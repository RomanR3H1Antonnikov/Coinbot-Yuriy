"""Avito runs on the owner's PC with its own local DB. The bot (/logs, /list, /rejected)
reads the VPS DB, so finds and rejects are pushed there over ssh (best effort, retried
from a pending file on the next run)."""
import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

PENDING = Path(__file__).resolve().parent.parent / "logs" / "vps_sync_pending.jsonl"

_REMOTE = (
    "cd /root/Coinbot-Yuriy && .venv/bin/python -c \""
    "import sys,json;from db.database import init_db,save_found_lot,save_rejected,mark_seen;"
    "init_db();d=json.load(sys.stdin);"
    "[(save_found_lot(l),mark_seen(l['lot_id'],l['source'])) for l in d['found']];"
    "save_rejected([(l,s,r) for l,s,r in d['rejected']])\""
)


def _enabled() -> bool:
    return bool(os.getenv("VPS_SSH"))


def _push(payload: dict) -> bool:
    key = os.path.expanduser(os.getenv("VPS_SSH_KEY", "~/.ssh/gulaistore"))
    cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20",
           os.environ["VPS_SSH"], _REMOTE]
    try:
        r = subprocess.run(cmd, input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           capture_output=True, timeout=90)
    except Exception as e:
        logger.warning("VPS sync failed: %s", e)
        return False
    if r.returncode != 0:
        logger.warning("VPS sync failed: %s", r.stderr.decode("utf-8", "replace")[-300:])
        return False
    return True


def push_avito_stats(snapshot: dict) -> bool:
    """Daily report is built on the VPS; this is the Avito part of it (read by audit_run.py)."""
    if not _enabled():
        return False
    key = os.path.expanduser(os.getenv("VPS_SSH_KEY", "~/.ssh/gulaistore"))
    cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20",
           os.environ["VPS_SSH"], "cat > /root/Coinbot-Yuriy/logs/avito_stats.json"]
    try:
        r = subprocess.run(cmd, input=json.dumps(snapshot, ensure_ascii=False).encode("utf-8"),
                           capture_output=True, timeout=60)
    except Exception as e:
        logger.warning("Avito stats push failed: %s", e)
        return False
    if r.returncode != 0:
        logger.warning("Avito stats push failed: %s", r.stderr.decode("utf-8", "replace")[-300:])
    return r.returncode == 0


def sync_to_vps(found: list[dict], rejected: list[tuple[dict, str, str]]):
    if not _enabled():
        return
    items = [{"found": found, "rejected": [[l, s, r] for l, s, r in rejected]}]
    if PENDING.exists():
        for line in PENDING.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))
    if not any(i["found"] or i["rejected"] for i in items):
        return
    merged = {"found": [x for i in items for x in i["found"]],
              "rejected": [x for i in items for x in i["rejected"]]}
    if _push(merged):
        PENDING.unlink(missing_ok=True)
    else:
        PENDING.parent.mkdir(exist_ok=True)
        PENDING.write_text(json.dumps(merged, ensure_ascii=False) + "\n", encoding="utf-8")
