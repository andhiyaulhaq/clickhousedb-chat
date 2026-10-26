"""Full-pipeline accuracy on the gold questions (docs/guide.md rule 8a).

    uv run python eval_gold.py holdout [N]     # or: eval | both
Needs ClickHouse (seeded, app user) and Ollama. Prints strict/lenient like `pipeline.py eval`, so the numbers are comparable
with the bare-model scores; the gap is what validation and repairs add or lose. Per-question results go to data/results/.
"""
import json
import sys
import time
from collections import Counter, defaultdict
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import compare  # the same scorer behind every accuracy number in docs/model-history.md  # noqa: E402

from app import executor, text_to_sql, validator  # noqa: E402

# The app caps results at 1000 rows for display. Scoring raises the cap so a truncated listing is not counted wrong.
text_to_sql.validator.validate = partial(validator.validate, limit=10000)
text_to_sql.shaping.mask = lambda rows: rows  # gold SQL returns real emails, so masked rows would never match


def canon(rows):
    return [[json.dumps(round(v, 4) if isinstance(v, float) else v) for v in row] for row in rows]


def main(which, limit=None):
    gold = [json.loads(l) for l in (ROOT / "data" / "gold" / f"{which}.jsonl").read_text(encoding="utf-8").splitlines() if l]
    gold = gold[:limit]
    by_cat, results, secs, refused = defaultdict(Counter), [], [], 0
    for i, g in enumerate(gold, 1):
        t0 = time.time()
        ans = text_to_sql.ask(g["question"])
        secs.append(time.time() - t0)
        pred = None if ans.error else canon(ans.rows)
        refused += ans.error == text_to_sql.UNANSWERABLE
        verdict = compare(canon(executor.run(g["sql"])[1]), pred)
        by_cat[g["category"]][verdict] += 1
        results.append({"id": g["id"], "category": g["category"], "verdict": verdict, "attempts": ans.attempts,
                        "question": g["question"], "pred": ans.sql, "gold": g["sql"], "error": ans.error})
        print(f"[{i}/{len(gold)}] {verdict:13s} r{ans.attempts} {g['question'][:70]}", flush=True)
    out = ROOT / "data" / "results" / f"app_{which}.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    tot = sum(by_cat.values(), Counter())
    n = sum(tot.values())
    strict, lenient = tot["ok"], tot["ok"] + tot["ok_extra_cols"]
    print(f"\nfull pipeline on {which}: strict {strict}/{n} = {strict / n:.1%}, lenient {lenient}/{n} = {lenient / n:.1%}")
    print("  " + ", ".join(f"{k} {tot[k]}" for k in ["ok", "ok_extra_cols", "partial_cols", "wrong", "error"])
          + f", {sum(r['attempts'] > 0 for r in results)} needed repair, {refused} refused as unanswerable, avg {sum(secs) / n:.1f}s/query")
    print(f"  {'category':10s} strict lenient partial  of")
    for cat, c in sorted(by_cat.items()):
        print(f"  {cat:10s} {c['ok']:6d} {c['ok'] + c['ok_extra_cols']:7d} {c['partial_cols']:7d} {sum(c.values()):3d}")


if __name__ == "__main__":
    sets = ["eval", "holdout"] if sys.argv[1:2] == ["both"] else sys.argv[1:2] or ["holdout"]
    for s in sets:
        main(s, int(sys.argv[2]) if len(sys.argv) > 2 else None)
