from app.shaping import mask, pick_chart


def test_mask_emails_anywhere():
    rows = [["Budi", "budi.santoso@acme.co.id", 5], ["x", "Hubungi: ani@mail.com", None], ["t", ["a@b.io", "no mail"], 1]]
    assert mask(rows) == [["Budi", "b***@acme.co.id", 5], ["x", "Hubungi: a***@mail.com", None], ["t", ["a***@b.io", "no mail"], 1]]


def chart(columns, rows):
    c = pick_chart(columns, rows)
    return c and (c.type, c.x, c.y)


def test_stat():
    assert chart(["n"], [[42]]) == ("stat", None, ["n"])
    assert chart(["n"], [["abc"]]) is None


def test_line_for_dates():
    assert chart(["bulan", "omset", "deals"], [["2026-01-01", 1, 2.5], ["2026-02-01", None, 3]]) == ("line", "bulan", ["omset", "deals"])
    assert chart(["m", "n"], [["2026-01", 1], ["2026-02", 2]])[0] == "line"


def test_bar_for_categories():
    assert chart(["segmen", "omset"], [["Enterprise", 10], ["SMB", 5]]) == ("bar", "segmen", ["omset"])


def test_table_fallbacks():
    assert chart(["a", "b"], []) is None
    assert chart(["segmen", "omset"], [["Enterprise", 10]]) is None  # one category is not a chart
    assert chart(["nama", "segmen", "omset"], [["a", "x", 1], ["b", "y", 2]]) is None  # extra text column
    assert chart(["nama", "omset"], [[f"n{i}", i] for i in range(31)]) is None  # too many bars
    assert chart(["a", "b"], [[1, 2], [3, 4]]) is None  # numeric x axis
