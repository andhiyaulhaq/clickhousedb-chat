from app.summary import _num, summarize


def test_number_format():
    assert _num(3328, False) == "3.328" and _num(500552.28, False) == "500.552,28" and _num(0.63, False) == "0,63"
    assert _num(86621267.57, False) == "86,6 juta" and _num(1.25e9, False) == "1,2 miliar" and _num(2e6, False) == "2 juta"
    assert _num(500552.28, True) == "500,552.28" and _num(86621267.57, True) == "86.6 million"


def test_series_names_the_peak_and_the_trough():
    rows = [["2025-01-01", 18754300.28], ["2025-02-01", 21543295.6], ["2025-03-01", 33011490.81]]
    assert summarize(["bulan", "total_omset"], rows) == "3 periode. total omset tertinggi pada 2025-03-01 (33 juta), terendah pada 2025-01-01 (18,8 juta)."
    assert summarize(["month", "revenue"], rows, english=True).startswith("3 periods. Highest revenue on 2025-03-01 (33 million)")


def test_ranking_labels_with_the_name_not_the_id():
    rows = [["C803", "Dewi Santoso", 500552.28], ["C901", "Agus Halim", 499938.65], ["C1200", "Budi", 100]]
    s = summarize(["customer_id", "name", "deal_won_terbesar"], rows)
    assert s == "3 baris. deal won terbesar tertinggi: Dewi Santoso (500.552,28); terendah: Budi (100)."


def test_nulls_are_skipped():
    assert summarize(["segmen", "n"], [["A", None], ["B", 5], ["C", 2]]) == "3 baris. n tertinggi: B (5); terendah: C (2)."


def test_nothing_to_add():
    assert summarize(["n"], [[42]]) is None  # the stat tile has it
    assert summarize(["a", "b"], []) is None
    assert summarize(["nama", "segmen"], [["a", "x"], ["b", "y"]]) is None  # a plain list
    assert summarize(["segmen", "n"], [["A", 5], ["B", 5]]) is None  # nothing is higher or lower
    assert summarize(["a", "b"], [[1, 2], [3, 4]]) is None  # no label for the numbers
    assert summarize(["segmen", "n"], [["A", None], ["B", 5]]) is None  # one value is not a range
