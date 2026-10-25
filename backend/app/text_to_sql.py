"""Question -> SQL with the Ollama model, then validate and execute, repairing failures by sending the error back."""
import re

import httpx

from app import config, executor, shaping, validator
from app.schemas import AskResponse

UNANSWERABLE = "Pertanyaan ini tidak bisa dijawab dari data yang tersedia."


def clean_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip().rstrip(";")


def generate(messages: list[dict]) -> str:
    """One model call. Only the conversation is sent: the system prompt lives in the Modelfile."""
    r = httpx.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={"model": config.SQL_MODEL, "messages": messages, "stream": False, "options": {"temperature": 0}},
        timeout=300,
    )
    r.raise_for_status()
    return clean_sql(r.json()["message"]["content"])


def ask(question: str) -> AskResponse:
    """Retries only repair SQL that fails; they cannot catch SQL that runs and is wrong (docs/guide.md section 3)."""
    messages = [{"role": "user", "content": question}]
    sql = generate(messages)
    attempts = 0
    while True:
        try:
            columns, rows = executor.run(validator.validate(sql))
            rows = shaping.mask(rows)
            return AskResponse(sql=sql, columns=columns, rows=rows, chart=shaping.pick_chart(columns, rows), attempts=attempts)
        except validator.Unanswerable:
            return AskResponse(sql=sql, error=UNANSWERABLE, attempts=attempts)
        except (validator.Invalid, executor.ExecError) as e:
            reason = str(e)
        if attempts >= config.MAX_RETRIES:
            return AskResponse(sql=sql, error=f"Query gagal setelah {attempts} perbaikan: {reason}", attempts=attempts)
        attempts += 1
        messages += [{"role": "assistant", "content": sql},
                     {"role": "user", "content": f"SQL itu gagal: {reason}\nPerbaiki SQL-nya. Output only SQL."}]
        sql = generate(messages)
