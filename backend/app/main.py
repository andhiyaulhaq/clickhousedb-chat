import json
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException

from app import config, text_to_sql
from app.schemas import AskRequest, AskResponse

app = FastAPI(title="ClickHouse chat")


def log(question: str, r: AskResponse | None, secs: float, exc: Exception | None = None) -> None:
    outcome = "unavailable" if r is None else "refused" if r.refusal else "unanswerable" if r.error == text_to_sql.UNANSWERABLE else "error" if r.error else "ok"
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "question": question, "outcome": outcome, "secs": round(secs, 1)}
    if exc:
        entry["exception"] = f"{type(exc).__name__}: {exc}"
    if r:
        resp = r.model_dump() | {"row_count": len(r.rows), "rows": r.rows[:config.LOG_ROWS]}
        entry |= {"refusal": r.refusal, "trace": r.trace, "response": resp}
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
