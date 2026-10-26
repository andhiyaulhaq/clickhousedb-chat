from app.notes import labeler, period_kind
from app.summary import _num, period_labels, summarize


def test_number_format():
    assert _num(3328, False) == "3.328" and _num(500552.28, False) == "500.552,28" and _num(0.63, False) == "0,63"
    assert _num(86621267.57, False) == "86,6 juta" and _num(1.25e9, False) == "1,2 miliar" and _num(2e6, False) == "2 juta"
    assert _num(500552.28, True) == "500,552.28" and _num(86621267.57, True) == "86.6 million"


def test_series_names_the_peak_and_the_trough():
    rows = [["2025-01-01", 18754300.28], ["2025-02-01", 21543295.6], ["2025-03-01", 33011490.81]]
    assert summarize(["bulan", "total_omset"], rows) == "3 periode. total omset: tertinggi pada Maret 2025 (33 juta), terendah pada Januari 2025 (18,8 juta)."
    assert summarize(["month", "revenue"], rows, english=True).startswith("3 periods. revenue: highest on March 2025 (33 million)")


def test_ranking_labels_with_the_name_not_the_id():
    rows = [["C803", "Dewi Santoso", 500552.28], ["C901", "Agus Halim", 499938.65], ["C1200", "Budi", 100]]
    s = summarize(["customer_id", "name", "deal_won_terbesar"], rows)
    assert s == "3 baris. deal won terbesar: tertinggi Dewi Santoso (500.552,28), terendah Budi (100)."


def test_nulls_are_skipped():
    assert summarize(["segmen", "n"], [["A", None], ["B", 5], ["C", 2]]) == "3 baris. n: tertinggi B (5), terendah C (2)."


def test_nothing_to_add():
    assert summarize(["n"], [[42]]) is None  # the stat tile has it
    assert summarize(["a", "b"], []) is None
    assert summarize(["nama", "segmen"], [["a", "x"], ["b", "y"]]) is None  # a plain list
    assert summarize(["segmen", "n"], [["A", 5], ["B", 5]]) is None  # nothing is higher or lower
    assert summarize(["a", "b"], [[1, 2], [3, 4]]) is None  # no label for the numbers
    assert summarize(["segmen", "n"], [["A", None], ["B", 5]]) is None  # one value is not a range


def labels(raw, sql="", english=False):
    fmt = labeler(raw, sql, english)
    return [fmt(l) for l in raw]


def test_months_are_named():
    assert labels(["2025-01-01", "2025-02-01", "2026-07-01"]) == ["Januari 2025", "Februari 2025", "Juli 2026"]
    assert labels(["2025-12-01", "2026-03-01"], english=True) == ["December 2025", "March 2026"]
    assert labels(["2025-03"]) == ["Maret 2025"]  # formatDateTime(..., '%Y-%m')


def test_quarters_are_q1_to_q4():
    assert labels(["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01"]) == ["Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025"]
    assert labels(["2025-01-01", "2025-04-01"], "SELECT toStartOfQuarter(d.closed_date) AS q FROM deals AS d") == ["Q1 2025", "Q2 2025"]
    # the same dates grouped by month are months: the SQL decides when the labels alone cannot
    assert labels(["2025-01-01", "2025-04-01"], "SELECT toStartOfMonth(d.closed_date) AS bulan FROM deals AS d") == ["Januari 2025", "April 2025"]


def test_years_weeks_and_days():
    assert labels(["2024-01-01", "2025-01-01"]) == ["2024", "2025"]
    assert labels(["2026-10-05", "2026-10-12"], "SELECT toStartOfWeek(t.created_at, 1)") == ["minggu 5 Oktober 2026", "minggu 12 Oktober 2026"]
    assert labels(["2026-10-05", "2026-10-12"], "", True) == ["week of 5 October 2026", "week of 12 October 2026"]  # a week apart, same weekday
    assert labels(["2026-10-24", "2026-10-25"]) == ["24 Oktober 2026", "25 Oktober 2026"]


def test_labels_that_are_not_plain_dates_stay_as_they_are():
    assert labels(["Enterprise", "SMB"]) == ["Enterprise", "SMB"]
    assert period_kind(["2026-10-24 13:00:00", "2026-10-24 14:00:00"]) is None  # hourly
    assert labels(["2026-10-24 13:00:00"]) == ["2026-10-24 13:00:00"]
    assert labels(["2026-02-30"]) == ["2026-02-30"]  # not a real date


def test_period_labels_for_the_table_and_the_chart_axis():
    rows = [["2025-01-01", 18754300.28], ["2025-02-01", 21543295.6], ["2025-03-01", 33011490.81]]
    full, short = period_labels(["bulan", "total_omset"], rows)
    assert full == {"bulan": ["Januari 2025", "Februari 2025", "Maret 2025"]} and short == {"bulan": ["Jan 2025", "Feb 2025", "Mar 2025"]}
    full, short = period_labels(["month", "revenue"], [["2025-10-01", 1], ["2026-03-01", 2]], "", True)
    assert full["month"] == ["October 2025", "March 2026"] and short["month"] == ["Oct 2025", "Mar 2026"]
    q = [["2025-01-01", 1], ["2025-04-01", 2], ["2025-07-01", 3]]
    assert period_labels(["q", "n"], q, "SELECT toStartOfQuarter(x)")[0]["q"] == ["Q1 2025", "Q2 2025", "Q3 2025"]
    assert period_labels(["q", "n"], q, "SELECT toStartOfQuarter(x)")[1]["q"] == ["Q1 2025", "Q2 2025", "Q3 2025"]  # no short form for a quarter


def test_period_labels_leave_other_columns_alone():
    assert period_labels(["segmen", "n"], [["A", 1], ["B", 2]]) == ({}, {})  # not dates
    assert period_labels(["dibuat", "n"], [["2026-10-24 13:05:22", 1], ["2026-10-24 14:10:00", 2]]) == ({}, {})  # timestamps stay as they are
    assert period_labels(["bulan", "n"], []) == ({}, {})


def test_period_labels_keep_a_null_as_blank_and_every_date_column():
    rows = [["2025-01-01", None, "2025-03-14"], ["2025-02-01", "2025-05-01", "2025-03-15"]]
    full, _ = period_labels(["bulan", "tutup", "tgl"], rows)
    assert full["bulan"] == ["Januari 2025", "Februari 2025"] and full["tutup"] == ["", "Mei 2025"]
    assert full["tgl"] == ["14 Maret 2025", "15 Maret 2025"]  # plain dates: day, month, year
