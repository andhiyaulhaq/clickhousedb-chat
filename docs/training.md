# Training and evaluation workflow

How the Text-to-SQL model is built, scored and retrained. Everything here runs from the repo root with `uv run python pipeline.py <command>` (stdlib only, no installs). For the model itself see `models/text2sql-3b-v3/README.md`; for the rules it was trained on see `docs/text2sql-spec.md`.

## Data layout
```
data/
  raw/            source question + SQL pairs (raw_*.jsonl): the only training data edited by hand
  holdout/        independent test pairs (raw_holdout_*.jsonl), never trained on
  train.jsonl  rejected.jsonl      built from raw/ by `build` (git-ignored, rebuild when needed)
  eval.jsonl   holdout.jsonl       dev and holdout sets in chat-message format, read by `eval`
  eval_keys.txt   frozen list of which raw pairs form the dev set
  gold/           the same 267 questions as {id, set, category, difficulty, question, sql}: the app's eval set
  results/        per-question predictions (eval_results_*.jsonl) and logs (eval_log_*.txt), the accuracy history
  archive/        old intermediates (git-ignored)
clickhouse/       schema.sql (DDL extract for the validator) and seed.sql (random CRM data, 2 years back, relative to now())
models/<name>/    one folder per model version:
  tools/build_notebook.py   generates notebooks/finetune.ipynb (holds this version's hyperparameters)
  notebooks/                finetune.ipynb (blank template) and colab_upload.zip (git-ignored)
  output/                   what Colab produced: Modelfile, executed finetune.ipynb, GGUF (git-ignored)
```

## Commands
| Command | What it does |
|---|---|
| `setup` | drops and recreates database `crm` in ClickHouse, runs the DDL from the spec and `clickhouse/seed.sql` |
| `gen N` | calls Gemini N times, appends raw pairs to `data/raw/raw.jsonl` (needs `GEMINI_API_KEY`) |
| `check <file>` | validates one raw file: `ERR` / `NOFINAL` / `DUP` / `EMPTY` per line |
| `build` | dedupes, lints and executes every `data/raw/raw*.jsonl` in ClickHouse, writes `train.jsonl`, `eval.jsonl`, `rejected.jsonl` |
| `holdout` | builds `data/holdout.jsonl` from `data/holdout/raw_holdout_*.jsonl` |
| `zip [model]` | bundles spec, seed, train and eval into `models/<model>/notebooks/colab_upload.zip` (default `text2sql-3b-v3`) |
| `eval <ollama-name> [N]` | execution accuracy on the dev set. Flags: `--set=holdout` for the independent set, `--retry=2` to let the model fix failing SQL, `--rescore` to re-check saved predictions without calling the model |
| `ask "<question>"` | question → SQL → rows, with 2 retries (model from `TEXT2SQL_MODEL`) |
| `test` | self-checks, including that the spec still parses (needs ClickHouse running) |

Environment: `CH_URL`, `CH_USER`, `CH_PASSWORD` (defaults match `docker-compose.yml`), `OLLAMA_URL`, `TEXT2SQL_MODEL`, `GEMINI_API_KEY`, `GEMINI_MODEL`.

## How accuracy is scored
Execution accuracy: the generated query must return the same **rows** as the reference query, not the same SQL text. **Strict** also needs the same columns (order may differ); **lenient** accepts extra columns. Outcomes per question: `ok`, `ok_extra_cols`, `partial_cols`, `wrong`, `error`. With about 130 questions the margin is about ±5 points.

- **Dev set** (134 questions): data was tuned against its failures, so it is optimistic.
- **Holdout** (133 questions): written independently and never trained on. This is the honest number.
- Both sets were written by Claude agents from the same spec, so real users' phrasing will probably score lower.
- Always score the Ollama (4-bit) model, not the Colab number. It runs 3 to 5 points lower.
- Relative dates resolve against the ClickHouse server clock. Seeded data is generated once, so "hari ini" / "kemarin" questions return no rows after a few days: re-run `setup`. Gold and generated SQL are compared on the same database, so a fresh seed does not invalidate a score, but it can shift it by a point or two (see the re-run in `models/text2sql-3b-v3/README.md`).
- `eval` overwrites `data/results/eval_results_<model>[_holdout].jsonl`. Rename a result file first if you want to keep it.

## Retrain loop
1. Find failures: read `data/results/eval_results_*.jsonl` for the wrong and partial questions, group them by pattern.
2. Add or relabel pairs in `data/raw/raw_*.jsonl`. If a rule changes, edit it in `docs/text2sql-spec.md` as well. Run `check` on the new file.
3. `build`, then `zip`.
4. Copy the previous `models/<name>/` folder as a starting point for the new version (keep `tools/`, empty `notebooks/` and `output/`), edit its `tools/build_notebook.py` for the new run, and run it to regenerate `notebooks/finetune.ipynb`. `zip <name>` writes `notebooks/colab_upload.zip`. Upload the zip to Colab and run the notebook on a T4 (about 2 h for 4,256 rows × 3 epochs).
5. Put what Colab produced (Modelfile, executed notebook, GGUF) in `models/<name>/output/` and register it: `cd models/<name>/output && ollama create <name> -f Modelfile`.
6. `eval <name>` and `eval <name> --set=holdout`. Record the numbers in `docs/model-history.md`.
7. If the schema changed, also update `clickhouse/schema.sql`, `clickhouse/seed.sql`, `data/gold/` and the validator whitelist. New tables need new training data.

Weights are not in git (`*.gguf`): on another machine, copy the GGUF into its folder or retrain.
