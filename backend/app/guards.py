"""Input checks before the model is called (docs/guide.md rule 3). Deterministic and cheap; no model.

check() returns the cleaned question or raises Refused. The user sees one generic REFUSED text whatever rule fired (except "absent",
which says the data cannot answer it); the reason (noise, injection, write, offtopic, absent) goes only to the query log, so an
attacker learns nothing about what was matched.
"""
import re
import unicodedata

REFUSED = "Pertanyaan ini tidak bisa diproses. Ajukan pertanyaan tentang data CRM, misalnya omset, deal, pelanggan, atau tiket."


class Refused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ponytail: vocabulary rules, tuned on data/adversarial.jsonl (267 gold questions are the false-positive check). They do not
# generalize to every phrasing; the validator and the read-only DB user are the real safety net. Measure with
# eval_adversarial.py before adding words, and consider a small classifier only if a whole class keeps getting through.
_LEAD = r"^(?:(?:tolong|coba|silakan|mohon|please|bisa)\s+)*"
RULES = [
    ("injection", re.compile(
        r"(?:abaikan|lupakan|ignore|disregard|forget)\b.{0,40}\b(?:instruksi|aturan|perintah|instructions?|rules?|previous|sebelumnya)"
        r"|system prompt|prompt sistem|instruksi (?:awal|sistem)|developer mode|jailbreak|kamu sekarang|sekarang kamu|you are now"
        r"|^\W*#{2,}\s*system|\bsystem\s*:"
        r"|\bsystem\.\w+|information_schema|\b(?:url|file|s3|remote|mysql|postgresql)\s*\("
        r"|;\s*(?:drop|delete|insert|update|alter|truncate|create|grant|select|show|set)\b")),
    ("write", re.compile(
        _LEAD + r"(?:hapus|ubah|ganti|update|tambah(?:kan)?|masukkan|kosongkan|truncate|drop|delete|remove|insert|modify|rename|grant|revoke|alter)\b"
        r"|" + _LEAD + r"(?:buat|create)(?:kan)?\s+(?:user|pengguna|akun|role|tabel|table|database)"
        r"|\b(?:drop|alter|truncate)\s+(?:table|database|user)\b|\bdelete\s+from\b|\binsert\s+into\b")),
    # Concepts the CRM schema has no column for. The model otherwise swaps in something else and answers wrongly
    # ("gaji tiap sales dengan win rate teratas" returned an invented win rate and no salary).
    ("absent", re.compile(
        r"\b(?:gaji|upah|salary|margin|laba|profit|alamat|address|telepon|phone|stok|stock|pembayaran|payment|invoice|faktur|tagihan"
        r"|biaya|nps|survei|karyawan|employees?)\b")),
    ("offtopic", re.compile(
        r"\b(?:terjemah\w*|translate|puisi|pantun|lelucon|joke|resep|cuaca|kurs|python|kode program|apa kabar)\b"
        r"|\bsiapa (?:kamu|anda)\b|\bkamu siapa\b|\bwho are you\b|\bmodel apa\b|^\W*(?:halo|hai|hi|hello)\W*$")),
]


def check(question: str) -> str:
    """Return the cleaned question (what the model should see) or raise Refused."""
    q = unicodedata.normalize("NFKC", question)
    q = "".join(ch for ch in q if ch in "\n\t " or unicodedata.category(ch) not in ("Cc", "Cf"))  # control and zero-width chars
    q = " ".join(q.split())
    if sum(ch.isalpha() for ch in q) < 3:  # "???", "1234", emoji only
        raise Refused("noise")
    low = q.lower()
    for reason, rx in RULES:
        if rx.search(low):
            raise Refused(reason)
    return q
