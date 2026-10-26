import json
from pathlib import Path

import httpx

from app import config, text_to_sql
from datetime import date

from app import notes
from app.notes import align_window, caveats, date_basis, is_english, partial_period, shape_note, totals_misleading, window_note

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


NOW = date(2026, 10, 26)  # a Monday
WINDOWED = "SELECT toStartOf{g}(x.d{mode}) AS p, count() FROM t AS x FINAL WHERE x.d >= {start} GROUP BY p"


def windowed(g, start, mode=""):
    return WINDOWED.format(g=g, start=start, mode=mode)


def test_a_rolling_window_becomes_whole_periods():
    sql, window = align_window(windowed("Month", "subtractYears(now(), 1)"), NOW)
    assert "x.d >= toStartOfMonth(subtractYears(today(), 1)) AND x.d < toStartOfMonth(today())" in sql
    assert window == {"start": "2025-10-01", "end": "2026-09-01"}  # twelve months: October 2025 to September 2026
    assert align_window(windowed("Month", "subtractMonths(now(), 6)"), NOW)[1] == {"start": "2026-04-01", "end": "2026-09-01"}
    assert align_window(windowed("Month", "now() - INTERVAL 1 YEAR"), NOW)[1] == {"start": "2025-10-01", "end": "2026-09-01"}
    assert align_window(windowed("Quarter", "subtractYears(today(), 1)"), NOW)[1] == {"start": "2025-10-01", "end": "2026-07-01"}  # Q4 2025 to Q3 2026
    sql, window = align_window(windowed("Week", "subtractMonths(now(), 3)", ", 1"), NOW)
    assert "x.d >= toStartOfWeek(subtractMonths(today(), 3), 1) AND x.d < toStartOfWeek(today(), 1)" in sql
    assert window == {"start": "2026-07-20", "end": "2026-10-19"}  # the week of 19 October is the last finished one
    assert align_window(windowed("Week", "subtractWeeks(now(), 8)", ", 1"), NOW)[1] == {"start": "2026-08-31", "end": "2026-10-19"}


def test_windows_that_are_already_whole_or_cannot_be_are_left_alone():
    for sql in (
        windowed("Month", "toStartOfYear(subtractYears(today(), 1))") + " AND x.d < toStartOfYear(today())",  # aligned, has an upper bound
        windowed("Month", "subtractYears(now(), 1)") + " AND x.d < today()",  # the model already bounded it
        windowed("Month", "subtractDays(now(), 90)"),  # days cannot make whole months
        windowed("Month", "subtractWeeks(now(), 6)"),
        windowed("Quarter", "subtractMonths(now(), 6)"),
        windowed("Year", "subtractMonths(now(), 18)"),
        "SELECT count() FROM t AS x FINAL WHERE x.d >= subtractYears(now(), 1)",  # not grouped by a period
        "SELECT toStartOfDay(x.d) AS p, count() FROM t AS x FINAL WHERE x.d >= subtractDays(now(), 7) GROUP BY p",  # last 7 days per day
    ):
        assert align_window(sql, NOW) == (sql, None), sql


def test_the_window_note_names_the_range():
    month = windowed("Month", "subtractYears(now(), 1)")
    assert window_note({"start": "2025-10-01", "end": "2026-09-01"}, month, False) == "(Rentang waktu disesuaikan ke periode penuh: Oktober 2025 sampai September 2026.)"
    assert window_note({"start": "2025-10-01", "end": "2026-09-01"}, month, True) == "(Time range adjusted to whole periods: October 2025 to September 2026.)"
    assert window_note({"start": "2026-09-01", "end": "2026-09-01"}, month, False) == "(Rentang waktu disesuaikan ke periode penuh: September 2026.)"  # "1 bulan terakhir"
    sql, window = align_window(month, NOW)
    both = caveats(sql, 12, False, ["2025-10-01", "2026-09-01"], window)
    assert both.startswith("(Rentang waktu disesuaikan") and "belum penuh" not in both and "masih berjalan" not in both  # one note, not three
