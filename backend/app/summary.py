"""One sentence about the result, built by rules from the rows (docs/guide.md section 3).

No model on purpose: a small model can misstate a number, and the sentence is only worth showing if every figure in it is
true. It states the highest and lowest value of the first numeric column and what they belong to. It never sums or averages,
because adding up rates or averages would say something false. Returns None when there is nothing useful to add: the stat
tile, the chart and the table already show a single value, a plain list, or a flat result.
"""
from app.shaping import kind


def _num(v: float, english: bool) -> str:
    """Indonesian style by default (1.234,5), abbreviated from a million up (86,6 juta)."""
    for limit, idn, en in ((1e9, "miliar", "billion"), (1e6, "juta", "million")):
        if abs(v) >= limit:
            s, unit = f"{v / limit:,.1f}".removesuffix(".0"), en if english else idn
            return f"{s if english else s.translate(_SWAP)} {unit}"
    s = f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return s if english else s.translate(_SWAP)


_SWAP = str.maketrans(",.", ".,")


def summarize(columns: list[str], rows: list[list], english: bool = False) -> str | None:
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
    (hl, hv), (ll, lv) = max(pairs, key=lambda p: p[1]), min(pairs, key=lambda p: p[1])
    if hv == lv:
        return None
    name, hi, lo = columns[metric].replace("_", " "), _num(hv, english), _num(lv, english)
    if english:
        return (f"{len(rows)} periods. Highest {name} on {hl} ({hi}), lowest on {ll} ({lo})." if series
                else f"{len(rows)} rows. Highest {name}: {hl} ({hi}); lowest: {ll} ({lo}).")
    return (f"{len(rows)} periode. {name} tertinggi pada {hl} ({hi}), terendah pada {ll} ({lo})." if series
            else f"{len(rows)} baris. {name} tertinggi: {hl} ({hi}); terendah: {ll} ({lo}).")
