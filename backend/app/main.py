import httpx
from fastapi import FastAPI, HTTPException

from app import text_to_sql
from app.schemas import AskRequest, AskResponse

app = FastAPI(title="ClickHouse chat")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    try:
        return text_to_sql.ask(req.question)
    except httpx.HTTPError as e:  # Ollama or ClickHouse unreachable or erroring
        raise HTTPException(503, f"Model atau database tidak tersedia ({type(e).__name__}).") from e
