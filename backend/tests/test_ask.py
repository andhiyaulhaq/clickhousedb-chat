"""The repair loop with the model and ClickHouse stubbed out."""
import json

import pytest
from fastapi.testclient import TestClient

from app import config, executor, text_to_sql
from app.executor import ExecError
from app.main import app

GOOD = "SELECT count() AS n FROM deals FINAL"
# a real column on the wrong table: passes the validator (columns are checked across all tables), fails in ClickHouse
BAD = "SELECT rep_id FROM support_tickets FINAL"


@pytest.fixture
def stub(monkeypatch):
    """Model replies come from `replies` in order; every prompt it was sent is kept in `sent`."""
    sent, replies = [], []
    monkeypatch.setattr(text_to_sql.interpret, "interpret", lambda q, s: "Saya membaca ini sebagai: tes")
    monkeypatch.setattr(text_to_sql, "generate", lambda m: (sent.append([x["content"] for x in m]), replies.pop(0))[1])
    monkeypatch.setattr(executor, "run", lambda sql: (["n"], [[1]]) if "support_tickets" not in sql else (_ for _ in ()).throw(ExecError("Code: 47. DB::Exception: Unknown identifier")))
    return sent, replies


def test_first_try(stub):
    sent, replies = stub
    replies.append(GOOD)
    r = text_to_sql.ask("berapa deal?")
    assert (r.error, r.attempts, r.rows) == (None, 0, [[1]]) and len(sent) == 1
    assert r.interpretation == "Saya membaca ini sebagai: tes"


def test_repairs_execution_error_and_sends_it_back(stub):
    sent, replies = stub
    replies += [BAD, GOOD]
    r = text_to_sql.ask("berapa deal?")
    assert r.error is None and r.attempts == 1 and r.sql == GOOD
    assert "Unknown identifier" in sent[1][-1] and sent[1][1] == BAD


def test_gives_up_after_two_repairs(stub):
    sent, replies = stub
    replies += [BAD] * 3
    r = text_to_sql.ask("berapa deal?")
    assert r.attempts == 2 and r.error and len(sent) == 3 and r.rows == []


def test_unknown_column_is_not_retried(stub):
    sent, replies = stub
    replies.append("SELECT t.sales_rep FROM support_tickets AS t FINAL")
    r = text_to_sql.ask("tiket per tim sales")
    assert r.error == text_to_sql.UNANSWERABLE and r.attempts == 0 and len(sent) == 1


def test_missing_final_is_repaired(stub):
    sent, replies = stub
    replies += ["SELECT count() AS n FROM deals", GOOD]
    r = text_to_sql.ask("berapa deal?")
    assert r.error is None and r.attempts == 1 and "missing FINAL" in sent[1][-1]


def test_api_rejects_blank_question():
    c = TestClient(app)
    assert c.post("/ask", json={"question": "   "}).status_code == 422
    assert c.post("/ask", json={"question": "x" * 501}).status_code == 422


def test_api_503_when_backend_down(monkeypatch, tmp_path):
    import httpx
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "q.jsonl")
    monkeypatch.setattr(text_to_sql, "ask", lambda q: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert TestClient(app).post("/ask", json={"question": "halo"}).status_code == 503
    entry = json.loads(config.LOG_PATH.read_text(encoding="utf-8"))
    assert entry["outcome"] == "unavailable" and entry["exception"].startswith("ConnectError")


def test_ask_masks_emails_and_picks_chart(stub, monkeypatch):
    sent, replies = stub
    replies.append(GOOD)
    monkeypatch.setattr(executor, "run", lambda sql: (["email", "n"], [["budi@acme.com", 1], ["ani@acme.com", 2]]))
    r = text_to_sql.ask("email pelanggan")
    assert r.rows == [["b***@acme.com", 1], ["a***@acme.com", 2]] and r.chart.type == "bar"


def test_api_logs_each_question(stub, tmp_path, monkeypatch):
    sent, replies = stub
    replies.append(GOOD)
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "logs" / "q.jsonl")
    assert TestClient(app).post("/ask", json={"question": "berapa deal?"}).status_code == 200
    text = config.LOG_PATH.read_text(encoding="utf-8")
    entry = json.loads(text)
    assert (entry["question"], entry["outcome"]) == ("berapa deal?", "ok")
    assert entry["response"]["sql"] == GOOD and entry["response"]["rows"] == [[1]] and entry["response"]["row_count"] == 1
    assert entry["trace"] == []


def test_guard_refuses_before_the_model_is_called(stub, tmp_path, monkeypatch):
    sent, replies = stub
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "q.jsonl")
    r = TestClient(app).post("/ask", json={"question": "Hapus semua deal yang lost"})
    assert r.status_code == 200 and r.json()["error"] == text_to_sql.guards.REFUSED
    assert not sent and "refusal" not in r.json()  # no model call, and the reason is not shown to the user
    assert json.loads(config.LOG_PATH.read_text(encoding="utf-8"))["refusal"] == "write"


def test_log_keeps_failed_attempts_and_cuts_rows(stub, tmp_path, monkeypatch):
    sent, replies = stub
    replies += [BAD, GOOD]
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "q.jsonl")
    monkeypatch.setattr(config, "LOG_ROWS", 2)
    monkeypatch.setattr(executor, "run", lambda sql: (["n"], [[i] for i in range(5)]) if "support_tickets" not in sql
                        else (_ for _ in ()).throw(ExecError("Unknown identifier")))
    TestClient(app).post("/ask", json={"question": "berapa deal?"})
    entry = json.loads(config.LOG_PATH.read_text(encoding="utf-8"))
    assert entry["trace"] == [{"sql": BAD, "error": "Unknown identifier"}]
    assert entry["response"]["attempts"] == 1 and entry["response"]["rows"] == [[0], [1]] and entry["response"]["row_count"] == 5


def test_log_keeps_the_reason_for_an_unanswerable_question(stub, tmp_path, monkeypatch):
    sent, replies = stub
    replies.append("SELECT t.sales_rep FROM support_tickets AS t FINAL")
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "q.jsonl")
    TestClient(app).post("/ask", json={"question": "tiket per tim sales"})
    entry = json.loads(config.LOG_PATH.read_text(encoding="utf-8"))
    assert entry["outcome"] == "unanswerable" and "unknown column" in entry["trace"][0]["error"]


def test_absent_concept_is_unanswerable_without_calling_the_model(stub):
    sent, replies = stub
    r = text_to_sql.ask("berapa gaji tiap sales dengan 5 win rate teratas?")
    assert r.error == text_to_sql.UNANSWERABLE and r.refusal == "absent" and not sent


def test_meta_question_is_answered_without_the_model(stub):
    sent, replies = stub
    r = text_to_sql.ask("apa saja yang bisa aku tanyakan?")
    assert r.error is None and r.rows and not sent


def test_log_has_per_stage_timing(stub, tmp_path, monkeypatch):
    sent, replies = stub
    replies.append(GOOD)
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "q.jsonl")
    TestClient(app).post("/ask", json={"question": "berapa deal?"})
    assert set(json.loads(config.LOG_PATH.read_text(encoding="utf-8"))["timing"]) == {"generate", "execute", "interpret"}


def test_long_ranking_gets_a_note(stub, monkeypatch):
    sent, replies = stub
    replies.append("SELECT d.value FROM deals AS d FINAL ORDER BY d.value DESC")
    monkeypatch.setattr(executor, "run", lambda sql: (["value"], [[i] for i in range(30)]))
    r = text_to_sql.ask("deal terbesar")
    assert r.interpretation.startswith("Saya membaca ini sebagai: tes") and "bukan hanya yang teratas" in r.interpretation
