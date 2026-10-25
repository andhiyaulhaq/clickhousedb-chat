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
    ("SELECT * FROM deals INTO OUTFILE 'x'", Invalid),
    ("SELECT sales_rep FROM support_tickets", Unanswerable),
    ("SELECT * FROM crm.nope", Unanswerable),
])
def test_rejects(sql, exc):
    with pytest.raises(exc):
        validate(sql)


def test_limit():
    assert validate("SELECT deal_id FROM deals").endswith("LIMIT 1000")
    assert validate("SELECT deal_id FROM deals LIMIT 5") == "SELECT deal_id FROM deals LIMIT 5"
    assert validate("SELECT deal_id FROM deals LIMIT 99999").startswith("SELECT * FROM (")
    assert validate("SELECT deal_id FROM deals UNION ALL SELECT deal_id FROM deals").startswith("SELECT * FROM (")
