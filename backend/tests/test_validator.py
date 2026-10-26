import json
from pathlib import Path

import pytest

from app.validator import Invalid, Unanswerable, validate

GOLD = Path(__file__).resolve().parents[2] / "data" / "gold"
ROWS = [json.loads(l) for f in ("eval.jsonl", "holdout.jsonl") for l in (GOLD / f).read_text(encoding="utf-8").splitlines() if l]


def test_gold_all_pass():
    bad = []
    for r in ROWS:
        try:
            validate(r["sql"])
        except Invalid as e:
            bad.append((r["id"], str(e)))
    assert len(ROWS) == 267
    assert not bad, bad


@pytest.mark.parametrize("sql,exc", [
    ("DROP TABLE deals", Invalid),
    ("SELECT 1; DROP TABLE deals", Invalid),
    ("INSERT INTO deals VALUES (1)", Invalid),
    ("SELECT * FROM system.tables", Unanswerable),
    ("SELECT * FROM url('http://x', CSV)", Invalid),
    ("SELECT * FROM file('/etc/passwd')", Invalid),
    ("SELECT * FROM deals FINAL INTO OUTFILE 'x'", Invalid),
    ("SELECT sales_rep FROM support_tickets", Unanswerable),
    ("SELECT * FROM crm.nope", Unanswerable),
    ("SELECT r.team FROM support_tickets AS t FINAL JOIN customers AS c FINAL ON 1 JOIN sales_reps AS r ON c.rep_id = r.rep_id", Unanswerable),
])
def test_rejects(sql, exc):
    with pytest.raises(exc):
        validate(sql)


def test_limit():
    assert validate("SELECT deal_id FROM deals FINAL").endswith("LIMIT 1000")
    assert validate("SELECT deal_id FROM deals FINAL LIMIT 5") == "SELECT deal_id FROM deals FINAL LIMIT 5"
    assert validate("SELECT deal_id FROM deals FINAL LIMIT 99999").startswith("SELECT * FROM (")
    assert validate("SELECT deal_id FROM deals FINAL UNION ALL SELECT deal_id FROM deals FINAL").startswith("SELECT * FROM (")


def test_final_required():
    with pytest.raises(Invalid, match="missing FINAL"):
        validate("SELECT d.deal_id FROM deals AS d")
    with pytest.raises(Invalid, match="missing FINAL"):
        validate("SELECT d.deal_id FROM deals AS d FINAL JOIN customers AS c ON d.customer_id = c.customer_id")
    validate("SELECT r.rep_id FROM sales_reps AS r")  # not a ReplacingMergeTree table


def test_outer_subquery_alias_may_shadow_inner_table_alias():
    validate("SELECT c.total FROM (SELECT c.customer_id, count() AS total FROM customers AS c FINAL GROUP BY c.customer_id) AS c")
    with pytest.raises(Unanswerable):  # a plain table alias is still checked against its own table
        validate("SELECT c.rep_id FROM customers AS c FINAL")


def test_query_must_read_a_table():
    for sql in ("SELECT 'Good morning' AS salam", "SELECT now()", "SELECT 1"):
        with pytest.raises(Unanswerable):
            validate(sql)


def test_unknown_attributes_key_is_unanswerable():
    with pytest.raises(Unanswerable):
        validate("SELECT c.name FROM customers AS c FINAL WHERE c.attributes['city'] = 'Bandung'")
    assert validate("SELECT c.name FROM customers AS c FINAL WHERE c.attributes['region'] = 'APAC' LIMIT 5")
