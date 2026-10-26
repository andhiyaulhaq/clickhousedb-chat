"""Deterministic result shaping (docs/guide.md rules 5 and 6): mask PII, then pick a chart from the result's shape."""
import re

from app.schemas import Chart

# ponytail: masks emails by value pattern, so aliasing or concat cannot dodge it; names and companies stay readable for the pilot
EMAIL = re.compile(r"([\w.+-])[\w.+-]*(@[\w-]+(?:\.[\w-]+)+)")
DATE = re.compile(r"\d{4}-\d{2}(-\d{2})?( \d{2}:\d{2}:\d{2})?$")  # ClickHouse sends Date/DateTime as strings
MAX_BARS = 30


def _mask(v):
    if isinstance(v, str):
        return EMAIL.sub(r"\1***\2", v)
    if isinstance(v, list):  # array columns
        return [_mask(x) for x in v]
    return v


def mask(rows: list[list]) -> list[list]:
    return [[_mask(v) for v in row] for row in rows]


def kind(values) -> str:
    vs = [v for v in values if v is not None]
    if vs and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vs):
        return "number"
    if vs and all(isinstance(v, str) for v in vs):
        return "date" if all(DATE.match(v) for v in vs) else "text"
    return "other"


def pick_chart(columns: list[str], rows: list[list]) -> Chart | None:
    """None means table only. First column is the x axis, every other column must be a number."""
    if not rows:
        return None
    kinds = [kind(c) for c in zip(*rows)]
    if len(rows) == 1 and kinds == ["number"]:
        return Chart(type="stat", y=columns)
    if len(rows) < 2 or len(columns) < 2 or set(kinds[1:]) != {"number"}:
        return None
    if kinds[0] == "date":
        return Chart(type="line", x=columns[0], y=columns[1:])
    if kinds[0] == "text" and len(rows) <= MAX_BARS:
        return Chart(type="bar", x=columns[0], y=columns[1:])
    return None
