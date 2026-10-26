"""Question -> SQL with the Ollama model, then validate and execute, repairing failures by sending the error back."""
import re
import time

import httpx

from app import config, executor, guards, interpret, meta, shaping, validator
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
    try:
        question = guards.check(question)
    except guards.Refused as e:
        # a missing concept is a data limit, not a rejected input, so say so
        return AskResponse(error=UNANSWERABLE if e.reason == "absent" else guards.REFUSED, refusal=e.reason)
    if meta.is_meta(question):
        return meta.answer(question)
    timing = {}

    def timed(stage, fn, *args):
        t0 = time.perf_counter()
        try:
            return fn(*args)
        finally:
            timing[stage] = round(timing.get(stage, 0) + time.perf_counter() - t0, 1)

    messages = [{"role": "user", "content": question}]
    sql = timed("generate", generate, messages)
    attempts, trace = 0, []
    while True:
        try:
            columns, rows = timed("execute", lambda: executor.run(validator.validate(sql)))
            rows = shaping.mask(rows)
            line = timed("interpret", interpret.interpret, question, sql)
            return AskResponse(sql=sql, interpretation=line, columns=columns, rows=rows, chart=shaping.pick_chart(columns, rows),
                               attempts=attempts, trace=trace, timing=timing)
        except validator.Unanswerable as e:
            trace.append({"sql": sql, "error": str(e)})
            return AskResponse(sql=sql, error=UNANSWERABLE, attempts=attempts, trace=trace, timing=timing)
        except (validator.Invalid, executor.ExecError) as e:
            reason = str(e)
            trace.append({"sql": sql, "error": reason})
        if attempts >= config.MAX_RETRIES:
            return AskResponse(sql=sql, error=f"Query gagal setelah {attempts} perbaikan: {reason}", attempts=attempts, trace=trace, timing=timing)
        attempts += 1
        messages += [{"role": "assistant", "content": sql},
                     {"role": "user", "content": f"SQL itu gagal: {reason}\nPerbaiki SQL-nya. Output only SQL."}]
        sql = timed("generate", generate, messages)
