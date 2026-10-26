# ClickHouse Analytics Chatbot

Ask questions in Indonesian about CRM data. A fine-tuned 3B model (`text2sql-3b-v3`, running in Ollama) turns the question into ClickHouse SQL, the app validates and runs it read-only, and the answer comes back as a chart plus a short summary.

**Status:** model trained and evaluated (88 to 89.5% strict on 133 independent questions); the backend answers questions end to end (`POST /ask`: model, validator, restricted ClickHouse user, up to 2 repairs). Results come back with emails masked and a chart type chosen by rule; every question is logged to `data/logs/`. The chat UI is in `frontend/`; the summary is next. Internal pilot, local only. Details and build order: `docs/guide.md`.

## Quick start
```bash
docker compose up -d                       # ClickHouse 25.8 on :8123 (user default, password crm)
uv run python pipeline.py setup            # DROPS and recreates database crm, then seeds it
cd models/text2sql-3b-v3/output && ollama create text2sql-3b-v3 -f Modelfile   # once; needs the GGUF in that folder
uv run python pipeline.py ask "berapa omset bulan ini?"                  # question -> SQL -> rows
cd backend && uv run pytest                # validator (267 gold queries), executor (needs ClickHouse), repair loop
cd backend && uv run uvicorn app.main:app --port 8000   # POST /ask {"question": "..."}
cd frontend && pnpm install && pnpm dev    # chat UI on http://localhost:5173 (needs the backend on :8000)
cd backend && uv run python eval_gold.py holdout        # gold questions through the full pipeline (about 15 min)
```
Seeded dates are relative to the day you run `setup`, so "hari ini / kemarin" return no rows after a few days: re-run `setup`. Only one ClickHouse can hold port 8123; stop any other container first.

## Repo map
| Path | What |
|---|---|
| `backend/` | the app: validator, executor, `/ask` API (done); masking, charts, summary (todo). `uv` project |
| `frontend/` | Svelte chat UI (not started) |
| `clickhouse/` | `schema.sql` (DDL extract, source of the validator's whitelist), `seed.sql` (random CRM data), `app_user.sql` (the restricted user the app connects as) |
| `docker-compose.yml` | local ClickHouse (with a data volume) |
| `pipeline.py`, `pyproject.toml` | model workspace tooling: setup, build, eval, ask |
| `data/` | training pairs, eval sets (`gold/` is the app's), eval results |
| `models/text2sql-3b-v3/` | the model: README, `tools/` (notebook generator), `notebooks/` (Colab template + upload zip), `output/` (Modelfile, executed notebook, GGUF which is git-ignored) |
| `docs/` | see below |

## Docs
| Doc | Read it for |
|---|---|
| `docs/guide.md` | app spec: scope, architecture, stack, engineering rules, build order and status |
| `models/text2sql-3b-v3/README.md` | the model: profile, how to call it, accuracy, known limits |
| `docs/text2sql-spec.md` | what the model was trained on: schema, SQL rules 1-12, glossary (machine-read by `pipeline.py`) |
| `docs/training.md` | data layout, `pipeline.py` commands, how accuracy is scored, retrain loop |
| `docs/model-history.md` | the five trained versions and what changed between them |

## Origin
The model was built in `C:\najib\2_explore\slm-text2sql-clickhouse`. Its non-library files and the 3b-v3 weights were copied here, so this repo is the working copy; that project is a frozen original and the other four model versions stay there.
