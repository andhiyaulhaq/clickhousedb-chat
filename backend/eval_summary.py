"""How often does the model's paragraph survive the number check, and is it any good? (docs/guide.md section 3)

    uv run python eval_summary.py [N]
Runs gold questions (Indonesian and English holdouts) through ClickHouse with their gold SQL, builds the facts, asks the model for
the paragraph and prints it with the verdict. Needs ClickHouse and Ollama. Read the accepted paragraphs against the table: the
check covers numbers and rise/fall claims, not names or wording.
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

from app import executor, narrate, shaping, summary
from app.notes import is_english

ROOT = Path(__file__).resolve().parents[1]


def main(n):
    both = [[json.loads(l) for l in (ROOT / "data" / "gold" / f"{f}.jsonl").read_text(encoding="utf-8").splitlines() if l] for f in ("holdout", "holdout_en")]
    gold = [g for pair in zip(*both) for g in pair]  # Indonesian and English alternate
    cases, outcomes, secs = [], Counter(), []
    for g in gold[:: (len(gold) // (n * 3)) | 1]:  # an odd step, or every pick would land in the same language  # spread over categories and both languages; many are single values or lists
        cols, rows = executor.run(g["sql"])
        rows = shaping.mask(rows)
        facts = summary.facts(cols, rows, is_english(g["question"]), g["question"])
        if facts is None:
            continue
        job = narrate.register(g["question"], facts)
        t0 = time.time()
        r = narrate.run(job)
        secs.append(time.time() - t0)
        outcomes["ok" if r["outcome"] == "ok" else r["outcome"].split(" is ")[0].split(" the ")[0]] += 1
        cases.append((g, facts, r))
        print(f"\n[{g['id']}] {g['question']}\n  facts: {' | '.join(facts.lines)}\n  {r['outcome']} ({secs[-1]:.1f}s): {r['raw']}")
        if len(cases) >= n:
            break
    ok = sum(r["outcome"] == "ok" for _, _, r in cases)
    print(f"\n{ok}/{len(cases)} accepted, avg {sum(secs) / max(1, len(secs)):.1f}s. Outcomes: {dict(outcomes)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 15)
