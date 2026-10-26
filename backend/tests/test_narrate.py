import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, narrate, text_to_sql
from app.main import app
from app.summary import facts, number_tokens

SERIES = [["2025-01-01", 18754300.28, 308], ["2025-02-01", 21543295.6, 283], ["2025-03-01", 33011490.81, 301]]
COLS = ["bulan", "total_omset", "jumlah_deal"]


def make_facts(**kw):
    return facts(kw.get("columns", COLS), kw.get("rows", SERIES), kw.get("english", False), kw.get("question", "omset per bulan"))


def test_number_tokens_ignore_leading_zeros_and_keep_decimals():
    assert number_tokens("2025-03-01: 18,8 juta, 500.552,28 dan 0,63") == {"2025", "3", "1", "18,8", "500.552,28", "0,63"}


def test_facts_for_a_series():
    f = make_facts()
    assert f.trend == "up"
    assert "jumlah baris: 3" in f.lines and "total omset: tertinggi bulan 2025-03-01 (33 juta); terendah bulan 2025-01-01 (18,8 juta)" in f.lines
    assert "jumlah seluruh baris untuk total omset: 73,3 juta" in f.lines  # an additive column gets a total ...
    assert "2025-03-01 menyumbang 45% dari total" in f.lines
    assert any(l.startswith("total omset dari 2025-01-01 ke 2025-03-01: naik 76%") for l in f.lines)
    assert "nilai per bulan: 2025-01-01 (18,8 juta), 2025-02-01 (21,5 juta), 2025-03-01 (33 juta)" in f.lines  # a series in date order
    assert {"76", "73,3", "18,8", "33", "45"} <= f.allowed and f.owners == {}  # dates are paraphrased ("Maret"), so no owners


def test_a_rate_is_never_summed():
    f = facts(["nama", "win_rate"], [["A", 0.63], ["B", 0.58]], False)
    assert not any("seluruh baris" in l for l in f.lines) and f.trend is None
    f = facts(["customer_id", "name", "deal_won_terbesar"], [["C1", "A", 500.0], ["C2", "B", 100.0]], False)
    assert not any("seluruh baris" in l for l in f.lines)  # the maximum per customer is not additive either


def test_no_facts_when_there_is_nothing_to_say():
    assert facts(["n"], [[42]]) is None and facts(["a", "b"], []) is None
    assert facts(["segmen", "n"], [["A", 5], ["B", 5]]) is None


def test_english_facts():
    f = make_facts(english=True, columns=["month", "revenue", "deals"])
    assert f.english and "number of rows: 3" in f.lines and any("rose 76%" in l for l in f.lines)


def test_verify_accepts_copied_numbers_and_rejects_invented_ones():
    f = make_facts()
    ok = "Omset tertinggi pada Maret 2025 sebesar 33 juta, naik 76% dari Januari (18,8 juta). Totalnya 73,3 juta."
    assert narrate.verify(ok, f) is None
    assert "19" in narrate.verify("Omset bulan terendah sekitar 19 juta dibanding bulan lain.", f)  # rounded, not copied
    assert "12" in narrate.verify("Dalam data ini ada 12 bulan yang dicatat.", f)  # a number nobody gave
    assert narrate.verify("Pertanyaan ini menyebut 5 teratas dan ringkasan ini sudah sesuai.", make_facts(question="5 teratas")) is None  # the user's own number is fine


def test_verify_checks_the_direction():
    up, flat = make_facts(), facts(["segmen", "n"], [["A", 5], ["B", 2]], False, "")
    assert narrate.verify("Omset turun dari Januari ke Maret.", up) is not None
    assert narrate.verify("Omset naik dari Januari ke Maret.", up) is None
    assert "rise" in narrate.verify("Omset naik di segmen A sepanjang periode ini.", flat)  # a trend nobody computed
    assert narrate.verify("Segmen A tertinggi (5), B terendah (2).", flat) is None


def test_prompt_contains_only_the_facts_and_a_preview():
    f = make_facts()
    system, ranking, ranking_reply, series, series_reply, user = [m["content"] for m in narrate._messages("omset per bulan", f)]
    assert "bahasa Indonesia" in system and "angka baru" in system and "Produk A menghasilkan" in ranking_reply
    assert "Omset bulanan tertinggi" in series_reply  # a series has its own example: without it the model wrote "omset per bulan adalah 31,3 juta"
    assert "omset per bulan" in user and "- jumlah baris: 3" in user and "- nilai per bulan: 2025-01-01" in user
    assert "|" not in user  # no sample rows: the model echoed them back


@pytest.fixture
def job(monkeypatch):
    replies = []
    monkeypatch.setattr(narrate, "generate", lambda messages: replies.pop(0))
    return narrate.register("omset per bulan", make_facts()), replies


def test_run_returns_a_verified_paragraph_and_caches_it(job):
    job_id, replies = job
    replies.append("Omset tertinggi pada Maret 2025 sebesar 33 juta.")
    assert narrate.run(job_id) == {"text": "Omset tertinggi pada Maret 2025 sebesar 33 juta.", "outcome": "ok", "raw": "Omset tertinggi pada Maret 2025 sebesar 33 juta."}
    assert narrate.run(job_id)["outcome"] == "ok" and replies == []  # the model was asked once


def test_run_drops_a_paragraph_with_a_wrong_number_but_keeps_what_it_wrote(job):
    job_id, replies = job
    replies.append("Omset tertinggi pada bulan Maret sebesar 35 juta.")
    r = narrate.run(job_id)
    assert r["text"] is None and r["outcome"].startswith("rejected: number 35") and r["raw"] == "Omset tertinggi pada bulan Maret sebesar 35 juta."


def test_run_survives_an_unavailable_model_and_lets_the_user_retry(job, monkeypatch):
    job_id, replies = job
    monkeypatch.setattr(narrate, "generate", lambda m: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert narrate.run(job_id)["outcome"] == "unavailable"
    monkeypatch.setattr(narrate, "generate", lambda m: "Omset tertinggi pada bulan Maret sebesar 33 juta.")
    assert narrate.run(job_id)["outcome"] == "ok"


def test_unknown_job_and_the_job_limit():
    with pytest.raises(KeyError):
        narrate.run("nope")
    ids = [narrate.register("q", make_facts()) for _ in range(narrate.MAX_JOBS + 5)]
    assert ids[0] not in narrate._jobs and ids[-1] in narrate._jobs and len(narrate._jobs) == narrate.MAX_JOBS


def test_ask_registers_a_job_only_when_there_are_facts(monkeypatch):
    from app import executor
    monkeypatch.setattr(text_to_sql, "generate", lambda m: "SELECT count() AS n FROM deals FINAL")
    monkeypatch.setattr(executor, "run", lambda sql: (["bulan", "total_omset"], [["2025-01-01", 1.0], ["2025-02-01", 2.0]]))
    r = text_to_sql.ask("omset per bulan")
    assert r.summary_id in narrate._jobs and r.summary
    monkeypatch.setattr(executor, "run", lambda sql: (["n"], [[1]]))
    assert text_to_sql.ask("berapa deal?").summary_id is None


def test_summary_endpoint_returns_the_paragraph_and_logs_the_raw_text(job, tmp_path, monkeypatch):
    job_id, replies = job
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "q.jsonl")
    replies.append("Omset tertinggi pada bulan Maret sebesar 35 juta.")  # wrong number
    c = TestClient(app)
    assert c.get(f"/summary/{job_id}").json() == {"summary": None}
    entry = json.loads(config.LOG_PATH.read_text(encoding="utf-8"))
    assert entry["kind"] == "summary" and entry["summary_id"] == job_id and entry["outcome"].startswith("rejected") and entry["text"] == "Omset tertinggi pada bulan Maret sebesar 35 juta."
    assert c.get("/summary/unknown").status_code == 404


LABELS = [["Alpha", 50e6], ["Beta", 40e6], ["Gamma", 20e6]]


def test_numbers_know_which_item_they_belong_to():
    f = facts(["produk", "omset"], LABELS, False, "omset per produk")
    assert f.owners["50"] == {"Alpha"} and f.owners["45"] == {"Alpha"} and f.owners["20"] == {"Gamma"} and "3" not in f.owners
    assert narrate.verify("Alpha menghasilkan 50 juta atau 45% dari total omset yang tercatat.", f) is None
    # the real failure: Beta was credited with Alpha's share
    why = narrate.verify("Beta menyumbang 45% dari total omset yang tercatat sepanjang periode.", f)
    assert "45 belongs to Alpha" in why
    assert narrate.verify("Alpha menghasilkan 50 juta. Beta mencapai 40 juta dan Gamma 20 juta.", f) is None


def test_a_dump_of_rows_is_not_a_sentence():
    f = facts(["produk", "omset"], LABELS, False, "")
    for text in ("50 | Alpha | 40 | Beta", "50 juta; 40 juta", "Alpha 50 juta", "Alpha menghasilkan 50 juta dan Beta mencapai 40 juta tetapi"):
        assert narrate.verify(text, f) == "not a sentence", text


def test_a_claim_that_data_is_missing_is_rejected():
    f = make_facts()
    assert narrate.verify("Data omset untuk bulan Maret tidak ditemukan dalam hasil ini sama sekali.", f) == "claims something is missing"


def test_the_label_column_is_named_so_the_model_does_not_guess_what_it_is():
    f = facts(["title", "value"], [["New Logo #870", 500974.3], ["Migration #4641", 413742.98]], False, "")
    assert "value: tertinggi title New Logo #870 (500.974,30); terendah title Migration #4641 (413.742,98)" in f.lines


def test_no_narration_when_the_summary_model_is_switched_off(monkeypatch):
    from app import executor
    monkeypatch.setattr(config, "SUMMARY_MODEL", "")
    monkeypatch.setattr(text_to_sql, "generate", lambda m: "SELECT count() AS n FROM deals FINAL")
    monkeypatch.setattr(executor, "run", lambda sql: (["bulan", "total_omset"], [["2025-01-01", 1.0], ["2025-02-01", 2.0]]))
    r = text_to_sql.ask("omset per bulan")
    assert r.summary and r.summary_id is None  # the rule-based sentence stays


ROLLING = ("SELECT toStartOfMonth(d.closed_date) AS bulan, sum(d.value) AS total_omset FROM deals AS d FINAL "
                     "WHERE d.stage = 'won' AND d.closed_date >= subtractYears(now(), 1) GROUP BY bulan ORDER BY bulan")
WINDOW = [["2025-10-01", 4.4e6], ["2025-11-01", 29.3e6], ["2025-12-01", 29.2e6], ["2026-01-01", 26.4e6], ["2026-02-01", 31.3e6], ["2026-03-01", 20.1e6]]


def test_a_partial_first_period_is_not_the_lowest():
    from app.summary import summarize
    s = summarize(["bulan", "total_omset"], WINDOW, False, ROLLING)
    assert "tertinggi pada 2026-02-01 (31,3 juta), terendah pada 2026-01-01 (26,4 juta)" in s and "4,4 juta" not in s and "tidak dihitung: belum penuh" in s
    f = facts(["bulan", "total_omset"], WINDOW, False, "omset 1 tahun terakhir", ROLLING)
    assert "tertinggi bulan 2026-02-01 (31,3 juta); terendah bulan 2026-01-01 (26,4 juta)" in " ".join(f.lines)
    assert any("belum penuh" in l and "2025-10-01" in l and "2026-03-01" in l for l in f.lines)
    assert any(l.startswith("jumlah seluruh baris") for l in f.lines)  # the window total is still a real total
    assert f.trend == "up"  # change from 2025-11 to 2026-02 (29,3 to 31,3 juta), not from the partial October
    assert "2025-10-01 (4,4 juta)" in " ".join(f.lines)  # the partial value is still listed, with the explanation
    # without a rolling window nothing is left out
    assert "4,4 juta" in summarize(["bulan", "total_omset"], WINDOW, False, "")


def test_no_total_or_share_for_a_top_n_or_overlapping_groups():
    rows = [["Rudi", 21.4e6], ["Hendra", 20.6e6], ["Eko", 20.3e6]]
    sql = "SELECT r.name, sum(d.value) AS total_omset FROM deals AS d FINAL GROUP BY r.name ORDER BY total_omset DESC LIMIT 5"
    f = facts(["name", "total_omset"], rows, False, "top 5 sales", sql)
    assert not any("seluruh baris" in l or "menyumbang" in l for l in f.lines)
    assert any("seluruh baris" in l for l in facts(["name", "total_omset"], rows, False, "sales", "SELECT 1").lines)
    overlapping = "SELECT product, sum(d.value) AS total_revenue FROM deals AS d FINAL ARRAY JOIN d.products_involved AS product GROUP BY product"
    assert not any("accounts for" in l or "sum over" in l for l in facts(["product", "total_revenue"], rows, True, "revenue per product", overlapping).lines)
