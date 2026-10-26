"""One line saying how the SQL read the question (docs/guide.md section 3). It sees the question and the SQL, never the rows.

The point is to expose the assumptions a wrong-but-plausible answer hides: which deal stage was counted, which period,
how it was grouped. A failure here returns None: the answer is still useful without the line.
"""
import re

import httpx

from app import config

# The small model does not reliably follow "answer in the language of the question" (5 of 8 wrong when tried), so the
# language is decided here and the model only ever sees instructions and examples in that language.
_EN = {"the", "how", "what", "which", "show", "each", "with", "and", "of", "for", "who", "are", "is", "have", "last", "this", "than",
       "more", "most", "many", "did", "does", "from", "revenue", "average", "rank", "number", "only", "please", "by", "customers",
       "reps", "tickets", "products", "companies", "activity", "duration", "value"}  # no word that is also Indonesian or SQL-ish: total, in, to, all, list
_ID = {"yang", "berapa", "dan", "di", "tiap", "dengan", "tampilkan", "siapa", "apa", "dari", "untuk", "ada", "tahun", "bulan",
       "lebih", "pelanggan", "mana", "sama", "yg", "brp", "tolong", "dong", "kasih", "cari", "milik", "semua", "pernah", "masih",
       "sudah", "belum", "tidak", "jumlah", "omset", "tiket", "rata", "aktivitas"}


def is_english(question: str) -> bool:
    words = re.findall(r"[a-z']+", question.lower())
    return sum(w in _EN for w in words) > sum(w in _ID for w in words)  # a tie (or mixed) stays Indonesian


PACKS = {
    "id": dict(
        system=(
            "Kamu menjelaskan bagaimana sebuah query SQL menafsirkan pertanyaan pengguna tentang data CRM. "
            "Tulis SATU kalimat pendek (maksimal 30 kata) dalam bahasa Indonesia. "
            "Sebutkan metrik, filter (misalnya status deal atau tiket), periode waktu, dan pengelompokan yang benar-benar ada di SQL, "
            "dan sebutkan asumsi yang tidak dinyatakan pengguna. Jangan menambahkan hal yang tidak ada di SQL. "
            "Jika query menampilkan daftar baris dan bukan menghitung, tulis 'daftar', bukan 'jumlah'. "
            "Omset berarti jumlah nilai deal dengan stage 'won'. Awali dengan 'Saya membaca ini sebagai:'."
        ),
        examples=[
            ("omset per bulan tahun lalu",
             "SELECT toStartOfMonth(d.closed_date) AS bulan, sum(d.value) AS total_omset FROM deals AS d FINAL WHERE d.stage = 'won' "
             "AND d.closed_date >= toStartOfYear(subtractYears(today(), 1)) AND d.closed_date < toStartOfYear(today()) GROUP BY bulan ORDER BY bulan",
             "Saya membaca ini sebagai: total nilai deal berstatus won (omset), dikelompokkan per bulan, untuk tahun kalender lalu."),
            ("berapa total deal bulan kemarin",
             "SELECT sum(d.value) AS total_deal FROM deals AS d FINAL WHERE d.closed_date >= toStartOfMonth(subtractMonths(today(), 1)) "
             "AND d.closed_date < toStartOfMonth(today())",
             "Saya membaca ini sebagai: jumlah nilai semua deal yang ditutup bulan lalu, baik won maupun lost."),
            ("pelanggan yang punya deal lost di atas 500 ribu",
             "SELECT DISTINCT c.customer_id, c.name FROM customers AS c FINAL INNER JOIN deals AS d FINAL ON c.customer_id = d.customer_id "
             "WHERE d.stage = 'lost' AND d.value > 500000",
             "Saya membaca ini sebagai: daftar pelanggan yang punya minimal satu deal berstatus lost dengan nilai di atas 500.000."),
        ],
    ),
    "en": dict(
        system=(
            "You explain how a SQL query interpreted a user's question about CRM data. "
            "Write ONE short sentence (at most 30 words) in English. "
            "Name the metric, the filters (for example deal or ticket status), the time period and the grouping that are really in the SQL, "
            "and any assumption the user did not state. Do not add anything that is not in the SQL. "
            "If the query lists rows rather than counting them, say 'list of', not 'number of'. "
            "Revenue means the sum of deal value with stage 'won'. Start with 'I read this as:'."
        ),
        examples=[
            ("how many open tickets?",
             "SELECT count() AS n FROM support_tickets AS t FINAL WHERE t.status = 'open'",
             "I read this as: the number of support tickets whose status is exactly 'open' (not 'in_progress')."),
            ("total revenue per month last year",
             "SELECT toStartOfMonth(d.closed_date) AS month, sum(d.value) AS revenue FROM deals AS d FINAL WHERE d.stage = 'won' "
             "AND d.closed_date >= toStartOfYear(subtractYears(today(), 1)) AND d.closed_date < toStartOfYear(today()) GROUP BY month ORDER BY month",
             "I read this as: the summed value of won deals (revenue), grouped by month, for the previous calendar year."),
            ("customers with a lost deal above 500,000",
             "SELECT DISTINCT c.customer_id, c.name FROM customers AS c FINAL INNER JOIN deals AS d FINAL ON c.customer_id = d.customer_id "
             "WHERE d.stage = 'lost' AND d.value > 500000",
             "I read this as: a list of customers with at least one deal in stage lost worth more than 500,000."),
        ],
    ),
}


def _messages(question: str, sql: str) -> list[dict]:
    pack = PACKS["en" if is_english(question) else "id"]
    ask = lambda q, s: {"role": "user", "content": f"Pertanyaan: {q}\nSQL: {s}"}
    shots = [m for q, s, a in pack["examples"] for m in (ask(q, s), {"role": "assistant", "content": a})]
    return [{"role": "system", "content": pack["system"]}, *shots, ask(question, sql)]


def interpret(question: str, sql: str, model: str | None = None) -> str | None:
    try:
        r = httpx.post(
            f"{config.OLLAMA_URL}/api/chat",
            json={"model": model or config.SUMMARY_MODEL, "messages": _messages(question, sql), "stream": False,
                  "options": {"temperature": 0, "num_predict": 100}},
            timeout=60,
        )
        r.raise_for_status()
        text = r.json()["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    return " ".join(text.split("\n")[0].split()).strip("\"'")[:300] or None
