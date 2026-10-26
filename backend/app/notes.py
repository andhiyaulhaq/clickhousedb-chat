"""Caveats about how the SQL read the question, computed from the SQL itself (docs/guide.md section 3).

No model. An earlier version asked a small instruct model to paraphrase the SQL ("how I read your question"). It mostly
restated the question, was misleading in 2 of the first 10 real answers and cost 4 to 6 s of an 11 s answer, so it was removed.
What stayed are the checks that cannot be wrong because they read the SQL and nothing else.
"""
import calendar
import re
from datetime import date, timedelta

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
    only partly covered, so a low there is not a real dip. A window aligned to a period
    (toStartOfYear(subtractYears(today(), 1))) is whole at the start. The end is a separate question: see period_in_progress."""
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
    - a rolling window grouped by period: the first period is partial
    - a long ranking (ORDER BY ... DESC, no LIMIT) came back whole: "customer with the largest deal" returned 291 rows"""
    notes = []
    if re.search(r"\barray\s+join\b", sql, re.I) and re.search(r"\bgroup\s+by\b", sql, re.I):
        notes.append("(A row with several products or tags is counted in each of them, so the groups can add up to more than the real total.)" if english
                     else "(Satu baris yang punya beberapa produk atau tag dihitung di setiap grupnya, jadi jumlah antar grup bisa melebihi total sebenarnya.)")
    if partial_period(sql):
        notes.append("(The first period is partial because the time range is counted back from today.)" if english
                     else "(Periode pertama belum penuh karena rentang waktu dihitung mundur dari hari ini.)")
    if n_rows > PREVIEW_ROWS and _unbounded_ranking(sql):
        notes.append("(All matching rows are shown, sorted descending, not just the top ones.)" if english
                     else "(Semua baris yang cocok ditampilkan, diurutkan menurun, bukan hanya yang teratas.)")
    return " ".join(notes)


_MONTHS_SHORT = {
    False: ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
    True: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
_MONTHS = {
    False: ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"],
    True: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
}


def _parse(label) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?(?: (\d{2}:\d{2}:\d{2}))?$", str(label))
    if m is None or m[4] not in (None, "00:00:00"):  # an hourly series has no label better than the timestamp
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3] or 1))
    except ValueError:
        return None


def period_kind(labels: list, sql: str = "") -> str | None:
    """month, quarter, year, week or day, from the labels (and the grouping function in the SQL when the labels are ambiguous)."""
    ds = [_parse(l) for l in labels]
    if not ds or None in ds:
        return None
    ds, low = sorted(set(ds)), sql.lower()
    if all(d.day == 1 for d in ds):
        if all(d.month == 1 for d in ds) and "tostartofmonth" not in low:
            return "year"
        if all(d.month in (1, 4, 7, 10) for d in ds):
            if "tostartofquarter" in low:
                return "quarter"
            months = [d.year * 12 + d.month for d in ds]
            if "tostartofmonth" not in low and len(ds) >= 2 and all((b - a) % 3 == 0 for a, b in zip(months, months[1:])):
                return "quarter"
        return "month"
    same_weekday = len({d.weekday() for d in ds}) == 1
    if same_weekday and ("tostartofweek" in low or "tomonday" in low or (len(ds) >= 2 and all((b - a).days % 7 == 0 for a, b in zip(ds, ds[1:])))):
        return "week"
    return "day"


def labeler(labels: list, sql: str, english: bool, short: bool = False):
    """2026-07-01 is shown as Juli 2026 for monthly data, Q3 2026 for quarterly, 2026 for yearly, and so on. A label that is not a date stays as is."""
    kind_, names = period_kind(labels, sql), (_MONTHS_SHORT if short else _MONTHS)[english]

    def fmt(label):
        d = _parse(label)
        if d is None or kind_ is None:
            return label
        if kind_ == "month":
            return f"{names[d.month - 1]} {d.year}"
        if kind_ == "quarter":
            return f"Q{(d.month - 1) // 3 + 1} {d.year}"
        if kind_ == "year":
            return str(d.year)
        when = f"{d.day} {names[d.month - 1]} {d.year}"
        return (f"week of {when}" if english else f"minggu {when}") if kind_ == "week" else when
    return fmt


def today() -> date:
    return date.today()  # a function, so a test can pin it


def period_in_progress(label, kind_: str | None, now: date) -> bool:
    """The period the label starts is not over yet: this month's value is a part of a month, and 'up 6% since January' is distorted."""
    d = _parse(label)
    if d is None or kind_ is None:
        return False
    if kind_ == "month":
        return (d.year, d.month) == (now.year, now.month)
    if kind_ == "quarter":
        return d.year == now.year and (d.month - 1) // 3 == (now.month - 1) // 3
    if kind_ == "year":
        return d.year == now.year
    if kind_ == "week":
        return d <= now < d + timedelta(days=7)
    return d == now


def _in_progress_note(labels: list, sql: str, english: bool) -> str:
    """For a series whose window ends today, name the unfinished last period: its value is not final."""
    ds = [(_parse(l), l) for l in labels]
    if not ds or any(d is None for d, _ in ds):
        return ""
    kind_ = period_kind(labels, sql)
    last = max(ds)[1]
    if not period_in_progress(last, kind_, today()):
        return ""
    when = labeler(labels, sql, english)(last)
    return f"(The last period, {when}, is still in progress, so its value is not final.)" if english else f"(Periode terakhir, {when}, masih berjalan, jadi nilainya belum final.)"


# "1 tahun terakhir" per month is the last 12 whole months, not a window that starts mid-month and ends in the month in progress
_GRANULARITY = ("Week", "Month", "Quarter", "Year")  # the finest grouping function in the SQL decides
_ANCHOR = re.compile(
    r"(?P<col>[A-Za-z_][\w.]*)\s*>=\s*(?:subtract(?P<unit>Years|Quarters|Months|Weeks|Days)\(\s*(?:now|today)\(\)\s*,\s*(?P<n>\d+)\s*\)"
    r"|(?:now|today)\(\)\s*-\s*INTERVAL\s+(?P<n2>\d+)\s+(?P<unit2>YEAR|QUARTER|MONTH|WEEK|DAY)S?)", re.I)
_UNITS = {"YEAR": "Years", "QUARTER": "Quarters", "MONTH": "Months", "WEEK": "Weeks", "DAY": "Days"}
# which windows can be made of whole periods: "6 minggu terakhir" per month cannot, and days never can
_ALIGNABLE = {"Month": {"Years", "Quarters", "Months"}, "Week": {"Years", "Quarters", "Months", "Weeks"}, "Quarter": {"Years", "Quarters"}, "Year": {"Years"}}


def _shift_months(d: date, k: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + k, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def _period_start(d: date, gran: str) -> date:
    if gran == "Week":
        return d - timedelta(days=d.weekday())
    return date(d.year, {"Month": d.month, "Quarter": 3 * ((d.month - 1) // 3) + 1, "Year": 1}[gran], 1)


def align_window(sql: str, now: date) -> tuple[str, dict | None]:
    """Rewrite `col >= subtractMonths(now(), 12)` over monthly (or weekly, quarterly, yearly) groups into whole periods ending before the
    current one: `col >= toStartOfMonth(subtractMonths(today(), 12)) AND col < toStartOfMonth(today())`. Returns the SQL and the first and last
    period it covers, or the SQL unchanged and None. A window that already has an upper bound, or a unit that cannot make whole periods, is left alone."""
    gran = next((g for g in _GRANULARITY if re.search(rf"toStartOf{g}\(", sql, re.I)), None)
    if gran is None:
        return sql, None
    mode, found = ", 1" if gran == "Week" else "", []

    def fix(m):
        unit, n, col = m["unit"] or _UNITS[m["unit2"].upper()], int(m["n"] or m["n2"]), m["col"]
        if unit not in _ALIGNABLE[gran] or re.search(re.escape(col) + r"\s*<", sql):
            return m.group(0)
        found.append((unit, n))
        return f"{col} >= toStartOf{gran}(subtract{unit}(today(), {n}){mode}) AND {col} < toStartOf{gran}(today(){mode})"

    new = _ANCHOR.sub(fix, sql)
    if not found:
        return sql, None
    unit, n = found[0]
    back = now - timedelta(days=7 * n) if unit == "Weeks" else _shift_months(now, -n * {"Years": 12, "Quarters": 3, "Months": 1}[unit])
    current = _period_start(now, gran)
    last = {"Week": current - timedelta(days=7), "Month": _shift_months(current, -1), "Quarter": _shift_months(current, -3), "Year": date(now.year - 1, 1, 1)}[gran]
    return new, {"start": _period_start(back, gran).isoformat(), "end": last.isoformat()}


def window_note(window: dict, sql: str, english: bool) -> str:
    fmt = labeler([window["start"], window["end"]], sql, english)
    a, b = fmt(window["start"]), fmt(window["end"])
    if english:
        return f"(Time range adjusted to whole periods: {a} to {b}.)" if a != b else f"(Time range adjusted to a whole period: {a}.)"
    return f"(Rentang waktu disesuaikan ke periode penuh: {a} sampai {b}.)" if a != b else f"(Rentang waktu disesuaikan ke periode penuh: {a}.)"


def caveats(sql: str, n_rows: int, english: bool, labels: list | None = None, window: dict | None = None) -> str | None:
    """labels: the first column of a date series, for the unfinished-period note. window: what align_window returned."""
    parts = [window_note(window, sql, english) if window else "", date_basis(sql, english), shape_note(sql, n_rows, english),
             _in_progress_note(labels, sql, english) if labels else ""]
    return " ".join(filter(None, parts)) or None
