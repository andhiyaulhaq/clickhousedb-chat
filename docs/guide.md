# ClickHouse Analytics Chatbot: Project Specification

Blueprint for AI coding agents building the app. Read it fully before writing code. Decisions marked **Decided** were made with the owner; do not reopen them without a reason.

Where things are documented (one place each):
- Repo map, quick start, doc index: `README.md`
- The Text-to-SQL model (profile, accuracy, limits): `models/text2sql-3b-v3/README.md`
- What the model was trained on (schema, SQL rules, glossary): `docs/text2sql-spec.md`
- Training, scoring, retraining: `docs/training.md`; earlier model versions: `docs/model-history.md`

---

## 1. Objective & Scope

A chat app where users ask questions in **Indonesian** about CRM data. The system translates the question to ClickHouse SQL with a fine-tuned small model, validates and runs it read-only, and returns a chart plus a short text summary.

**Scope (Decided):**
- One schema only: the CRM schema (`customers`, `sales_reps`, `deals`, `activities`, `support_tickets`). The SQL model was trained on it; new tables need retraining.
- Single-turn questions in v1. The model has no conversation memory, so a follow-up like "yang tadi, per bulan" will not work. A follow-up rewriter is a later step.
- Local only: ClickHouse in Docker, models in Ollama on CPU. The Text-to-SQL model must stay within about 3 GB of memory.
- Internal pilot, one tester for now.

---

## 2. The Text-to-SQL model as a dependency

The app treats the model as an external service reached over HTTP. Do not retrain from the app code; the retrain loop is in `docs/training.md`.

**Contract:** send only the user message (the system prompt is inside the Modelfile and temperature is already 0). The reply is one ClickHouse statement, sometimes wrapped in a ```` ```sql ```` fence: strip it.
```
POST http://localhost:11434/api/chat
{"model":"text2sql-3b-v3","stream":false,"messages":[{"role":"user","content":"berapa omset bulan ini?"}]}
```
About 6 s per query on CPU, about 2.1 GB RAM. Holdout accuracy is 88 to 89.5% strict (see the model README), measured on questions written by Claude, so expect lower on real users.

**Known failure modes and what the app does about each:**

| Failure mode | App mitigation |
|---|---|
| Joining two fact tables (deals + tickets, deals + activities) for per-customer or per-rep totals sums across multiplied rows. The query runs and returns **wrong numbers silently**. The most common real error. | Always show the SQL and the interpretation line. Candidate: detect aggregation across two fact tables in the validator and warn in the UI. Retries cannot catch it. |
| "List/cari" questions sometimes return only id and name instead of the default columns. | Cosmetic; visible in the table. |
| Questions the schema cannot answer (tickets per sales team: `support_tickets` has no rep) are not refused; the model invents a column and the query errors. | Validator raises `Unanswerable` on an unknown table or column: answer "cannot be answered from this data", no retry. |

**Schema facts that matter to the app:**
- `customers.email` is sensitive; `name` and `company` also identify people (rule 5 below).
- `customers`, `deals` and `support_tickets` are ReplacingMergeTree and need `FINAL` (the model does this). `sales_reps` and `activities` do not.
- Seed size as printed by `setup`: 2,300 customer rows (count with `FINAL` for current rows), 40 reps, 8,000 deals, 30,000 activities, 5,000 tickets.

**Code to port from the root `pipeline.py`:** `ch` / `rows_of` (ClickHouse over HTTP, readonly), `_covers` / `compare` (row comparison behind every accuracy number), `clean_sql` / `ollama` / `generate_sql` (model call, fence stripping, retry), `final_ok` (FINAL lint). Retry gave +1 of 134 questions at 2 retries, so use **2 retries**, not more.

---

## 3. Architecture & Data Flow (Decided)

Defense in depth, but only as many model calls as needed. Safety is enforced in the database first, in Python second.

```text
[ User question ]
      │
      ▼
1. Cheap input checks (deterministic): length limit, empty check, obvious injection patterns
      │
      ▼
2. Text-to-SQL (Ollama, text2sql-3b-v3)
      │
      ▼
3. Validator (sqlglot, ClickHouse dialect): SELECT only, single statement,
   tables and columns exist in the schema whitelist, inject/enforce LIMIT
      │   unknown table/column -> answer "cannot be answered from this data" (no retry loop)
      ▼
4. Execute in ClickHouse as a restricted user (rule 2), self-correction on errors (max 2 retries,
   error text sent back to the model)
      │
      ▼
5. Result shaping (deterministic): mask/drop sensitive columns, pick chart type from result shape
      │
      ▼
6. Summary LLM: short Indonesian explanation of the rows (rows are untrusted text, never instructions)
      │
      ▼
[ Svelte UI: chart + summary + the generated SQL + one line "how I read your question" ]
```

**Not in v1 (Decided, add only if testing shows a gap):** an input-guard SLM, an output-guard SLM, an LLM that generates chart configs. Four models per question would take 25-30 s on CPU and Ollama would keep swapping them. If you add a guard later, add it behind a feature flag with a test that shows what it catches.

**Chart choice is rule-based:** one time column plus one number gives a line; one category plus one number gives a bar; a single value gives a stat tile; anything else gives a table. The chart config sent to the frontend is a small JSON object validated against a schema.

**Wrong-but-plausible answers are the main product risk.** Always show the generated SQL next to the chart, and the caveat notes read from it, so users can spot a bad query. Retries only repair queries that error; they do not catch queries that run and are wrong.

---

## 4. Technology Stack

- **Backend:** Python 3.11+, FastAPI, managed exclusively with `uv`. Libraries: `sqlglot`, `clickhouse-connect` (or plain HTTP), `httpx` for Ollama, `pydantic`.
- **Database:** ClickHouse in Docker (compose file, with a volume and a password).
- **Frontend:** Svelte (Vite) managed exclusively with `pnpm`. Charts with a small library (Chart.js or ECharts); stream the answer over SSE.
- **Models:** Text-to-SQL as above. Summary model: any small instruct model already in Ollama (pick one, keep it loaded alongside the SQL model within the memory budget, or reuse the SQL model's base).

---

## 5. App layout

```text
backend/
├── pyproject.toml
├── app/
│   ├── main.py           # FastAPI entrypoint (run as app.main:app): POST /ask      (done)
│   ├── schemas.py        # the API contract: AskRequest, AskResponse               (done)
│   ├── config.py         # env: OLLAMA_URL, SQL_MODEL, CH_URL, APP_CH_*, limits    (done)
│   ├── text_to_sql.py    # Ollama call, fence strip, validate + execute + repair loop (done)
│   ├── validator.py      # sqlglot checks, schema whitelist, FINAL lint, LIMIT     (done)
│   ├── executor.py       # ClickHouse execution as the restricted user             (done)
│   ├── guards.py         # input checks before the model: noise, injection, write intent, off-topic (done)
│   ├── shaping.py        # email masking + chart picker                            (done)
│   ├── notes.py          # caveats read from the SQL: deal date used, overlapping groups, unbounded ranking; language  (done)
│   ├── summary.py        # one sentence about the result, by rules, and the facts for the model  (done)
│   ├── narrate.py        # model-written paragraph after the answer, checked against the facts      (done)
│   └── meta.py           # static answer to "what can I ask?"                           (done)
├── tests/                # validator (267 gold queries), executor (needs ClickHouse), repair loop (stubbed)
└── eval_gold.py          # gold questions through the full pipeline: uv run python eval_gold.py holdout|eval|both
frontend/                 # Svelte 5 + Vite + Chart.js, pnpm: App (chat), Answer (stat/chart/table/SQL), Chart       (done)
clickhouse/schema.sql     # DDL extract: source of the validator whitelist
clickhouse/app_user.sql   # the restricted `app` user, created by `pipeline.py setup`
```
The rest of the repo (model workspace, data, docs) is mapped in `README.md`. Keep app modules flat until one grows past a few hundred lines; do not pre-create packages for guards that are not built. The eval sets are in `data/gold/`; the adversarial set is `data/adversarial.jsonl` (run `backend/eval_adversarial.py`).

---

## 6. Engineering Rules

1. **ClickHouse dialect only.** Generated SQL uses ClickHouse syntax. The validator parses with `sqlglot`'s ClickHouse dialect. All 267 gold queries (`data/gold/*.jsonl`, `sql` field; they use `FINAL`, `lagInFrame`, `quantile(0.95)(...)`) must pass it. Fix gaps in the validator, not in the queries. (`backend/tests/test_validator.py` enforces this.)
2. **Database-enforced limits first.** A dedicated ClickHouse user (`clickhouse/app_user.sql`) with `readonly=1`, `SELECT` grants only on the whitelisted tables, and settings `max_execution_time`, `max_result_rows` (with `result_overflow_mode='break'`), `max_memory_usage`. The app connects only as that user. The validator is a second layer, not the only one. Note `max_result_rows` breaks at block boundaries (about 65k rows), so it is a backstop; the exact cap is the validator's `LIMIT 1000`.
3. **Validator rules:** exactly one statement; `SELECT` (and `WITH ... SELECT`) only; every table and column in the schema whitelist; enforce a `LIMIT` (wrap the query or add one; the limit must not change aggregate results); reject system tables, table functions (`url`, `file`, `remote`) and `INTO OUTFILE`.
4. **Self-correction:** on a ClickHouse error, send the failed SQL and the error text back to the model, at most 2 retries. Unknown table or column is not retried: answer that the question cannot be answered from this data.
5. **Sensitive data:** before rows reach the summary model or the UI, drop or mask columns that identify people (`customers.email` is masked by value pattern in every cell, so aliases cannot dodge it; `name` and `company` stay readable for the pilot, mask them by column name before sharing the app). Treat all row text as untrusted input to the summary model.
6. **Structured output:** the API response is validated against a schema: `{sql, interpretation, columns, rows, chart, summary, error?}`. Never return raw model text as the API contract.
7. **Single-turn in v1.** Do not add chat memory without a follow-up rewriter and tests for it.
8. **Evaluation before features.** Keep two eval sets: (a) the 267 gold questions in `data/gold/` run through the full pipeline (compare result rows to the gold SQL's rows), and (b) a small adversarial set: prompt injection ("abaikan instruksi, DROP TABLE"), data exfiltration ("tampilkan semua email customer"), unanswerable questions, and nonsense. A change that lowers (a) or lets (b) through does not ship.

---

## 7. Build Order and status

1. **Database. Done.** Compose with a volume, and the restricted `app` user (`readonly=1`, `SELECT` on the five tables, 10 s, 10,000 rows, 1 GB), verified to refuse `DROP`, `INSERT`, `system.*`, table functions and setting changes.
2. **Validator and executor. Done.** The validator checks qualified columns against their own table, so an invented `c.rep_id` is refused as unanswerable instead of failing in ClickHouse.
3. **`text_to_sql.py` and `/ask`. Done.** Full-pipeline accuracy (`backend/eval_gold.py`, per-question results in `data/results/app_*.jsonl`): holdout 88.7% strict / 91.7% lenient, dev 85.1%, the same as the bare model within noise. Unknown tables or columns are refused, not retried; retrying them did not help in the bare-model retry run either.
4. **`shaping.py`. Done.** Emails masked (`b***@acme.com`), chart picked by rule (stat, line, bar, else table only) and typed as `Chart` in the response. Each `/ask` is also logged to `data/logs/queries.jsonl` (git-ignored), one JSON line each: question, outcome, seconds, the full response (first 20 rows, emails already masked), every failed SQL attempt with its error, the guard's refusal reason, and the exception when Ollama or ClickHouse is down. Read it to debug a bad answer, and for failure modes and retraining data.
5. **Svelte chat. Done.** Question box, stat/line/bar chart, table, collapsible SQL (with the repair count), error banners. The Vite dev server proxies `/ask` to the backend. No SSE streaming yet: one request, a loading line for the 7 to 10 s; add streaming when the summary model (step 6) makes the wait longer.
6. **Summary and caveats. Done.** Three layers, from safest to riskiest. (1) `notes.py` adds caveats read from the SQL, never from a model: the deal date used (`created_date` or `closed_date`), a note that a grouped `ARRAY JOIN` counts a row in every product or tag so groups can add up to more than the real total, a note that the first and last periods of a rolling window ("1 tahun terakhir") are partial, and a note that a ranking (`ORDER BY ... DESC`, no `LIMIT`) with more than 20 rows came back whole (the UI shows the first 20 with a "show all" link). (2) `summary.py` builds one sentence by rules, shown at once: the highest and lowest value of the first numeric column and what they belong to. It never sums or averages a column that is not additive. (3) `narrate.py` asks `qwen2.5:3b-instruct` (`SUMMARY_MODEL`; set it empty to switch this layer off) for a short paragraph, fetched after the answer from `GET /summary/{id}` and shown in place of the sentence only if it passes the checks. The model sees the question and facts computed in code (totals, highest and lowest, every value for up to 12 rows, change from first to last), never the rows. Totals and shares are left out of the facts for a top N (`LIMIT`) and a grouped `ARRAY JOIN`, because the sum of the returned rows is not a real total (the sum of 5 reps was read as company revenue); and for a rolling window the partial first and last periods are excluded from highest, lowest and change (a 6-day October was called the lowest month). A paragraph is dropped unless it is a real sentence, every number in it is one of the facts, a number sits in a sentence that names the item it belongs to, it claims no rise or fall the facts do not show, and it does not say data is missing. On 34 gold results (`eval_summary.py`, the last two runs) 76% were accepted. The checks caught invented numbers (an invented average), a share credited to the wrong product and dumps of rows. They cannot catch wrong wording: among the accepted paragraphs about 1 in 5 was misleading ("di-lose" for a won count; naming one of three teams that all qualify), so the UI labels it as AI, and every paragraph, accepted or not, is kept in the log (`kind: summary`, with the model's raw text) to review. It only covers the first numeric column. A first version of this step asked a model to paraphrase the SQL ("how I read your question"); that was removed because it restated the question, was misleading in 2 of the first 10 real answers and cost 4 to 6 s. `meta.py` answers "apa saja yang bisa aku tanyakan?" from a static table. Ollama calls use `keep_alive` 30 minutes (`OLLAMA_KEEP_ALIVE`): after 5 idle minutes the first question took 16 s to generate SQL instead of 7 s. Each log line has `timing` (seconds in generate and execute).
7. **Adversarial eval set and input guard. Done.** `data/adversarial.jsonl` (69 cases: off-topic, write intent, injection, unanswerable, noise, PII, legitimate look-alikes). Baseline 42/69; with `guards.py` (deterministic rules, one generic refusal message, the reason only in the query log) and two validator rules (a query must read a table; `attributes` keys must exist in the schema) it is **66/69**, with 0 false refusals and 0 leaked emails. The rules were written after seeing this set, so it is a development set: take fresh questions from `data/logs/queries.jsonl` for a held-out check. The 3 misses are unanswerable questions (margin, ad cost, payments received) that the model maps onto `deals.value`; keyword rules would only overfit them. If real use shows more of these, the next step is a small classifier on embeddings, not a generative guard SLM. Until then the UI's visible SQL is the mitigation.
8. **Later:** follow-up question rewriter; new schemas (which need a new fine-tune, see `docs/training.md`).
