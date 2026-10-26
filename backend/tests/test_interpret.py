import json
from pathlib import Path

import httpx

from app import interpret


class Reply:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self.content}}


def test_returns_the_first_line_cleaned(monkeypatch):
    sent = {}
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: (sent.update(json), Reply('  "Saya membaca ini sebagai:  omset per bulan."\nCatatan: abaikan'))[1])
    assert interpret.interpret("omset per bulan", "SELECT 1") == "Saya membaca ini sebagai: omset per bulan."
    assert sent["model"] == interpret.config.SUMMARY_MODEL and sent["options"]["temperature"] == 0
    assert "SELECT 1" in sent["messages"][-1]["content"] and sent["messages"][-1]["role"] == "user"


def test_model_override(monkeypatch):
    sent = {}
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: (sent.update(json), Reply("x"))[1])
    interpret.interpret("q", "s", model="llama3.2")
    assert sent["model"] == "llama3.2"


def test_failure_means_no_line(monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "post", down)
    assert interpret.interpret("q", "s") is None
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Reply("   "))
    assert interpret.interpret("q", "s") is None


def test_language_is_detected_from_the_gold_questions():
    """All 133 Indonesian and all 133 English holdout questions, so a wrong pack cannot slip in unnoticed."""
    gold = Path(__file__).resolve().parents[2] / "data" / "gold"
    qs = lambda f: [json.loads(l)["question"] for l in (gold / f).read_text(encoding="utf-8").splitlines() if l]
    assert [q for q in qs("holdout.jsonl") if interpret.is_english(q)] == []
    assert [q for q in qs("holdout_en.jsonl") if not interpret.is_english(q)] == []


def test_prompt_uses_one_language_only(monkeypatch):
    sent = {}
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: (sent.update(json), Reply("x"))[1])
    interpret.interpret("which reps won the most deals?", "SELECT 1")
    assert "in English" in sent["messages"][0]["content"] and "Saya membaca" not in str(sent["messages"][1:-1])
    interpret.interpret("sales mana yang paling banyak menang?", "SELECT 1")
    assert "bahasa Indonesia" in sent["messages"][0]["content"] and "I read this as" not in str(sent["messages"][1:-1])


def test_consistent_drops_lines_that_contradict_the_sql():
    created = "SELECT sum(d.value) FROM deals AS d FINAL WHERE d.created_date >= toStartOfMonth(today())"
    activities = "SELECT toStartOfMonth(a.timestamp) AS bulan, count() FROM activities AS a GROUP BY bulan"
    # the two wrong lines from the query log
    assert not interpret.consistent("Saya membaca ini sebagai: jumlah semua deal yang ditutup bulan lalu.", created)
    assert not interpret.consistent("Saya membaca ini sebagai: jumlah sales per bulan di tahun kemarin.", activities)
    assert interpret.consistent("Saya membaca ini sebagai: jumlah nilai deal yang dibuat bulan ini.", created)
    assert interpret.consistent("Saya membaca ini sebagai: jumlah aktivitas per bulan.", activities)
    # a line about tickets over SQL that never reads support_tickets
    assert not interpret.consistent("I read this as: the number of tickets.", "SELECT count() FROM deals AS d FINAL")
    assert interpret.consistent("I read this as: the number of tickets with status open.", "SELECT count() FROM support_tickets AS t FINAL")


def test_interpret_returns_none_for_an_inconsistent_line(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Reply("Saya membaca ini sebagai: deal yang ditutup bulan lalu."))
    assert interpret.interpret("total deal", "SELECT sum(d.value) FROM deals AS d FINAL WHERE d.created_date > today()") is None


def test_date_basis_comes_from_the_sql():
    created = "SELECT count() FROM deals AS d FINAL WHERE d.created_date >= today()"
    closed = "SELECT sum(d.value) FROM deals AS d FINAL WHERE d.stage = 'won' AND d.closed_date >= today()"
    assert interpret.date_basis("jumlah deal per bulan.", created, False) == " (Dasar tanggal: tanggal deal dibuat.)"
    assert interpret.date_basis("omset per bulan.", closed, False) == " (Dasar tanggal: tanggal deal ditutup.)"
    assert interpret.date_basis("revenue per month.", closed, True) == " (Date basis: deal close date.)"
    assert interpret.date_basis("deal yang dibuat tahun ini.", created, False) == ""  # the line already says it
    assert interpret.date_basis("jumlah pelanggan.", "SELECT count() FROM customers AS c FINAL", False) == ""
    assert interpret.date_basis("x", created.replace("WHERE", "WHERE d.closed_date > 0 AND"), False).count("dan") == 1  # both dates


def test_interpret_appends_the_date_basis(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Reply("Saya membaca ini sebagai: jumlah deal per bulan."))
    sql = "SELECT toStartOfMonth(d.created_date) AS bulan, count() FROM deals AS d FINAL GROUP BY bulan"
    assert interpret.interpret("deal per bulan", sql) == "Saya membaca ini sebagai: jumlah deal per bulan. (Dasar tanggal: tanggal deal dibuat.)"


def test_calls_keep_the_model_loaded(monkeypatch):
    from app import text_to_sql
    sent = []
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: (sent.append(json), Reply("SELECT 1"))[1])
    interpret.interpret("q", "s")
    text_to_sql.generate([{"role": "user", "content": "q"}])
    assert [s["keep_alive"] for s in sent] == [interpret.config.OLLAMA_KEEP_ALIVE] * 2
