"""The API contract (docs/guide.md rule 6). The frontend codes against these two models."""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import config


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=config.MAX_QUESTION_CHARS)


class AskResponse(BaseModel):
    sql: str | None = None
    interpretation: str | None = None  # "how I read your question", filled by the summary step
    columns: list[str] = []
    rows: list[list[Any]] = []
    chart: dict | None = None  # filled by shaping.py
    summary: str | None = None  # filled by summary.py
    error: str | None = None  # user-facing, Indonesian; sql is still returned so the query can be inspected
    attempts: int = 0  # how many times the model was asked to repair the SQL
