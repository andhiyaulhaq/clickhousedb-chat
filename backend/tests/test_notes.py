import json
from pathlib import Path

import httpx

from app import config, text_to_sql
from app.notes import caveats, date_basis, is_english, partial_period, shape_note, totals_misleading

GOLD = Path(__file__).resolve().parents[2] / "data" / "gold"


def test_language_is_detected_from_the_gold_questions():
    """Both holdouts and the dev set, so a wrong language cannot slip in unnoticed."""
    qs = lambda f: [json.loads(l)["question"] for l in (GOLD / f).read_text(encoding="utf-8").splitlines() if l]
    assert [q for q in qs("holdout.jsonl") + qs("eval.jsonl") if is_english(q)] == []
    assert [q for q in qs("holdout_en.jsonl") if not is_english(q)] == []


def test_date_basis_comes_from_the_sql():
    created = "SELECT count() FROM deals AS d FINAL WHERE d.created_date >= today()"
    closed = "SELECT sum(d.value) FROM deals AS d FINAL WHERE d.stage = 'won' AND d.closed_date >= today()"
    assert date_basis(created, False) == "(Dasar tanggal: tanggal deal dibuat.)"
    assert date_basis(closed, False) == "(Dasar tanggal: tanggal deal ditutup.)"
    assert date_basis(closed, True) == "(Date basis: deal close date.)"
    assert date_basis("SELECT count() FROM customers AS c FINAL", False) == ""
    assert "dan" in date_basis(created.replace("WHERE", "WHERE d.closed_date > 0 AND"), False)  # both dates


def test_shape_note_only_for_a_long_descending_ranking_without_limit():
    ranked = "SELECT c.name, max(d.value) AS m FROM deals AS d FINAL INNER JOIN customers AS c FINAL ON d.customer_id = c.customer_id GROUP BY c.name ORDER BY m DESC"
    assert "bukan hanya yang teratas" in shape_note(ranked, 291, False)
    assert "not just the top ones" in shape_note(ranked, 291, True)
    assert shape_note(ranked, 20, False) == ""  # short enough to read
    assert shape_note(ranked + " LIMIT 5", 291, False) == ""  # the user asked for a top N
    assert shape_note(ranked.replace("DESC", "ASC"), 291, False) == ""  # time series and alphabetical lists
    assert shape_note("SELECT d.value FROM deals AS d FINAL", 291, False) == ""


def test_shape_note_warns_that_array_join_groups_overlap():
    per_product = "SELECT product, sum(d.value) AS r FROM deals AS d FINAL ARRAY JOIN d.products_involved AS product WHERE d.stage = 'won' GROUP BY product"
    assert "beberapa produk atau tag" in shape_note(per_product, 5, False)  # also for a short result
    assert "several products or tags" in shape_note(per_product, 5, True)
    assert shape_note(per_product.replace(" GROUP BY product", ""), 5, False) == ""  # not an aggregate
    both = shape_note(per_product + " ORDER BY r DESC", 30, False)
    assert "beberapa produk atau tag" in both and "bukan hanya yang teratas" in both


def test_caveats_joins_the_notes_and_is_none_when_there_is_nothing_to_say():
    assert caveats("SELECT count() FROM customers AS c FINAL", 1, False) is None
    sql = "SELECT d.value FROM deals AS d FINAL WHERE d.closed_date > today() ORDER BY d.value DESC"
    assert caveats(sql, 30, False) == "(Dasar tanggal: tanggal deal ditutup.) (Semua baris yang cocok ditampilkan, diurutkan menurun, bukan hanya yang teratas.)"


def test_sql_calls_keep_the_model_loaded(monkeypatch):
    sent = []

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "SELECT 1"}}

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: (sent.append(json), Reply())[1])
    text_to_sql.generate([{"role": "user", "content": "q"}])
    assert [s["keep_alive"] for s in sent] == [config.OLLAMA_KEEP_ALIVE]


MONTHLY = "SELECT toStartOfMonth(d.closed_date) AS bulan, sum(d.value) AS total_omset FROM deals AS d FINAL WHERE d.stage = 'won' AND d.closed_date >= {start} GROUP BY bulan ORDER BY bulan"


def test_partial_period_only_for_a_rolling_window_grouped_by_period():
    assert partial_period(MONTHLY.format(start="subtractYears(now(), 1)"))  # "1 tahun terakhir"
    assert partial_period(MONTHLY.format(start="subtractMonths(today(), 6)"))
    assert partial_period(MONTHLY.format(start="now() - INTERVAL 1 YEAR"))
    assert not partial_period(MONTHLY.format(start="toStartOfYear(subtractYears(today(), 1))"))  # last calendar year: whole months
    assert not partial_period(MONTHLY.format(start="toStartOfMonth(subtractMonths(today(), 6))"))
    assert not partial_period("SELECT count() FROM deals AS d FINAL WHERE d.closed_date >= subtractDays(today(), 90)")  # not grouped by period


def test_partial_period_note():
    assert "belum penuh" in shape_note(MONTHLY.format(start="subtractYears(now(), 1)"), 13, False)
    assert "partial" in shape_note(MONTHLY.format(start="subtractYears(now(), 1)"), 13, True)
    assert shape_note(MONTHLY.format(start="toStartOfYear(today())"), 13, False) == ""


def test_totals_are_misleading_for_a_top_n_and_for_overlapping_groups():
    assert totals_misleading("SELECT r.name, sum(d.value) AS t FROM deals AS d FINAL GROUP BY r.name ORDER BY t DESC LIMIT 5")
    assert totals_misleading("SELECT p, sum(d.value) FROM deals AS d FINAL ARRAY JOIN d.products_involved AS p GROUP BY p")
    assert not totals_misleading("SELECT c.segment, count() FROM customers AS c FINAL GROUP BY c.segment")
