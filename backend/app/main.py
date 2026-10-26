import json
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException

from app import config, narrate, text_to_sql
from app.schemas import AskRequest, AskResponse

app = FastAPI(title="ClickHouse chat")


def _append(entry: dict) -> None:
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log(question: str, r: AskResponse | None, secs: float, exc: Exception | None = None) -> None:
    outcome = "unavailable" if r is None else "refused" if r.refusal else "unanswerable" if r.error == text_to_sql.UNANSWERABLE else "error" if r.error else "ok"
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "question": question, "outcome": outcome, "secs": round(secs, 1)}
    if exc:
        entry["exception"] = f"{type(exc).__name__}: {exc}"
    if r:
        resp = r.model_dump() | {"row_count": len(r.rows), "rows": r.rows[:config.LOG_ROWS]}
        resp.pop("display_short")
        resp["display"] = {k: v[:config.LOG_ROWS] for k, v in r.display.items()}
        entry |= {"refusal": r.refusal, "rewritten_from": r.rewritten_from, "timing": r.timing, "trace": r.trace, "response": resp}
    _append(entry)


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    t0, r, exc = time.time(), None, None
    try:
        r = text_to_sql.ask(req.question)
        return r
    except httpx.HTTPError as e:  # Ollama or ClickHouse unreachable or erroring
        exc = e
        raise HTTPException(503, f"Model atau database tidak tersedia ({type(e).__name__}).") from e
    finally:
        log(req.question, r, time.time() - t0, exc)


@app.get("/summary/{job_id}")
def summary(job_id: str) -> dict:
    """The model-written paragraph for an answer, or null when it was rejected or the model is unavailable (the page keeps the rule-based sentence)."""
    t0 = time.time()
    try:
        result = narrate.run(job_id)
    except KeyError:
        raise HTTPException(404, "Ringkasan tidak ditemukan.") from None
    # the log keeps what the model wrote even when it was rejected, so a bad paragraph can be debugged
    _append({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "summary", "summary_id": job_id,
             "outcome": result["outcome"], "text": result["raw"], "secs": round(time.time() - t0, 1)})
    return {"summary": result["text"]}
