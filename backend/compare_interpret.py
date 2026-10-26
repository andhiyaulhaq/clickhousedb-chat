"""Eyeball candidate models for the interpretation line, on gold questions with their known-correct SQL.

    uv run python compare_interpret.py qwen2.5:3b-instruct llama3.2 [N]
A line is good if it names the metric, the stage filter, the period and the grouping that the SQL really has, and nothing else.
Read it against the SQL: a fluent line that misdescribes the query is worse than no line.
"""
import json
import sys
import time
from pathlib import Path

from app import interpret

ROOT = Path(__file__).resolve().parents[1]


def main(models, n):
    gold = [json.loads(l) for f in ("holdout", "holdout_en") for l in (ROOT / "data" / "gold" / f"{f}.jsonl").read_text(encoding="utf-8").splitlines() if l]
    # spread over categories and both languages
    picks = gold[:: max(1, len(gold) // n)][:n]
    for g in picks:
        print(f"\n[{g['id']}] {g['question']}\n  SQL: {g['sql'][:300]}")
        for m in models:
            t0 = time.time()
            line = interpret.raw(g["question"], g["sql"], model=m)
            kept = line is not None and interpret.consistent(line, g["sql"])
            print(f"  {m:28s} ({time.time() - t0:.1f}s){'' if kept else ' DROPPED'} {line}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    n = int(args.pop()) if args and args[-1].isdigit() else 12
    main(args or ["qwen2.5:3b-instruct"], n)
