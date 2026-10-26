"""One JSON line per source per run (logs/run_journal.jsonl): what was fetched, how many cards
had a photo, how many lots were expected to be sent. The daily Avito report is built from it,
because Avito cannot be re-read for a control pass without risking a block."""
import json
import os
from datetime import datetime, timedelta, timezone

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "run_journal.jsonl")
KEEP_DAYS = 3


def write(src_id: str, **fields) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "src": src_id, **fields}
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if os.path.getsize(PATH) > 2_000_000:
            _trim()
    except OSError:
        pass


def _trim() -> None:
    keep = read(KEEP_DAYS * 24)
    with open(PATH, "w", encoding="utf-8") as f:
        for rec in keep:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read(hours: int, prefix: str = "") -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    try:
        with open(PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec["src"].startswith(prefix) and datetime.fromisoformat(rec["ts"]) >= cutoff:
                    out.append(rec)
    except OSError:
        pass
    return out
