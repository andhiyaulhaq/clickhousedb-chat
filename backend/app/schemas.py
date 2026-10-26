"""The API contract (docs/guide.md rule 6). The frontend codes against these two models."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app import config


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=config.MAX_QUESTION_CHARS)


class Chart(BaseModel):
    """stat: the single value is rows[0][0]. line/bar: x and y are column names. No chart means table only."""
    type: Literal["stat", "line", "bar"]
    x: str | None = None
    y: list[str]


class AskResponse(BaseModel):
    sql: str | None = None
    interpretation: str | None = None  # caveats read from the SQL: which deal date, overlapping groups, an unbounded ranking
    columns: list[str] = []
    rows: list[list[Any]] = []
    display: dict[str, list[str]] = {}  # date column -> label per row ("Januari 2025", "Q3 2026") for the table; rows keep the raw dates
    display_short: dict[str, list[str]] = {}  # the same, short ("Jan 2025"), for a chart axis
    chart: Chart | None = None  # filled by shaping.py
    summary: str | None = None  # one rule-based sentence (summary.py), shown at once
    summary_id: str | None = None  # GET /summary/{id} returns a model-written paragraph, checked against the data; may be null
    error: str | None = None  # user-facing, Indonesian; sql is still returned so the query can be inspected
    attempts: int = 0  # how many times the model was asked to repair the SQL
    trace: list[dict] = Field(default_factory=list, exclude=True)  # every failed SQL attempt and why, for the query log only
    timing: dict = Field(default_factory=dict, exclude=True)  # seconds spent in generate / execute, for the query log
    refusal: str | None = Field(default=None, exclude=True)  # why the input guard refused; for the query log, never sent to the client
