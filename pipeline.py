"""Text-to-SQL dataset pipeline. Stdlib only.

  python pipeline.py setup          create crm database, tables (DDL from docs/text2sql-spec.md), seed data
  python pipeline.py gen 40         call Gemini 40 times, append raw pairs to data/raw/raw.jsonl
  (build reads every data/raw/raw*.jsonl, so hand-written files like raw_join2.jsonl work too)
  python pipeline.py build          dedupe + lint + execute in ClickHouse -> data/train.jsonl, eval.jsonl, rejected.jsonl
  python pipeline.py check data/raw/raw_x.jsonl   validate one raw file (ERR / NOFINAL / DUP / EMPTY per line)
  python pipeline.py eval text2sql  execution accuracy of an Ollama model on data/eval.jsonl
                                    (optional 3rd arg: only the first N questions;
                                    --rescore re-checks saved predictions without calling the model;
                                    --retry=2 lets the model fix failing SQL using the error message;
                                    --set=holdout scores data/holdout.jsonl instead, the independent test set)
  python pipeline.py zip [model]    bundle spec, seed, train, eval into models/<model>/notebooks/colab_upload.zip for Colab
                                    (model defaults to text2sql-3b-v3)
  python pipeline.py holdout        build data/holdout.jsonl from data/holdout/raw_holdout_*.jsonl
  python pipeline.py ask "berapa omset bulan ini?"   question -> SQL -> result rows (model: TEXT2SQL_MODEL)
  python pipeline.py test           self-checks (needs ClickHouse running)

Env: GEMINI_API_KEY (gen), GEMINI_MODEL (default gemini-2.5-flash), CH_URL, CH_USER, CH_PASSWORD, OLLAMA_URL,
     TEXT2SQL_MODEL (default text2sql-3b-v3, used by ask).
"""
import hashlib, json, os, random, re, sys, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SPEC = (ROOT / "docs" / "text2sql-spec.md").read_text(encoding="utf-8")


def spec_block(pattern):
    m = re.search(pattern, SPEC, re.S)
    if m is None:
        raise SystemExit(f"docs/text2sql-spec.md no longer matches {pattern!r} (see its section 8)")
    return m.group(1)


DDL = spec_block(r"```sql\n(.*?)```")
SYSTEM_PROMPT = spec_block(r"### 7\..*?```\n(.*?)```").strip()
GEN_PROMPT = SPEC.split("### 7.")[0]
CATEGORIES = re.findall(r"^\| `(\w+)` \|", SPEC, re.M)
DIFFICULTIES = ["easy", "medium", "hard"]
BATCH = 25

CH_URL = os.getenv("CH_URL", "http://localhost:8123/")
CH_AUTH = {"X-ClickHouse-User": os.getenv("CH_USER", "default"), "X-ClickHouse-Key": os.getenv("CH_PASSWORD", "crm")}


def ch(sql, database="crm", **settings):
    """Run one statement over the ClickHouse HTTP API. Raises RuntimeError with the server message."""
    params = "&".join(f"{k}={v}" for k, v in {"database": database, **settings}.items())
    req = urllib.request.Request(f"{CH_URL}?{params}", data=sql.encode(), headers=CH_AUTH)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode().strip()) from None


def statements(text):
    text = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in text.split(";") if s.strip()]


def setup():
    ch("DROP DATABASE IF EXISTS crm", database="default")
    ch("CREATE DATABASE crm", database="default")
    for s in statements(DDL) + statements((ROOT / "clickhouse" / "seed.sql").read_text(encoding="utf-8")):
        ch(s)
    app_user = (ROOT / "clickhouse" / "app_user.sql").read_text(encoding="utf-8").replace("{password}", os.getenv("APP_CH_PASSWORD", "app"))
    for s in statements(app_user):
        ch(s, database="default")
    for t in ["customers", "sales_reps", "deals", "activities", "support_tickets"]:
        print(t, ch(f"SELECT count() FROM {t}").strip())
    print("app user ready")


def gemini(prompt):
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(json.load(r)["candidates"][0]["content"]["parts"][0]["text"])


def gen(batches):
    (DATA / "raw").mkdir(parents=True, exist_ok=True)
    for i in range(batches):
        cat, diff = random.choice(CATEGORIES), random.choice(DIFFICULTIES)
        prompt = (GEN_PROMPT.replace("[e.g., 25]", str(BATCH))
                  .replace("[one code from section 4]", cat)
                  .replace("[easy | medium | hard]", diff))
        try:
            items = gemini(prompt)
        except Exception as e:  # one bad batch shouldn't kill a long run
            print(f"batch {i}: {cat}/{diff} failed: {e}")
            continue
        with open(DATA / "raw" / "raw.jsonl", "a", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps({**it, "category": cat, "difficulty": diff}, ensure_ascii=False) + "\n")
        print(f"batch {i}: {cat}/{diff} +{len(items)}")


RMT = r"(?:customers|deals|support_tickets)"


def final_ok(sql):
    """Every FROM/JOIN of a ReplacingMergeTree table must carry FINAL (spec rule 2.1)."""
    refs = re.findall(rf"\b(?:FROM|JOIN)\s+{RMT}\b", sql, re.I)
    finals = re.findall(rf"\b(?:FROM|JOIN)\s+{RMT}\b(?:\s+(?:AS\s+)?\w+)?\s+FINAL\b", sql, re.I)
    return len(refs) == len(finals)


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def validate(sql):
    """(reason, None) if the SQL fails the FINAL lint or doesn't execute, else (None, row count)."""
    if not final_ok(sql):
        return "missing FINAL", None
    try:
        out = ch(sql, readonly=1, max_execution_time=10, max_result_rows=1000,
                 result_overflow_mode="break", default_format="JSONCompact")
    except RuntimeError as e:
        m = re.search(r"Code: \d+\. DB::Exception: [^\n\"]*", str(e))
        return (m.group(0) if m else str(e))[:300], None
    return None, json.loads(out)["rows"]


def load_raw():
    """Raw pairs tagged with a stable key (file:line), so rewriting a pair in place keeps its split."""
    return [{**json.loads(l), "key": f"{p.name}:{i}"}
            for p in sorted((DATA / "raw").glob("raw*.jsonl"))
            for i, l in enumerate(open(p, encoding="utf-8")) if l.strip()]


EVAL_KEYS = DATA / "eval_keys.txt"  # frozen held-out set, so models trained before and after a rewrite stay comparable


def is_eval(key):
    if EVAL_KEYS.exists():
        return key in EVAL_KEYS.read_text().split()
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % 10 == 0


def build():
    raw = load_raw()
    seen_q, seen_sql, keep, rejected = set(), set(), [], []
    # Eval rows first: a duplicate then drops the train copy, never a held-out question.
    for it in sorted(raw, key=lambda it: not is_eval(it["key"])):
        q, sql = it.get("question", "").strip(), it.get("sql", "").strip().rstrip(";")
        if not q or not sql:
            reason = "empty"
        elif norm(q) in seen_q or norm(sql) in seen_sql:
            reason = "duplicate"
        else:
            reason, it["rows"] = validate(sql)
        if reason:
            rejected.append({**it, "reason": reason})
            continue
        seen_q.add(norm(q)); seen_sql.add(norm(sql))
        keep.append({**it, "sql": sql})

    splits = {"eval": [it for it in keep if is_eval(it["key"])], "train": [it for it in keep if not is_eval(it["key"])]}
    # Near-paraphrases of a held-out question would inflate the score: drop them from train.
    words = lambda s: set(re.findall(r"\w+", s.lower()))
    ev_words = [words(it["question"]) for it in splits["eval"]]
    near = lambda w: any(len(w & e) / len(w | e) >= 0.6 for e in ev_words)
    rejected += [{**it, "reason": "near-eval"} for it in splits["train"] if near(words(it["question"]))]
    splits["train"] = [it for it in splits["train"] if not near(words(it["question"]))]
    for name, rows in splits.items():
        with open(DATA / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for it in rows:
                f.write(json.dumps({"messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": it["question"]},
                    {"role": "assistant", "content": it["sql"]}],
                    "category": it["category"], "difficulty": it["difficulty"], "key": it["key"]}, ensure_ascii=False) + "\n")
    with open(DATA / "rejected.jsonl", "w", encoding="utf-8") as f:
        for it in rejected:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    empty = sum(1 for it in keep if it["rows"] == 0)
    print(f"raw {len(raw)} -> train {len(splits['train'])}, eval {len(splits['eval'])}, "
          f"rejected {len(rejected)}, empty-result kept {empty}")


def build_holdout():
    """Independent test pairs (data/holdout/raw_holdout_*.jsonl, never used for training) -> data/holdout.jsonl,
    same format as eval.jsonl. Drops empty / duplicate / failing rows; reports overlap with train for information."""
    rows = lambda p: [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    seen_q, seen_sql = set(), set()
    train = rows(DATA / "train.jsonl")
    for r in train + rows(DATA / "eval.jsonl"):
        seen_q.add(norm(r["messages"][1]["content"])); seen_sql.add(norm(r["messages"][2]["content"]))
    words = lambda t: set(re.findall(r"\w+", t.lower()))
    train_w = [words(r["messages"][1]["content"]) for r in train]
    keep, dropped, close = [], [], 0
    for path in sorted((DATA / "holdout").glob("raw_holdout_*.jsonl")):
        for i, it in enumerate(rows(path)):
            q, sql = it.get("question", "").strip(), it.get("sql", "").strip().rstrip(";")
            reason = "empty" if not q or not sql else "duplicate" if norm(q) in seen_q or norm(sql) in seen_sql else validate(sql)[0]
            if reason:
                dropped.append((f"{path.name}:{i}", reason)); continue
            seen_q.add(norm(q)); seen_sql.add(norm(sql))
            w = words(q)
            close += any(len(w & t) / len(w | t) >= 0.6 for t in train_w)
            keep.append({"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": q},
                                      {"role": "assistant", "content": sql}],
                         "category": it["category"], "difficulty": it["difficulty"], "key": f"{path.name}:{i}"})
    with open(DATA / "holdout.jsonl", "w", encoding="utf-8") as f:
        for it in keep:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"holdout: {len(keep)} kept, {len(dropped)} dropped {dropped[:5]}, {close} with a train question >=0.6 word overlap")


def check(path):
    """Validate one raw file: prints ERR / NOFINAL / DUP / EMPTY lines and a summary. For hand-written data."""
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    bad, seen = 0, set()
    for i, r in enumerate(rows):
        reason, n = validate(r["sql"])
        if norm(r["sql"]) in seen or norm(r["question"]) in seen:
            reason = "DUP"
        seen |= {norm(r["sql"]), norm(r["question"])}
        if reason:
            bad += 1
            print(f"line {i}: {reason[:200]} | {r['question'][:60]}")
        elif n == 0:
            print(f"line {i}: EMPTY | {r['question'][:60]}")
    print(len(rows), "rows, bad", bad)


def rows_of(sql):
    """Result rows as lists of canonical value strings (floats rounded); None if the query fails."""
    try:
        out = ch(sql, readonly=1, max_execution_time=10, max_result_rows=10000,
                 result_overflow_mode="break", default_format="JSONCompact")
    except RuntimeError:
        return None
    canon = lambda v: json.dumps(round(v, 4) if isinstance(v, float) else v)
    return [[canon(v) for v in row] for row in json.loads(out)["data"]]


def _covers(big, small):
    """True if some distinct columns of `big` reproduce `small` row for row (as a multiset).
    Columns are matched by values, not names, so aliases don't matter."""
    import itertools
    if len(big) != len(small) or not small or not small[0]:
        return False
    big_cols, small_cols = list(zip(*big)), list(zip(*small))
    cands = [[i for i, bc in enumerate(big_cols) if sorted(bc) == sorted(sc)] for sc in small_cols]
    target = sorted(map(tuple, small))
    for combo in itertools.islice(itertools.product(*cands), 2000):  # ponytail: capped search, plenty for <20 columns
        if len(set(combo)) == len(combo) and sorted(tuple(r[i] for i in combo) for r in big) == target:
            return True
    return False


def compare(gold, pred):
    """ok: same rows, columns in any order. ok_extra_cols: pred has every gold column plus extras.
    partial_cols: pred has a subset of gold's columns, matching row for row. Row order is ignored."""
    if pred is None:
        return "error"
    if sorted(map(tuple, pred)) == sorted(map(tuple, gold)):
        return "ok"
    if _covers(pred, gold):
        return "ok" if len(pred[0]) == len(gold[0]) else "ok_extra_cols"
    if _covers(gold, pred):
        return "partial_cols"
    return "wrong"


def clean_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip().rstrip(";")


def ollama(model, messages):
    body = {"model": model, "messages": messages, "stream": False, "options": {"temperature": 0}}
    req = urllib.request.Request(os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/chat",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["message"]["content"]


def generate_sql(model, messages, retries=0):
    """Ask the model for SQL; if it fails the FINAL lint or ClickHouse rejects it, send the error
    back and let the model fix it, up to `retries` times. Returns (sql, attempts used)."""
    sql, attempts = clean_sql(ollama(model, messages)), 0
    while attempts < retries:
        reason, _ = validate(sql)
        if not reason:
            break
        attempts += 1
        messages = messages + [{"role": "assistant", "content": sql},
                               {"role": "user", "content": f"SQL itu gagal: {reason}\nPerbaiki SQL-nya. Output only SQL."}]
        sql = clean_sql(ollama(model, messages))
    return sql, attempts


def evaluate(model, limit=None, rescore=False, retries=0, which="eval"):
    """Execution accuracy of an Ollama model on data/eval.jsonl against the local ClickHouse.
    rescore=True re-checks the predictions saved by the last run instead of calling the model.
    retries>0 lets the model fix SQL that fails, using the error message (see generate_sql)."""
    import time
    from collections import Counter, defaultdict
    out_path = DATA / "results" / f"eval_results_{re.sub(r'[^\w.-]', '_', model)}{f'_retry{retries}' if retries else ''}{'_holdout' if which == 'holdout' else ''}.jsonl"
    rows = [json.loads(l) for l in open(DATA / f"{which}.jsonl", encoding="utf-8") if l.strip()][:limit]
    saved = {json.loads(l)["question"]: json.loads(l)["pred"] for l in open(out_path, encoding="utf-8")} if rescore else {}
    out_path.parent.mkdir(exist_ok=True)
    by_cat, results, secs, fixes = defaultdict(Counter), [], [], 0
    for i, r in enumerate(rows, 1):
        q, gold = r["messages"][1]["content"], r["messages"][2]["content"]
        if rescore:
            if q not in saved: continue
            pred = saved[q]
        else:
            t0 = time.time()
            pred, attempts = generate_sql(model, r["messages"][:2], retries)
            secs.append(time.time() - t0)
            fixes += attempts > 0
        g = rows_of(gold)
        if g is None:
            print("GOLD FAILS:", gold[:120])
            continue
        verdict = compare(g, rows_of(pred))
        by_cat[r["category"]][verdict] += 1
        results.append({"category": r["category"], "difficulty": r["difficulty"], "verdict": verdict,
                        "question": q, "pred": pred, "gold": gold})
        print(f"[{i}/{len(rows)}] {verdict:13s} {q[:70]}")
    with open(out_path, "w", encoding="utf-8") as f:
        for it in results:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    tot = sum(by_cat.values(), Counter())
    n = sum(tot.values())
    strict, lenient = tot["ok"], tot["ok"] + tot["ok_extra_cols"]
    print(f"\n{model}: strict {strict}/{n} = {strict / max(n, 1):.1%}, "
          f"lenient (extra columns ok) {lenient}/{n} = {lenient / max(n, 1):.1%}")
    print("  " + ", ".join(f"{k} {tot[k]}" for k in ["ok", "ok_extra_cols", "partial_cols", "wrong", "error"]) +
          (f", avg {sum(secs) / len(secs):.1f}s/query" if secs else "") +
          (f", {fixes} queries needed a retry" if retries and not rescore else ""))
    print(f"  {'category':10s} strict lenient partial  of")
    for cat, c in sorted(by_cat.items()):
        print(f"  {cat:10s} {c['ok']:6d} {c['ok'] + c['ok_extra_cols']:7d} {c['partial_cols']:7d} {sum(c.values()):3d}")


def test():
    R = rows_of
    assert compare(R("SELECT 1 AS a UNION ALL SELECT 2"), R("SELECT 2 AS b UNION ALL SELECT 1")) == "ok"
    assert R("SELECT nope") is None and compare([["1"]], None) == "error"
    gold = R("SELECT number AS id, number * 10 AS v FROM numbers(5)")
    assert compare(gold, R("SELECT number * 10, 'x', number FROM numbers(5)")) == "ok_extra_cols"  # reordered + extra
    assert compare(gold, R("SELECT number * 10, number FROM numbers(5)")) == "ok"  # same columns, other order
    assert compare(gold, R("SELECT number FROM numbers(5)")) == "partial_cols"
    assert compare(gold, R("SELECT number, number * 11 FROM numbers(5)")) == "wrong"
    assert compare(gold, R("SELECT number, number * 10 FROM numbers(4)")) == "wrong"  # missing a row
    # same per-column value sets but misaligned rows must not match
    assert compare(R("SELECT number AS a, 4 - number AS b FROM numbers(5)"),
                   R("SELECT number AS a, number AS b FROM numbers(5)")) == "wrong"
    assert clean_sql("```sql\nSELECT 1;\n```") == "SELECT 1" and clean_sql(" SELECT 2 ") == "SELECT 2"
    assert final_ok("SELECT 1 FROM deals AS d FINAL JOIN customers c FINAL ON 1")
    assert final_ok("SELECT 1 FROM sales_reps r JOIN activities a ON 1")
    assert not final_ok("SELECT 1 FROM deals AS d JOIN customers AS c FINAL ON 1")
    assert not final_ok("SELECT 1 FROM support_tickets")
    assert len(CATEGORIES) == 9 and "CREATE TABLE deals" in DDL and SYSTEM_PROMPT.startswith("You translate")
    print("ok")


def zip_upload(model="text2sql-3b-v3"):
    """Bundle what the Colab notebook needs (spec, seed, train, eval) into models/<model>/notebooks/colab_upload.zip."""
    import zipfile
    out = ROOT / "models" / model / "notebooks" / "colab_upload.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in [ROOT / "docs" / "text2sql-spec.md", ROOT / "clickhouse" / "seed.sql", DATA / "train.jsonl", DATA / "eval.jsonl"]:
            z.write(p, p.name)
    print(f"wrote {out.relative_to(ROOT).as_posix()}")


def ask(question, model):
    """Indonesian question -> SQL (the model may fix its own errors twice), then run it and show the first rows."""
    sql, _ = generate_sql(model, [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}], retries=2)
    rows = rows_of(sql)
    print(sql, "\n")
    print("query failed" if rows is None else f"{len(rows)} rows" + "".join("\n  " + " | ".join(r) for r in rows[:10]))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "setup": setup()
    elif cmd == "gen": gen(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    elif cmd == "build": build()
    elif cmd == "check": check(sys.argv[2])
    elif cmd == "holdout": build_holdout()
    elif cmd == "eval":
        args = [a for a in sys.argv[2:] if not a.startswith("--")]
        retries = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--retry=")), 0))
        evaluate(args[0] if args else "text2sql", int(args[1]) if len(args) > 1 else None, "--rescore" in sys.argv, retries,
                 "holdout" if "--set=holdout" in sys.argv else "eval")
    elif cmd == "zip": zip_upload(*sys.argv[2:3])
    elif cmd == "ask": ask(" ".join(sys.argv[2:]), os.getenv("TEXT2SQL_MODEL", "text2sql-3b-v3"))
    elif cmd == "test": test()
    else: print(__doc__)
