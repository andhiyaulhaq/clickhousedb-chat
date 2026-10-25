import os
from pathlib import Path

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
SQL_MODEL = os.getenv("SQL_MODEL", "text2sql-3b-v3")

CH_URL = os.getenv("CH_URL", "http://localhost:8123/")
CH_USER = os.getenv("APP_CH_USER", "app")  # the restricted user from clickhouse/app_user.sql, never `default`
CH_PASSWORD = os.getenv("APP_CH_PASSWORD", "app")

MAX_QUESTION_CHARS = 500
MAX_RETRIES = 2  # more than 2 did not help in the model project's eval

# one JSON line per /ask (question, SQL, outcome; never rows): review it for failure modes and retraining data
LOG_PATH = Path(os.getenv("QUERY_LOG", Path(__file__).resolve().parents[2] / "data" / "logs" / "queries.jsonl"))
