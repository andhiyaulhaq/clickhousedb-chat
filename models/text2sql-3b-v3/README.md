# text2sql-3b-v3

Indonesian question → one ClickHouse SQL query, for the CRM schema in `docs/text2sql-spec.md`.

## Profile
| | |
|---|---|
| Base model | Qwen2.5-Coder-3B |
| Fine-tuning | LoRA (rank 16, lr 2e-4, loss on the SQL answer only) with Unsloth, 3 epochs on a Colab T4 (116 min) |
| Training data | 4,256 question + SQL pairs (`data/raw`), checked by running them in ClickHouse |
| Format | GGUF, 4-bit Q4_K_M, 1.93 GB (`text2sql-q4_k_m.gguf`, git-ignored) |
| Runtime | Ollama, about 2.1 GB RAM, about 6 s per query on CPU |
| Ollama name | `text2sql-3b-v3` |
| Context / sampling | 2,048 tokens, temperature 0, stop `<|im_end|>` |

Files here:
- `output/`: what Colab produced. `Modelfile` (system prompt, ChatML template, parameters), `finetune.ipynb` (the executed notebook with its training output, the record of this run), the GGUF.
- `notebooks/`: `finetune.ipynb` (blank template, generated) and `colab_upload.zip` (git-ignored, from `pipeline.py zip`).
- `tools/build_notebook.py`: regenerates the template; holds this run's hyperparameters.

## Task
- **Input:** one Indonesian question as the only user message. The system prompt (schema rules) is inside the Modelfile, so do not send your own.
- **Output:** one ClickHouse SQL statement, no explanation. Strip a ```` ```sql ```` fence if one appears.
- **Scope:** the five CRM tables only (`customers`, `sales_reps`, `deals`, `activities`, `support_tickets`). Single turn, no memory of earlier questions.
- **Conventions it learned:** `FINAL` on the ReplacingMergeTree tables, default listing columns per entity, id + name per entity, rounding and time buckets (rules 1-12 in `docs/text2sql-spec.md`).

## Use
```
cd models/text2sql-3b-v3/output && ollama create text2sql-3b-v3 -f Modelfile   # once, run from output/
ollama run text2sql-3b-v3 "berapa omset bulan ini?"
curl http://localhost:11434/api/chat -d '{"model":"text2sql-3b-v3","stream":false,"messages":[{"role":"user","content":"berapa omset bulan ini?"}]}'
```

## Accuracy
Execution accuracy: the generated query must return the same rows as the reference query. Strict needs the same columns; lenient accepts extra columns. Scored on the 4-bit model in Ollama.

| Test set | Strict | Lenient |
|---|---|---|
| Holdout, 133 independent questions, never trained or tuned on | 89.5% | 92.5% |
| Holdout re-run on this repo's database, 2026-10-25 | 88.0% | 91.0% |
| Dev eval, 134 questions, used to guide the data (optimistic) | 85.8% (86.6% with 2 retries) | 86.6% |
| **Full app pipeline** (model + validator + executor + up to 2 repairs), holdout, 2026-10-25 | 88.7% | 91.7% |
| **Full app pipeline**, dev set, 2026-10-25 | 85.1% | 85.1% |
| **Full app pipeline with input guard**, holdout, 2026-10-26 | 88.0% | 91.0% |
| **Full app pipeline**, **English** holdout (`data/gold/holdout_en.jsonl`, same 133 questions translated), 2026-10-26 | 81.2% | 82.0% |

The full-pipeline rows come from `backend/eval_gold.py`: the model's SQL was identical to the bare run for 130 of 134 dev questions, so validation and repairs neither add nor lose accuracy beyond noise (repairs rescued 1 question, as in the bare retry run). Re-seeding ClickHouse alone moves scores by about 1 point. Margin is about ±5 points. Both sets were written by Claude agents from the same spec, so expect lower accuracy on real users' phrasing. The weakest holdout categories in the re-run were `subquery` (12/17 strict), `window` (12/16) and `join2` (11/13). Per-question results are in `data/results/`.

The model was trained on Indonesian questions only. On the English translation of the holdout it scores about 7 points lower strict (and 9 lower lenient), with identical SQL for only 57 of 133 questions. The gap is systematic, not random: the model reads "last year" and "last month" as a rolling window (`subtractYears(now(), 1)`) instead of the calendar period it learned for "tahun lalu" (5 questions), drops `stage = 'won'` for "revenue" (3), and returns only id and name for listings (4 partial_cols). The fix would be English paraphrases in the training data (retrain), not app code.

## Known limits
- **Joining two fact tables** (deals + tickets, deals + activities) for per-customer or per-rep totals often sums across multiplied rows. The query runs and returns wrong numbers silently. This is the most common real error.
- **List/cari questions** sometimes return only id and name instead of the default columns, or add a count column the reference does not.
- **Unanswerable questions are not refused.** Tickets have no sales rep, so "tiket per tim sales" has no correct query; the model invents a column and the query errors.
- **Relative dates** ("bulan ini", "kemarin") resolve against the ClickHouse server clock.

## History and retraining
This is the fifth and best of five trained versions: see `docs/model-history.md` for the others and what changed. Retraining steps are in `docs/training.md`.

The GGUF is git-ignored (1.9 GB). On another machine copy it into this folder, then register it as above, or retrain.
