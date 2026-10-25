"""Run validated SQL in ClickHouse as the restricted `app` user. Read-only and limits are enforced by the user itself."""
import re

import httpx

from app import config


class ExecError(RuntimeError):
    """ClickHouse rejected or failed the query. The message is short enough to send back to the model."""


def run(sql: str) -> tuple[list[str], list[list]]:
    """Return (column names, rows). Connection problems raise httpx.HTTPError, not ExecError: retrying SQL cannot fix them."""
    r = httpx.post(
        config.CH_URL,
        params={"database": "crm", "default_format": "JSONCompact"},
        content=sql.encode(),
        headers={"X-ClickHouse-User": config.CH_USER, "X-ClickHouse-Key": config.CH_PASSWORD},
        timeout=30,
    )
    if r.status_code != 200:
        m = re.search(r"Code: \d+\. DB::Exception: [^\n\"]*", r.text)
        raise ExecError((m.group(0) if m else r.text.strip())[:300])
    out = r.json()
    return [c["name"] for c in out["meta"]], out["data"]
