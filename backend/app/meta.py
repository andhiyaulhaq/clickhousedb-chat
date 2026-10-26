"""Static answer to "what can I ask?" questions. No model call, so nothing to hallucinate: the model otherwise queries
information_schema, which the validator (rightly) refuses."""
import re

from app.interpret import is_english
from app.schemas import AskResponse

META = re.compile(
    r"apa saja (?:yang )?(?:bisa|boleh|dapat) (?:aku|saya|kita)?\s*(?:tanya|tanyakan)|data apa saja|data apa yang (?:ada|tersedia)"
    r"|apa (?:yang )?(?:bisa|dapat) (?:kamu|anda) (?:lakukan|jawab)|contoh pertanyaan|tabel apa|apa isi database"
    r"|what can i ask|what (?:data|tables) (?:do you have|are there|is there|are available)|what can you (?:do|answer)|example questions"
    r"|^\W*(?:help|bantuan)\W*$")

# every example is a gold question the pipeline answers
ID = ("Saya bisa menjawab pertanyaan tentang data CRM berikut. Contoh pertanyaan yang bisa Anda coba:", ["Data", "Contoh pertanyaan"], [
    ["Pelanggan", "jumlah pelanggan per segmen"],
    ["Deal dan omset", "omset per bulan tahun lalu"],
    ["Sales", "siapa 5 sales dengan omset tertinggi dari customer Enterprise tahun ini"],
    ["Aktivitas (call, email, meeting, demo)", "total durasi aktivitas per tipe"],
    ["Tiket support", "jumlah tiket urgent per minggu selama 3 bulan terakhir"],
    ["Gabungan", "omset customer Enterprise per kuartal untuk tahun lalu"],
])
EN = ("I can answer questions about this CRM data. Example questions to try:", ["Data", "Example question"], [
    ["Customers", "how many customers per segment?"],
    ["Deals and revenue", "revenue per month last year"],
    ["Sales reps", "who are the top 5 sales reps by revenue from Enterprise customers this year"],
    ["Activities (call, email, meeting, demo)", "total activity duration per type"],
    ["Support tickets", "number of urgent tickets per week over the last 3 months"],
    ["Combined", "Enterprise customer revenue per quarter for last year"],
])


def is_meta(question: str) -> bool:
    return META.search(question.lower()) is not None


def answer(question: str) -> AskResponse:
    summary, columns, rows = EN if is_english(question) else ID
    return AskResponse(summary=summary, columns=columns, rows=rows)
