"""Facts and a one-sentence summary about the result, computed by rules from the rows (docs/guide.md section 3).

Nothing here uses a model. summarize() is the sentence shown at once: the highest and lowest value of the first numeric column and
what they belong to. facts() is what narrate.py hands to the model, and the only numbers its text may contain. Neither sums or
averages a column that is not additive (rates, averages, maximums), because adding those up would say something false. Both return
None when there is nothing useful to add: a single value, a plain list or a flat result are already clear from the stat tile and table.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from app.notes import partial_period, totals_misleading
from app.shaping import kind

ALL_VALUES = 12  # up to this many rows, every value of the metric is given as a fact


def _num(v: float, english: bool) -> str:
    """Indonesian style by default (1.234,5), abbreviated from a million up (86,6 juta)."""
    for limit, idn, en in ((1e9, "miliar", "billion"), (1e6, "juta", "million")):
        if abs(v) >= limit:
            s, unit = f"{v / limit:,.1f}".removesuffix(".0"), en if english else idn
            return f"{s if english else s.translate(_SWAP)} {unit}"
    s = f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return s if english else s.translate(_SWAP)


_SWAP = str.maketrans(",.", ".,")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def number_tokens(text: str) -> set[str]:
    """Every number in a text, with leading zeros dropped from whole numbers (a date's '03' is the model's '3')."""
    return {(t.lstrip("0") or "0") if t.isdigit() else t for t in _NUMBER.findall(text)}


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


def _labeler(labels: list, sql: str, english: bool):
    """2026-07-01 is shown as Juli 2026 for monthly data, Q3 2026 for quarterly, 2026 for yearly, and so on. A label that is not a date stays as is."""
    kind_, names = period_kind(labels, sql), _MONTHS[english]

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


def _extract(columns: list[str], rows: list[list], trim: bool = False):
    """(is a series, label column, metric column, all (label, value), the ones that count) for the first numeric column, or None.
    With trim, a series drops its first and last period from the ones that count: they are partial in a rolling window."""
    if len(rows) < 2:
        return None
    kinds = [kind(c) for c in zip(*rows)]
    metric = next((i for i, k in enumerate(kinds) if k == "number"), None)
    if metric is None:
        return None
    series = kinds[0] == "date"
    # what the number belongs to: the date, or the first text column that is not an id (customer_id, rep_id)
    texts = [i for i, k in enumerate(kinds) if k == "text"]
    label = 0 if series else next((i for i in texts if not columns[i].lower().endswith("id")), texts[0] if texts else None)
    if label is None:
        return None
    pairs = [(r[label], r[metric]) for r in rows if r[metric] is not None]
    if len(pairs) < 2:
        return None
    core = sorted(pairs, key=lambda p: p[0])[1:-1] if trim and series and len(pairs) >= 4 else pairs
    if max(p[1] for p in core) == min(p[1] for p in core):
        return None
    return series, label, metric, pairs, core


def summarize(columns: list[str], rows: list[list], english: bool = False, sql: str = "") -> str | None:
    found = _extract(columns, rows, partial_period(sql))
    if found is None:
        return None
    series, label, metric, pairs, core = found
    L = _labeler([p[0] for p in pairs], sql, english) if series else (lambda x: x)
    (hl, hv), (ll, lv) = max(core, key=lambda p: p[1]), min(core, key=lambda p: p[1])
    name, hi, lo = columns[metric].replace("_", " "), _num(hv, english), _num(lv, english)
    left_out = core is not pairs  # the partial first and last period
    if english:
        return (f"{len(rows)} periods. {name}: highest on {L(hl)} ({hi}), lowest on {L(ll)} ({lo})." if series
                else f"{len(rows)} rows. {name}: highest {L(hl)} ({hi}), lowest {L(ll)} ({lo}).") + (" (First and last period left out: partial.)" if left_out else "")
    return (f"{len(rows)} periode. {name}: tertinggi pada {L(hl)} ({hi}), terendah pada {L(ll)} ({lo})." if series
            else f"{len(rows)} baris. {name}: tertinggi {L(hl)} ({hi}), terendah {L(ll)} ({lo}).") + (" (Periode pertama dan terakhir tidak dihitung: belum penuh.)" if left_out else "")


# A column that can be added up. Rates, averages and "the largest X per row" cannot, and neither can running totals.
_ADDITIVE = re.compile(r"omset|revenue|total|jumlah|count|nilai|value|tiket|ticket|deal|\bn\b", re.I)
_NOT_ADDITIVE = re.compile(r"rate|rasio|ratio|rata|avg|average|persen|percent|median|terbesar|tertinggi|terendah|max|min|win|kumulatif|cumulative|running", re.I)


@dataclass
class Facts:
    lines: list[str]  # all the model is told, and the only things its text may state
    trend: str | None  # "up" or "down" for a series, else None
    english: bool
    allowed: set[str] = field(default_factory=set)  # the only numbers the model's text may contain
    owners: dict[str, set[str]] = field(default_factory=dict)  # number -> the labels it belongs to (text labels only)


def facts(columns: list[str], rows: list[list], english: bool = False, question: str = "", sql: str = "") -> Facts | None:
    found = _extract(columns, rows, partial_period(sql))
    if found is None:
        return None
    series, label, metric, pairs, core = found
    L = _labeler([p[0] for p in pairs], sql, english) if series else (lambda x: x)
    name, n = columns[metric].replace("_", " "), len(rows)
    (hl, hv), (ll, lv) = max(core, key=lambda p: p[1]), min(core, key=lambda p: p[1])
    f = lambda v: _num(v, english)
    en = english
    owners: dict[str, set[str]] = {}

    def own(text, who):  # a number said about the wrong item is wrong even if the number is real
        if not series:
            for t in number_tokens(text):
                owners.setdefault(t, set()).add(str(who))

    own(f(hv), hl)
    own(f(lv), ll)
    lines = [f"number of rows: {n}" if en else f"jumlah baris: {n}",
             # the label column is named: "New Logo #870" is a deal title, and without that the model called it a sales rep
             f"{name}: highest {columns[label]} {L(hl)} ({f(hv)}); lowest {columns[label]} {L(ll)} ({f(lv)})" if en
             else f"{name}: tertinggi {columns[label]} {L(hl)} ({f(hv)}); terendah {columns[label]} {L(ll)} ({f(lv)})"]
    if core is not pairs:  # "1 tahun terakhir" starts mid-month: the model called the 6-day October the lowest month
        first, last = sorted(pairs, key=lambda p: p[0])[0][0], sorted(pairs, key=lambda p: p[0])[-1][0]
        lines.append(f"the first period ({L(first)}) and the last ({L(last)}) are partial, so they are not counted as highest, lowest or the start or end of a change" if en
                     else f"periode pertama ({L(first)}) dan terakhir ({L(last)}) belum penuh, jadi tidak dihitung sebagai tertinggi, terendah, atau awal dan akhir perubahan")
    if n <= ALL_VALUES:
        shown = sorted(pairs, key=lambda p: p[0] if series else -p[1])
        lines.append(f"values per {columns[label]}: " if en else f"nilai per {columns[label]}: ")
        lines[-1] += ", ".join(f"{L(l)} ({f(v)})" for l, v in shown)
        for l, v in shown:
            own(f(v), l)
    total = sum(p[1] for p in pairs)
    # not for a top N or overlapping groups: 101,1 juta was the sum of 5 reps, and was read as company revenue
    if (_ADDITIVE.search(columns[metric]) and not _NOT_ADDITIVE.search(columns[metric]) and total > 0 and min(p[1] for p in pairs) >= 0
            and not totals_misleading(sql)):
        lines.append(f"sum over all rows of {name}: {f(total)}" if en else f"jumlah seluruh baris untuk {name}: {f(total)}")
        share = hv / total * 100
        own(f"{share:.0f}", hl)
        lines.append(f"{L(hl)} accounts for {share:.0f}% of the total" if en else f"{L(hl)} menyumbang {share:.0f}% dari total")
    trend = None
    if series:
        ordered = sorted(core, key=lambda p: p[0])
        (fl, fv), (el, ev) = ordered[0], ordered[-1]
        if fv and round(abs((ev - fv) / abs(fv) * 100)) >= 1:
            pct = (ev - fv) / abs(fv) * 100
            trend = "up" if pct > 0 else "down"
            word = ("rose" if pct > 0 else "fell") if en else ("naik" if pct > 0 else "turun")
            lines.append(f"{name} from {L(fl)} to {L(el)}: {word} {abs(pct):.0f}%" if en else f"{name} dari {L(fl)} ke {L(el)}: {word} {abs(pct):.0f}%")
    owners.pop(str(n), None)  # the row count is not about any one item
    return Facts(lines, trend, en, number_tokens(" ".join(lines + [question])), owners)
