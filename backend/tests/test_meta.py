import json
from pathlib import Path

import pytest

from app import meta

DATA = Path(__file__).resolve().parents[2] / "data"


def questions(path):
    return [json.loads(l)["question"] for l in path.read_text(encoding="utf-8").splitlines() if l]


def test_no_gold_or_legit_question_is_meta():
    qs = [q for f in ("eval", "holdout", "holdout_en") for q in questions(DATA / "gold" / f"{f}.jsonl")]
    qs += [json.loads(l)["question"] for l in (DATA / "adversarial.jsonl").read_text(encoding="utf-8").splitlines()
           if json.loads(l)["expect"] == "refuse" or json.loads(l)["category"] == "legit"]
    assert [q for q in qs if meta.is_meta(q)] == []


@pytest.mark.parametrize("q", [
    "apa saja yang bisa aku tanyakan?", "data apa saja yang ada di database?", "Apa yang bisa kamu jawab?", "contoh pertanyaan dong",
    "what can I ask?", "What data do you have?", "help", "Bantuan",
])
def test_meta_questions(q):
    assert meta.is_meta(q)


def test_answer_language_follows_the_question():
    assert meta.answer("what can I ask?").columns == ["Data", "Example question"]
    r = meta.answer("apa saja yang bisa aku tanyakan?")
    assert r.columns == ["Data", "Contoh pertanyaan"] and len(r.rows) == 6 and r.sql is None and r.error is None
