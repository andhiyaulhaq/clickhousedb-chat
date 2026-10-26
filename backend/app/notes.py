"""Caveats about how the SQL read the question, computed from the SQL itself (docs/guide.md section 3).

No model. An earlier version asked a small instruct model to paraphrase the SQL ("how I read your question"). It mostly
restated the question, was misleading in 2 of the first 10 real answers and cost 4 to 6 s of an 11 s answer, so it was removed.
What stayed are the checks that cannot be wrong because they read the SQL and nothing else.
"""
import re

import sqlglot
from sqlglot import exp

# Language of the question, for the notes, the summary and the "what can I ask?" answer. Word lists, tuned on the gold questions:
# no word that is also Indonesian or SQL-ish (total, in, to, all, list). A tie, or a mixed question, stays Indonesian.
_EN = {"the", "how", "what", "which", "show", "each", "with", "and", "of", "for", "who", "are", "is", "have", "last", "this", "than",
       "more", "most", "many", "did", "does", "from", "revenue", "average", "rank", "number", "only", "please", "by", "customers",
       "reps", "tickets", "products", "companies", "activity", "duration", "value"}
_ID = {"yang", "berapa", "dan", "di", "tiap", "dengan", "tampilkan", "siapa", "apa", "dari", "untuk", "ada", "tahun", "bulan",
       "lebih", "pelanggan", "mana", "sama", "yg", "brp", "tolong", "dong", "kasih", "cari", "milik", "semua", "pernah", "masih",
       "sudah", "belum", "tidak", "jumlah", "omset", "tiket", "rata", "aktivitas"}

PREVIEW_ROWS = 20  # the UI shows this many rows first


def is_english(question: str) -> bool:
    words = re.findall(r"[a-z']+", question.lower())
    return sum(w in _EN for w in words) > sum(w in _ID for w in words)


# deals have two dates, so "last month" is ambiguous: say which one the SQL used
_DATE_BASIS = (("created_date", "tanggal deal dibuat", "deal creation date"),
               ("closed_date", "tanggal deal ditutup", "deal close date"))


def date_basis(sql: str, english: bool) -> str:
    used = [(i, e) for col, i, e in _DATE_BASIS if col in sql.lower()]
    if not used:
        return ""
    return f"(Date basis: {' and '.join(e for _, e in used)}.)" if english else f"(Dasar tanggal: {' dan '.join(i for i, _ in used)}.)"


_PERIOD = re.compile(r"toStartOf(?:Month|Week|Quarter|Year)\(", re.I)
_ROLLING = re.compile(r"subtract(?:Years|Months|Quarters|Weeks|Days)\(\s*(?:now|today)\(\)|(?:now|today)\(\)\s*-\s*INTERVAL", re.I)


def partial_period(sql: str) -> bool:
    """Grouped by month, week, quarter or year over a window counted back from today (\"1 tahun terakhir\"): the first period is
    only partly covered, and so is the last, so a low at either end is not a real dip. A window aligned to a period
    (toStartOfYear(subtractYears(today(), 1))) is whole."""
    if not _PERIOD.search(sql):
        return False
    return any(not re.search(r"toStartOf\w+\(\s*$", sql[:m.start()], re.I) for m in _ROLLING.finditer(sql))


def totals_misleading(sql: str) -> bool:
    """The sum of the returned rows is not a real total: a top N (LIMIT) leaves rows out, and a grouped ARRAY JOIN counts a row once
    per product or tag. A share of that sum is misleading too."""
    return bool(re.search(r"\blimit\b", sql, re.I) or (re.search(r"\barray\s+join\b", sql, re.I) and re.search(r"\bgroup\s+by\b", sql, re.I)))


def _unbounded_ranking(sql: str) -> bool:
    try:
        tree = sqlglot.parse_one(sql, read="clickhouse")
    except sqlglot.errors.SqlglotError:
        return False
    order = tree.args.get("order") if isinstance(tree, exp.Select) else None
    return order is not None and tree.args.get("limit") is None and bool(order.expressions[0].args.get("desc"))


def shape_note(sql: str, n_rows: int, english: bool) -> str:
    """- a grouped ARRAY JOIN counts a row once per product or tag, so the groups add up to more than the real total
    - a rolling window grouped by period: the first and last periods are partial
    - a long ranking (ORDER BY ... DESC, no LIMIT) came back whole: "customer with the largest deal" returned 291 rows"""
    notes = []
    if re.search(r"\barray\s+join\b", sql, re.I) and re.search(r"\bgroup\s+by\b", sql, re.I):
        notes.append("(A row with several products or tags is counted in each of them, so the groups can add up to more than the real total.)" if english
                     else "(Satu baris yang punya beberapa produk atau tag dihitung di setiap grupnya, jadi jumlah antar grup bisa melebihi total sebenarnya.)")
    if partial_period(sql):
        notes.append("(The first and last periods are partial because the time range is counted back from today.)" if english
                     else "(Periode pertama dan terakhir belum penuh karena rentang waktu dihitung mundur dari hari ini.)")
    if n_rows > PREVIEW_ROWS and _unbounded_ranking(sql):
        notes.append("(All matching rows are shown, sorted descending, not just the top ones.)" if english
                     else "(Semua baris yang cocok ditampilkan, diurutkan menurun, bukan hanya yang teratas.)")
    return " ".join(notes)


def caveats(sql: str, n_rows: int, english: bool) -> str | None:
    return " ".join(filter(None, [date_basis(sql, english), shape_note(sql, n_rows, english)])) or None
