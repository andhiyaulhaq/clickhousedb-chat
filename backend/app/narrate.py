"""A short paragraph about the result, written by a small instruct model and shown after the answer (docs/guide.md section 3).

The model never sees more than the question and the facts that summary.facts() computed in code, and its text is thrown away
unless every number in it is one of those facts. The rule-based sentence from summary.summarize() is already on screen, so a
rejected, slow or failed paragraph costs nothing. What is checked: numbers, and a claim of a rise or fall that the facts do not
support. What is not: names, and wording. Fluent text that is wrong in a way these checks miss is still possible.
"""
import re
import uuid
from collections import OrderedDict

import httpx

from app import config
from app.summary import Facts, number_tokens

MAX_JOBS = 100  # /ask registers a job per answer; the UI asks for it right after, so old ones can go
_jobs: OrderedDict[str, dict] = OrderedDict()

PACKS = {
    "id": (
        "Kamu menulis ringkasan singkat dari hasil query untuk menjawab pertanyaan pengguna, dalam bahasa Indonesia, 2 sampai 3 kalimat utuh. "
        "Gunakan HANYA nama dan angka yang tertulis di FAKTA, salin angka persis seperti tertulis, dan sebut nama item bersama angkanya. "
        "Jangan membulatkan, menghitung, atau membuat angka baru. Jangan menebak penyebab dan jangan menyebut SQL. "
        "Jangan menyebut atribut atau kesimpulan yang tidak tertulis di FAKTA (misalnya segmen, tim, atau bahwa data tidak ditemukan).",
        ("Pertanyaan", "FAKTA"),
        [
            ("Pertanyaan: omset per produk\nFAKTA:\n- jumlah baris: 3\n- total omset: tertinggi produk A (50 juta); terendah produk C (20 juta)\n"
             "- nilai per produk: A (50 juta), B (40 juta), C (20 juta)\n- jumlah seluruh baris untuk total omset: 110 juta\n- A menyumbang 45% dari total",
             "Produk A menghasilkan omset terbesar, yaitu 50 juta atau 45% dari total 110 juta. Produk C paling rendah dengan 20 juta."),
            ("Pertanyaan: omset per bulan tahun lalu\nFAKTA:\n- jumlah baris: 4\n- total omset: tertinggi bulan 2025-03-01 (33 juta); terendah bulan 2025-01-01 (18 juta)\n"
             "- nilai per bulan: 2025-01-01 (18 juta), 2025-02-01 (21 juta), 2025-03-01 (33 juta), 2025-04-01 (20 juta)\n"
             "- jumlah seluruh baris untuk total omset: 92 juta\n- 2025-03-01 menyumbang 36% dari total\n- total omset dari 2025-01-01 ke 2025-04-01: naik 11%",
             "Omset bulanan tertinggi terjadi pada 2025-03-01 sebesar 33 juta, dan terendah pada 2025-01-01 sebesar 18 juta. "
             "Dari 2025-01-01 ke 2025-04-01 omset naik 11%, dengan total 92 juta sepanjang periode."),
        ],
    ),
    "en": (
        "You write a short summary of a query result that answers the user's question, in English, 2 to 3 full sentences. "
        "Use ONLY names and numbers written in the FACTS, copy numbers exactly as written, and name the item together with its number. "
        "Do not round, calculate or invent numbers. Do not guess causes and do not mention SQL. "
        "Do not state attributes or conclusions that are not written in the FACTS (for example a segment, a team, or that no data was found).",
        ("Question", "FACTS"),
        [
            ("Question: revenue per product\nFACTS:\n- number of rows: 3\n- total revenue: highest product A (50 million); lowest product C (20 million)\n"
             "- values per product: A (50 million), B (40 million), C (20 million)\n- sum over all rows of total revenue: 110 million\n- A accounts for 45% of the total",
             "Product A earns the most, 50 million, which is 45% of the 110 million total. Product C is the lowest at 20 million."),
            ("Question: revenue per month last year\nFACTS:\n- number of rows: 4\n- total revenue: highest month 2025-03-01 (33 million); lowest month 2025-01-01 (18 million)\n"
             "- values per month: 2025-01-01 (18 million), 2025-02-01 (21 million), 2025-03-01 (33 million), 2025-04-01 (20 million)\n"
             "- sum over all rows of total revenue: 92 million\n- 2025-03-01 accounts for 36% of the total\n- total revenue from 2025-01-01 to 2025-04-01: rose 11%",
             "Monthly revenue peaked on 2025-03-01 at 33 million and was lowest on 2025-01-01 at 18 million. "
             "From 2025-01-01 to 2025-04-01 revenue rose 11%, for a total of 92 million over the period."),
        ],
    ),
}
_ABSENT = re.compile(r"tidak (?:ditemukan|ada|tersedia)|not found|no (?:data|results?|rows?)|none found", re.I)
_UP = re.compile(r"\b(naik|meningkat|bertambah|tumbuh|increas\w*|rose|rise|rising|grew|grow\w*)\b", re.I)
_DOWN = re.compile(r"\b(turun|menurun|menyusut|berkurang|decreas\w*|declin\w*|fell|fall\w*|drop\w*)\b", re.I)


def register(question: str, facts: Facts) -> str:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"question": question, "facts": facts, "result": None}
    while len(_jobs) > MAX_JOBS:
        _jobs.popitem(last=False)
    return job_id


def _messages(question: str, facts: Facts) -> list[dict]:
    system, (q, fact_label), examples = PACKS["en" if facts.english else "id"]
    body = f"{q}: {question}\n{fact_label}:\n" + "\n".join(f"- {line}" for line in facts.lines)
    shots = [m for user, reply in examples for m in ({"role": "user", "content": user}, {"role": "assistant", "content": reply})]
    return [{"role": "system", "content": system}, *shots, {"role": "user", "content": body}]


def generate(messages: list[dict]) -> str:
    r = httpx.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={"model": config.SUMMARY_MODEL, "messages": messages, "stream": False, "keep_alive": config.OLLAMA_KEEP_ALIVE,
              "options": {"temperature": 0, "num_predict": 200}},
        timeout=60,
    )
    r.raise_for_status()
    return " ".join(r.json()["message"]["content"].split())[:700]


def _fluent(text: str) -> bool:
    """A sentence, not a dump of rows: 'Eko Gunawan 4641 | Indah Lestari' and '61,45; 60,50' are what the model writes when it copies."""
    words = re.findall(r"[^\W\d_]{3,}", text)  # real words: a sentence with four dates in it is still a sentence
    return len(text.split()) >= 6 and len(words) >= 3 and "|" not in text and text[-1] in ".!?)"


def verify(text: str, facts: Facts) -> str | None:
    """None when the text is acceptable, else why not."""
    if not _fluent(text):
        return "not a sentence"
    extra = number_tokens(text) - facts.allowed
    if extra:
        return f"number {sorted(extra)[0]} is not in the facts"
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for tok in number_tokens(sentence):
            owners = facts.owners.get(tok)
            if owners and not any(o.lower() in sentence.lower() for o in owners):  # 21% is API-Gateway's, not Cloud-Storage-Pro's
                return f"number {tok} belongs to {sorted(owners)[0]}, which the sentence does not name"
    if _ABSENT.search(text):  # the facts are the rows that exist; a claim that something is missing is the model misreading them
        return "claims something is missing"
    if facts.trend != "up" and _UP.search(text) and not (facts.trend == "down" and _DOWN.search(text)):
        return "claims a rise the facts do not support"
    if facts.trend != "down" and _DOWN.search(text) and not (facts.trend == "up" and _UP.search(text)):
        return "claims a fall the facts do not support"
    return None


def run(job_id: str) -> dict:
    """{"text": str | None, "outcome": "ok" | "rejected: why" | "empty" | "unavailable", "raw": the model's text}. KeyError if unknown."""
    job = _jobs[job_id]
    if job["result"] is None:
        try:
            raw = generate(_messages(job["question"], job["facts"]))
        except (httpx.HTTPError, KeyError, ValueError):
            return {"text": None, "outcome": "unavailable", "raw": None}  # not cached: the user may ask again
        why = "empty" if not raw else verify(raw, job["facts"])
        job["result"] = {"text": None if why else raw, "outcome": "ok" if why is None else why if why == "empty" else f"rejected: {why}", "raw": raw}
    return job["result"]
