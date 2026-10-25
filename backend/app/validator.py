"""Second safety layer (the first is the read-only ClickHouse user). See docs/guide.md rule 3."""
from pathlib import Path

import sqlglot
from sqlglot import exp

SCHEMA = Path(__file__).resolve().parents[2] / "clickhouse" / "schema.sql"
MAX_LIMIT = 1000


class Invalid(ValueError):
    """Query is unsafe or malformed. Retry may help."""


class Unanswerable(Invalid):
    """Unknown table or column: the data cannot answer this. Do not retry."""


def _load_schema() -> dict[str, set[str]]:
    stmts = sqlglot.parse(SCHEMA.read_text(encoding="utf-8"), read="clickhouse")
    return {s.this.this.name: {c.name for c in s.this.expressions} for s in stmts}


TABLES = _load_schema()
COLUMNS = set().union(*TABLES.values())


def validate(sql: str, limit: int = MAX_LIMIT) -> str:
    """Return safe SQL with a LIMIT, or raise Invalid / Unanswerable."""
    try:
        stmts = sqlglot.parse(sql.strip().rstrip(";"), read="clickhouse")
    except sqlglot.errors.SqlglotError as e:
        raise Invalid(f"cannot parse: {e}") from e
    if len(stmts) != 1 or stmts[0] is None:
        raise Invalid("exactly one statement required")
    tree = stmts[0]
    if not isinstance(tree, exp.Query):
        raise Invalid("only SELECT is allowed")

    ctes = {c.alias for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):  # url(), file(), remote(), ...
            raise Invalid("table functions are not allowed")
        if t.name in ctes and not t.db:
            continue
        if t.db not in ("", "crm") or t.name not in TABLES:
            raise Unanswerable(f"unknown table: {t.sql(dialect='clickhouse')}")

    # ponytail: columns checked against the union of all tables, not per table; qualify-based check if misses show up
    aliases = {a.alias for a in tree.find_all(exp.Alias)}
    aliases |= {a.name for a in tree.find_all(exp.TableAlias)}
    aliases |= {c.name for a in tree.find_all(exp.TableAlias) for c in a.columns}
    for c in tree.find_all(exp.Column):
        if c.name not in COLUMNS and c.name not in aliases:
            raise Unanswerable(f"unknown column: {c.name}")

    if isinstance(tree, exp.Select):
        lim = tree.args.get("limit")
        if lim is None:
            return f"{sql.strip().rstrip(';')} LIMIT {limit}"
        n = lim.expression
        if isinstance(n, exp.Literal) and n.is_int and int(n.name) <= limit:
            return sql.strip().rstrip(";")
    # UNION, or LIMIT missing/too large/non-literal: wrap so inner aggregates stay untouched
    return f"SELECT * FROM ({sql.strip().rstrip(';')}) LIMIT {limit}"
