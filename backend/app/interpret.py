"""One line saying how the SQL read the question (docs/guide.md section 3). It sees the question and the SQL, never the rows.

The point is to expose the assumptions a wrong-but-plausible answer hides: which deal stage was counted, which period,
how it was grouped. A failure here returns None: the answer is still useful without the line.
"""
import re

import httpx
import sqlglot
from sqlglot import exp

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
            "Omset berarti jumlah nilai deal dengan stage 'won'. "
            "Kolom created_date adalah tanggal deal dibuat; closed_date adalah tanggal deal ditutup (won atau lost). "
            "Tabel activities berisi aktivitas dan support_tickets berisi tiket. Sebut apa yang dihitung (deal, aktivitas, tiket) dan tanggal mana yang dipakai. "
            "Awali dengan 'Saya membaca ini sebagai:'."
        ),
        examples=[
            ("omset per bulan tahun lalu",
             "SELECT toStartOfMonth(d.closed_date) AS bulan, sum(d.value) AS total_omset FROM deals AS d FINAL WHERE d.stage = 'won' "
             "AND d.closed_date >= toStartOfYear(subtractYears(today(), 1)) AND d.closed_date < toStartOfYear(today()) GROUP BY bulan ORDER BY bulan",
             "Saya membaca ini sebagai: total nilai deal berstatus won (omset), dikelompokkan per bulan, untuk tahun kalender lalu."),
            ("nilai semua deal milik pelanggan Enterprise",
             "SELECT sum(d.value) AS total_nilai FROM deals AS d FINAL INNER JOIN customers AS c FINAL ON d.customer_id = c.customer_id "
             "WHERE c.segment = 'Enterprise'",
             "Saya membaca ini sebagai: jumlah nilai semua deal (won, lost, dan yang masih berjalan) milik pelanggan segmen Enterprise, tanpa batas waktu."),
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
            "Revenue means the sum of deal value with stage 'won'. "
            "Column created_date is when a deal was created; closed_date is when it was closed (won or lost). "
            "Table activities holds activities and support_tickets holds tickets. Say what is counted (deals, activities, tickets) and which date is used. "
            "Start with 'I read this as:'."
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


def consistent(line: str, sql: str) -> bool:
    """False when the line contradicts the SQL on what a small model mixes up. A missing line beats a wrong one: it said
    'ditutup' for created_date, and described a count of activities as 'jumlah sales'."""
    low, s = line.lower(), sql.lower()
    if re.search(r"ditutup|menutup|closed|\bclose\b", low) and "closed_date" not in s:
        return False
    if re.search(r"dibuat|created|\bcreate\b", low) and not re.search(r"created_(date|at)", s):
        return False
    for table, words in (("activities", r"aktivitas|activit"), ("support_tickets", r"tiket|ticket")):
        if (table in s) != bool(re.search(words, low)):  # names a table the SQL does not read, or hides the one it reads
            return False
    return True


# deals have two dates, so "last month" is ambiguous; the model often leaves out which one the SQL used
_DATE_BASIS = (("created_date", r"dibuat|created(?!_)", "tanggal deal dibuat", "deal creation date"),
               ("closed_date", r"ditutup|closed(?!_)|closing", "tanggal deal ditutup", "deal close date"))


def date_basis(line: str, sql: str, english: bool) -> str:
    """A suffix naming the deal date column the SQL uses, unless the line already says so. Derived from the SQL, so it cannot be wrong."""
    used = [(i, e) for col, seen, i, e in _DATE_BASIS if col in sql.lower() and not re.search(seen, line.lower())]
    if not used:
        return ""
    return f" (Date basis: {' and '.join(e for _, e in used)}.)" if english else f" (Dasar tanggal: {' dan '.join(i for i, _ in used)}.)"


PREVIEW_ROWS = 20  # the UI shows this many rows first


def _unbounded_ranking(sql: str) -> bool:
    try:
        tree = sqlglot.parse_one(sql, read="clickhouse")
    except sqlglot.errors.SqlglotError:
        return False
    order = tree.args.get("order") if isinstance(tree, exp.Select) else None
    return order is not None and tree.args.get("limit") is None and bool(order.expressions[0].args.get("desc"))


def shape_note(sql: str, n_rows: int, english: bool) -> str:
    """Caveats read from the SQL, never from the model:
    - a grouped ARRAY JOIN counts a row once per product or tag, so the groups add up to more than the real total
    - a long ranking (ORDER BY ... DESC, no LIMIT) came back whole: "customer with the largest deal" returned 291 rows"""
    notes = []
    if re.search(r"\barray\s+join\b", sql, re.I) and re.search(r"\bgroup\s+by\b", sql, re.I):
        notes.append("(A row with several products or tags is counted in each of them, so the groups can add up to more than the real total.)" if english
                     else "(Satu baris yang punya beberapa produk atau tag dihitung di setiap grupnya, jadi jumlah antar grup bisa melebihi total sebenarnya.)")
    if n_rows > PREVIEW_ROWS and _unbounded_ranking(sql):
        notes.append("(All matching rows are shown, sorted descending, not just the top ones.)" if english
                     else "(Semua baris yang cocok ditampilkan, diurutkan menurun, bukan hanya yang teratas.)")
    return " ".join(notes)


def raw(question: str, sql: str, model: str | None = None) -> str | None:
    try:
        r = httpx.post(
            f"{config.OLLAMA_URL}/api/chat",
            json={"model": model or config.SUMMARY_MODEL, "messages": _messages(question, sql), "stream": False,
                  "keep_alive": config.OLLAMA_KEEP_ALIVE, "options": {"temperature": 0, "num_predict": 100}},
            timeout=60,
        )
        r.raise_for_status()
        text = r.json()["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    return " ".join(text.split("\n")[0].split()).strip("\"'")[:300] or None


def interpret(question: str, sql: str, model: str | None = None) -> str | None:
    line = raw(question, sql, model)
    if not line or not consistent(line, sql):
        return None
    return line + date_basis(line, sql, is_english(question))
