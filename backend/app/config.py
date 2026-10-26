import os
from pathlib import Path

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
SQL_MODEL = os.getenv("SQL_MODEL", "text2sql-3b-v3")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "qwen2.5:3b-instruct")  # general instruct model under 3 GB; see backend/compare_interpret.py

CH_URL = os.getenv("CH_URL", "http://localhost:8123/")
CH_USER = os.getenv("APP_CH_USER", "app")  # the restricted user from clickhouse/app_user.sql, never `default`
CH_PASSWORD = os.getenv("APP_CH_PASSWORD", "app")

MAX_QUESTION_CHARS = 500
MAX_RETRIES = 2  # more than 2 did not help in the model project's eval

# one JSON line per /ask: the question, the full response (rows cut to LOG_ROWS, emails already masked), every failed SQL attempt
# with its error, the guard's refusal reason and timing. Read it to debug a bad answer and for failure modes and retraining data.
LOG_ROWS = 20
LOG_PATH = Path(os.getenv("QUERY_LOG", Path(__file__).resolve().parents[2] / "data" / "logs" / "queries.jsonl"))
