import json
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException

from app import config, text_to_sql
from app.schemas import AskRequest, AskResponse

app = FastAPI(title="ClickHouse chat")


def log(question: str, r: AskResponse | None, secs: float) -> None:
    outcome = "unavailable" if r is None else "refused" if r.refusal else "unanswerable" if r.error == text_to_sql.UNANSWERABLE else "error" if r.error else "ok"
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "question": question, "outcome": outcome, "secs": round(secs, 1)}
    if r:
        entry |= {"sql": r.sql, "attempts": r.attempts, "rows": len(r.rows), "chart": r.chart and r.chart.type, "error": r.error, "refusal": r.refusal}
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    t0, r = time.time(), None
    try:
        r = text_to_sql.ask(req.question)
        return r
    except httpx.HTTPError as e:  # Ollama or ClickHouse unreachable or erroring
        raise HTTPException(503, f"Model atau database tidak tersedia ({type(e).__name__}).") from e
    finally:
        log(req.question, r, time.time() - t0)
