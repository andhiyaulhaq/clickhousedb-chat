"""Second safety layer (the first is the read-only ClickHouse user). See docs/guide.md rule 3."""
import re
from pathlib import Path

import sqlglot
from sqlglot import exp

SCHEMA = Path(__file__).resolve().parents[2] / "clickhouse" / "schema.sql"
MAX_LIMIT = 1000


class Invalid(ValueError):
    """Query is unsafe or malformed. Retry may help."""


class Unanswerable(Invalid):
    """Unknown table or column: the data cannot answer this. Do not retry."""


_SQL = SCHEMA.read_text(encoding="utf-8")
_DDL = sqlglot.parse(_SQL, read="clickhouse")
TABLES = {s.this.this.name: {c.name for c in s.this.expressions} for s in _DDL}
COLUMNS = set().union(*TABLES.values())
# ReplacingMergeTree tables show duplicate row versions unless read with FINAL
REPLACING = {s.this.this.name for s in _DDL if "ReplacingMergeTree" in s.sql(dialect="clickhouse")}
# customers.attributes is a free-form Map, so the model can invent keys (attributes['city']); the real ones are in the schema comment
ATTR_KEYS = set(re.findall(r"'(\w+)' \(", re.search(r"attributes Map.*?keys: (.*)", _SQL).group(1)))


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

    if next(tree.find_all(exp.Table), None) is None:  # SELECT 'Good morning', SELECT now(): no data was read
        raise Unanswerable("query reads no table")

    aliases = {a.alias for a in tree.find_all(exp.Alias)}
    aliases |= {a.name for a in tree.find_all(exp.TableAlias)}
    aliases |= {c.name for a in tree.find_all(exp.TableAlias) for c in a.columns}
    # qualifier -> real table. An alias bound to two different tables (reused in a subquery) is ambiguous, so it is skipped.
    # A qualifier that is also a subquery or CTE alias (`(SELECT ... FROM customers AS c ...) AS c`) is ambiguous too.
    derived = ctes | {s.alias for s in tree.find_all(exp.Subquery) if s.alias}
    bound: dict[str, set[str]] = {}
    for t in tree.find_all(exp.Table):
        if t.name in TABLES and t.alias_or_name not in derived:
            bound.setdefault(t.alias_or_name, set()).add(t.name)
    for c in tree.find_all(exp.Column):
        owner = bound.get(c.table, set())
        if len(owner) == 1:  # d.value is checked against deals only: catches c.rep_id (rep_id lives on deals, not customers)
            if c.name not in TABLES[next(iter(owner))]:
                raise Unanswerable(f"unknown column: {c.table}.{c.name}")
        # ponytail: unqualified columns and subquery/CTE qualifiers are checked against all tables; resolve scopes properly if misses show up
        elif c.name not in COLUMNS and c.name not in aliases:
            raise Unanswerable(f"unknown column: {c.name}")

    for b in tree.find_all(exp.Bracket):
        if isinstance(b.this, exp.Column) and b.this.name == "attributes":
            for k in b.expressions:
                if isinstance(k, exp.Literal) and k.is_string and k.name not in ATTR_KEYS:
                    raise Unanswerable(f"unknown attributes key: {k.name}")

    for t in tree.find_all(exp.Table):
        if t.name in REPLACING and t.name not in ctes and not isinstance(t.parent, exp.Final):
            raise Invalid(f"missing FINAL on {t.name}")

    if isinstance(tree, exp.Select):
        lim = tree.args.get("limit")
        if lim is None:
            return f"{sql.strip().rstrip(';')} LIMIT {limit}"
        n = lim.expression
        if isinstance(n, exp.Literal) and n.is_int and int(n.name) <= limit:
            return sql.strip().rstrip(";")
    # UNION, or LIMIT missing/too large/non-literal: wrap so inner aggregates stay untouched
    return f"SELECT * FROM ({sql.strip().rstrip(';')}) LIMIT {limit}"
