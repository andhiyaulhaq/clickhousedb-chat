"""Integration: needs ClickHouse with the crm data and the app user (docker compose up -d; uv run python pipeline.py setup)."""
import httpx
import pytest

from app import config, executor
from app.executor import ExecError


def _up():
    try:
        return httpx.get(config.CH_URL, timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="ClickHouse not running")


def test_select_returns_columns_and_numbers():
    cols, rows = executor.run("SELECT count() AS n FROM deals FINAL")
    assert cols == ["n"] and rows[0][0] == 8000  # a number, not a quoted UInt64


def test_row_cap_stops_runaway_results():
    # max_result_rows breaks at block boundaries (about 65k rows), so it is a backstop; the exact cap is the validator's LIMIT
    _, rows = executor.run("SELECT number FROM numbers(100000000)")
    assert len(rows) < 200000


@pytest.mark.parametrize("sql", [
    "DROP TABLE deals",
    "INSERT INTO deals (deal_id) VALUES ('x')",
    "SELECT * FROM system.users",
    "SELECT * FROM url('http://example.com', CSV, 'a String')",
    "SET max_execution_time = 1000",
])
def test_database_refuses(sql):
    with pytest.raises(ExecError):
        executor.run(sql)


def test_timeout():
    with pytest.raises(ExecError, match="TIMEOUT_EXCEEDED"):
        executor.run("SELECT count() FROM numbers(100000000000)")
