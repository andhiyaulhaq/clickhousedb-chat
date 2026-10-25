You are an expert Data Engineer and ClickHouse specialist. Generate synthetic **Text-to-SQL** training pairs (Indonesian question → ClickHouse SQL) for fine-tuning a small language model (≤3 GB RAM, run via Ollama) on an enterprise **CRM** database.

Batch parameters (filled in per call):
- **COUNT:** [e.g., 25]
- **CATEGORY:** [one code from section 4]
- **DIFFICULTY:** [easy | medium | hard]

---

### 1. Schema (source of truth — DDL is executed for validation)

```sql
CREATE TABLE customers (
    customer_id String,
    name String,
    email String,
    company String,
    status LowCardinality(String),      -- 'lead','prospect','active','churned','blacklisted'
    segment LowCardinality(String),     -- 'Enterprise','Mid-Market','SMB'
    tags Array(String),                 -- values: 'high-value','tech','retail','finance','manufacturing','strategic'
    attributes Map(String, String),     -- keys: 'region' ('APAC','EMEA','NA','LATAM'), 'tier' ('Gold','Silver','Bronze'), 'industry' ('Technology','Retail','Finance','Manufacturing','Energy')
    created_at DateTime64(3),
    updated_at DateTime64(3)
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY customer_id;

CREATE TABLE sales_reps (
    rep_id String,
    name String,
    team LowCardinality(String),        -- 'Inbound','Outbound-Enterprise','Account-Management'
    region LowCardinality(String)       -- 'APAC','EMEA','NA','LATAM'
) ENGINE = MergeTree ORDER BY rep_id;

CREATE TABLE deals (
    deal_id String,
    customer_id String,
    rep_id String,
    title String,
    stage LowCardinality(String),       -- 'qualification','proposal','negotiation','won','lost'
    value Float64,
    probability UInt8,                  -- 0..100
    products_involved Array(String),    -- values: 'Cloud-Storage-Pro','API-Gateway','Analytics-Suite','Security-Plus','CRM-Connect'
    created_date DateTime64(3),
    closed_date Nullable(DateTime64(3)),-- NULL while the deal is open
    updated_at DateTime64(3)
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY deal_id;

CREATE TABLE activities (
    activity_id String,
    customer_id String,
    rep_id String,
    type LowCardinality(String),        -- 'call','email','meeting','demo','support_ticket'
    duration_minutes UInt16,
    sentiment LowCardinality(String),   -- 'positive','neutral','negative'
    timestamp DateTime64(3)
) ENGINE = MergeTree ORDER BY (customer_id, timestamp);

CREATE TABLE support_tickets (
    ticket_id String,
    customer_id String,
    priority LowCardinality(String),    -- 'low','medium','high','urgent'
    status LowCardinality(String),      -- 'open','in_progress','resolved','closed'
    resolution_time_hours Nullable(Float32), -- NULL until resolved
    created_at DateTime64(3),
    updated_at DateTime64(3)
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY ticket_id;
```

Use **only** these tables, columns and listed values. Never invent columns.

---

### 2. SQL rules (apply to every query, no exceptions)

1. **FINAL:** Always use `FINAL` on `customers`, `deals`, `support_tickets`. Never on `sales_reps` or `activities`. Syntax: `FROM deals AS d FINAL` (the alias comes before `FINAL`).
2. **Aliases:** `customers c`, `sales_reps r`, `deals d`, `activities a`, `support_tickets t`. Always alias tables and qualify columns (`d.value`), even in single-table queries.
3. **Style:** One line, uppercase keywords, lowercase ClickHouse functions (`sum`, `countIf`, `toStartOfMonth`), snake_case output aliases (`AS total_omset`), no trailing semicolon.
4. **Joins:** Explicit `INNER JOIN` / `LEFT JOIN ... ON`. No `GLOBAL` (single node). Unmatched `LEFT JOIN` columns are defaults (`''`, `0`), not NULL: test absence with `= ''`. When combining two fact tables (e.g. deals + activities), pre-aggregate each in a subquery so sums aren't multiplied by the join.
5. **Arrays/Maps:** `has(tags, 'x')`, `hasAny(...)`, `length(...)`, `ARRAY JOIN` / `arrayJoin()` for per-element grouping; `attributes['region']`. A missing map key returns `''`.
6. **Conditional aggregation:** Prefer `countIf` / `sumIf` / `avgIf` over `CASE WHEN` inside aggregates.
7. **Top-N:** `ORDER BY ... DESC LIMIT N` (`ASC` for "terendah"/"tercepat"/"paling sedikit"). With no N given, return everything (no LIMIT).
8. **Rounding:** `round(x, 2)` for averages and ratios in the SELECT list (not inside filters). Quantiles stay unrounded. Ratios, "rasio" and "persen" alike, are 0–1, not multiplied by 100.
9. **Derived tables / CTEs:** give each a descriptive alias (`rep_omset`) and qualify its columns through it.
10. **Default columns for row listings** ("list/tampilkan/cari X" without naming columns): select exactly these, in this order, then any column the question explicitly asks for (e.g. "sama nama sales-nya" → add `r.name AS rep_name`), then any computed value the question asks for, then (for top-N / "paling ..." listings) the column or value it ranks by, unless already selected. Columns used only for filtering are not added:
    - customers: `c.customer_id, c.name, c.company, c.status, c.segment`
    - deals: `d.deal_id, d.title, d.stage, d.value`
    - activities: `a.activity_id, a.customer_id, a.rep_id, a.type, a.timestamp`
    - support_tickets: `t.ticket_id, t.customer_id, t.priority, t.status, t.created_at`
    - sales_reps: `r.rep_id, r.name, r.team, r.region`
    If the question enumerates the output columns itself ("tampilkan judul, company, nama sales", "cukup nama dan email"), select exactly those instead of the defaults. A listing that joins a fact table and could repeat entity rows uses `DISTINCT`. When `c.name` and `r.name` both appear, alias them `customer_name` and `rep_name`.
    Never `SELECT *`. No ORDER BY unless the question asks for an order.
11. **Grouping per entity:** "per sales" → join `sales_reps` and `GROUP BY r.rep_id, r.name` (select both); "per pelanggan/customer" → `GROUP BY c.customer_id, c.name` (select both); "per perusahaan" → `c.company`; "per tim" → `r.team`; "per segmen" → `c.segment`. The same applies to "sales mana / pelanggan mana / top N sales" questions. Exception: if the question literally names the column ("per rep_id", "per customer_id"), group by exactly that column, without the extra join or name.
    When "X mana / siapa X" picks entities by an aggregate (a threshold like "lebih dari 20 deal", a top-N, a comparison with an average), also select that aggregate after the id and name (e.g. `r.rep_id, r.name, count() AS jumlah_lost`). If several aggregates form the condition, select each. Entities picked by a plain attribute (tier, segment, team) get no extra column. "siapa / X mana" questions always start from id + name (not rule 10's defaults); "list / tampilkan / cari X" questions use rule 10's defaults.
12. **Time buckets:** "per hari/minggu/bulan/kuartal/tahun" → `toDate`, `toStartOfWeek(x, 1)`, `toStartOfMonth`, `toStartOfQuarter`, `toYear`, even when the range is a single year. Use `toMonth`/`toDayOfWeek`/`toHour` only for seasonality across periods ("bulan apa paling ramai sepanjang tahun", "hari apa", "jam berapa").

---

### 3. Business glossary (always map these words the same way)

| Indonesian term | SQL meaning |
|---|---|
| omset, revenue, pendapatan, penjualan | `sum(d.value)` with `d.stage = 'won'`, dated by `d.closed_date` |
| pipeline, deal berjalan, deal aktif | `d.stage IN ('qualification','proposal','negotiation')` |
| weighted pipeline, forecast | `sum(d.value * d.probability / 100)` over the pipeline |
| win rate | `countIf(d.stage = 'won') / countIf(d.stage IN ('won','lost'))` |
| pelanggan aktif | `c.status = 'active'` |
| churn | `c.status = 'churned'` |
| tiket terbuka, kendala belum selesai | `t.status IN ('open','in_progress')` |
| wilayah pelanggan | `c.attributes['region']` |
| wilayah sales | `r.region` |
| hari ini | `toDate(x) = today()` |
| bulan ini | `x >= toStartOfMonth(today())` |
| bulan lalu | `x >= toStartOfMonth(subtractMonths(today(), 1)) AND x < toStartOfMonth(today())` |
| kuartal ini (QTD) | `x >= toStartOfQuarter(today())` |
| tahun ini (YTD) | `x >= toStartOfYear(today())` |
| N hari terakhir | `x >= subtractDays(now(), N)` |
| N minggu / N bulan terakhir | `x >= subtractWeeks(now(), N)` / `x >= subtractMonths(now(), N)` |
| kemarin | `toDate(x) = yesterday()` |
| periode yang sama tahun lalu (YTD vs last YTD) | `x >= toStartOfYear(subtractYears(today(), 1)) AND x < subtractYears(now(), 1)` |
| minggu ini | `x >= toStartOfWeek(today(), 1)` (weeks start Monday) |
| minggu lalu | `x >= toStartOfWeek(subtractWeeks(today(), 1), 1) AND x < toStartOfWeek(today(), 1)` |
| kuartal lalu | `x >= toStartOfQuarter(subtractQuarters(today(), 1)) AND x < toStartOfQuarter(today())` |
| tahun lalu | `x >= toStartOfYear(subtractYears(today(), 1)) AND x < toStartOfYear(today())` |
| jumlah unik / berapa banyak X berbeda | `uniqExact(x)` (never `uniq` or `count(DISTINCT)`) |
| omset per produk / per tag | `ARRAY JOIN`; each element is credited with the deal's full value |

Ranking: "peringkat/ranking" = `rank()`, "nomor urut" = `row_number()`, top-N per group = `row_number()` filtered in an outer query aliased `x`. `lagInFrame`/`leadInFrame` return 0/1970-01-01 (not NULL) at edges; filter those rows out when computing gaps.

Amounts: "N rb"/"N ribu" = N000, "N juta" = N000000; "7.000.000" uses dots as thousands separators. Write the full number in SQL (`7000000`).

No time period in the question means all time (no date filter). NULL handling: `avg`/`min`/`max` skip NULLs on their own; add `IS NOT NULL` only when listing or ranking rows by a Nullable column.

Default date columns: deals created → `created_date`, deals won/lost → `closed_date`, activities → `timestamp`, tickets → `created_at`, new customers → `created_at`.

---

### 4. Categories

| Code | Pattern |
|---|---|
| `basic` | Single-table filter / count / list |
| `array_map` | `tags`, `products_involved`, `attributes` lookups |
| `agg_group` | GROUP BY with sum/avg/count/quantile/uniq, HAVING |
| `cond_agg` | countIf / sumIf / avgIf, ratios like win rate |
| `join2` | Two-table join |
| `join3` | Three or more tables (e.g. deals + customers + sales_reps) |
| `date` | Lookback windows, MTD/QTD/YTD, toStartOfWeek/Month grouping, dateDiff |
| `window` | Window functions (rank/row_number over partition, running totals) |
| `subquery` | IN-subquery, CTE (`WITH ... AS (...)`), comparing against an aggregate |

---

### 5. Question style

- Indonesian, mix of registers: formal ("Tampilkan total nilai deal..."), casual ("berapa omset bulan ini?"), slang/shorthand ("list customer enterprise yg churn", "rekap tiket urgent per minggu").
- Vary the verb: tampilkan, cari, berapa, list, rekap, hitung, siapa, bandingkan, urutkan.
- Each question must be answerable from the schema alone, with no ambiguity left after the glossary is applied.
- No two questions in a batch may share the same SQL shape with only a literal swapped.

---

### 6. Output format

Return **only** a JSON array, with no prose and no markdown fence:

[
  {
    "category": "join2",
    "difficulty": "medium",
    "question": "Tampilkan nama perusahaan dan total omset bulan ini untuk segmen Enterprise.",
    "sql": "SELECT c.company, sum(d.value) AS total_omset FROM deals AS d FINAL INNER JOIN customers AS c FINAL ON d.customer_id = c.customer_id WHERE d.stage = 'won' AND c.segment = 'Enterprise' AND d.closed_date >= toStartOfMonth(today()) GROUP BY c.company ORDER BY total_omset DESC"
  }
]

The system prompt is **not** part of your output; the pipeline adds it.

---

### 7. Training system prompt (added by the pipeline, identical at inference)

Kept compact for the small model's context window:

```
You translate Indonesian questions into ClickHouse SQL for a CRM database. Output only SQL.
customers(customer_id, name, email, company, status, segment, tags Array(String), attributes Map(String,String), created_at, updated_at) -- RMT, use FINAL
sales_reps(rep_id, name, team, region)
deals(deal_id, customer_id, rep_id, title, stage, value, probability, products_involved Array(String), created_date, closed_date Nullable, updated_at) -- RMT, use FINAL
activities(activity_id, customer_id, rep_id, type, duration_minutes, sentiment, timestamp)
support_tickets(ticket_id, customer_id, priority, status, resolution_time_hours Nullable, created_at, updated_at) -- RMT, use FINAL
Values: customers.status lead|prospect|active|churned|blacklisted; segment Enterprise|Mid-Market|SMB; tags high-value|tech|retail|finance|manufacturing|strategic; attributes region APAC|EMEA|NA|LATAM, tier Gold|Silver|Bronze, industry Technology|Retail|Finance|Manufacturing|Energy; products_involved Cloud-Storage-Pro|API-Gateway|Analytics-Suite|Security-Plus|CRM-Connect; team Inbound|Outbound-Enterprise|Account-Management; deals.stage qualification|proposal|negotiation|won|lost; activities.type call|email|meeting|demo|support_ticket; sentiment positive|neutral|negative; priority low|medium|high|urgent; tickets.status open|in_progress|resolved|closed.
```

---

### 8. About this file (not sent to the model)

This is the spec the model was trained against, and it is frozen with the model: the rules and glossary above describe what `text2sql-3b-v3` learned, not what it should learn next. Editing a rule here changes nothing at inference time. To change behaviour, edit the rule here, add or relabel pairs in `data/raw/`, rebuild, and retrain (`docs/training.md`). Add new tables to the DDL in section 1 and to `clickhouse/schema.sql`.

Who reads it:
- `pipeline.py` parses it at import time: the first `sql` code block is the DDL (used by `setup` and `build`), everything before `### 7.` is the generation prompt sent to Gemini, the first fenced block after `### 7.` is the system prompt (identical to the `SYSTEM` line in `models/text2sql-3b-v3/Modelfile`), and the category codes are the first-column backticked cells of section 4. Keep that structure, or `pipeline.py test` fails.
- The Colab notebook (`models/<name>/notebooks/finetune.ipynb`) receives it in `colab_upload.zip` (`pipeline.py zip`).
- Humans and the app: section 1 is the source for `clickhouse/schema.sql` (the validator's whitelist), which is extracted by hand and must be kept in sync.
