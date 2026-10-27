"""Avito figures for the daily report, built from the run journal (no extra requests to Avito).

Avito runs on the PC, the daily report is sent from the VPS, so after every Avito run the PC
pushes a small snapshot (logs/avito_stats.json) to the VPS; audit_run.py puts it in the common
report and warns if the snapshot is stale (PC off, task not running).

    python audit_avito.py     # print the snapshot for the last 24 h
"""
import json
import logging
import os
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WINDOW_H = 24
logger = logging.getLogger("audit_avito")


def collect() -> dict:
    from db.database import db_conn, count_viewed
    from utils import run_journal
    from utils.report_stats import photo_counts

    snap = {"ts": datetime.now(timezone.utc).isoformat(), "viewed": count_viewed("avito", WINDOW_H),
            "photo": photo_counts("avito", WINDOW_H), "lines": [], "problems": []}
    recs = run_journal.read(WINDOW_H, "avito")
    if not recs:
        snap["problems"].append("за сутки не было ни одного прогона Авито (ПК выключен или задача Coinbot-Avito не работает)")
        return snap

    empty = [r for r in recs if r["fetched"] == 0]
    ok = [r for r in recs if r["fetched"] > 0]
    fetched = sum(r["fetched"] for r in ok)
    no_photo = fetched - sum(r["with_photo"] for r in ok)
    hits = sum(r["hits"] for r in ok)
    rules = sum(r["rules_rejected"] for r in ok)
    expected = [i for r in recs for i in r["expected"]]

    with db_conn() as c:
        sent = {r[0] for r in c.execute("SELECT lot_id FROM found_lots WHERE source LIKE 'avito%'")}
        rejected = {r[0] for r in c.execute("SELECT lot_id FROM rejected_lots WHERE source LIKE 'avito%'")}
    lost = [i for i in expected if i not in sent and i not in rejected]

    snap["lines"] = [
        f"запросов выполнено {len(ok)} из {len(recs)}, карточек просмотрено {fetched}"
        + (f", без фото на странице {no_photo} ({no_photo * 100 // fetched}%)" if fetched else ""),
        f"подошло по словам {hits}, отсеяно правилами {rules}, отправлено {len(expected) - len(lost)}",
    ]
    if empty:
        names = ", ".join(sorted({r["src"].replace("avito_", "") for r in empty})[:8])
        snap["problems"].append(f"{len(empty)} запрос(ов) вернули 0 карточек (блок Авито или нет сети): {names}")
    if lost:
        snap["problems"].append(f"{len(lost)} лот(ов) подошли, но не отправлены и не отсеяны")
    gap = _longest_gap_h(ok)
    if gap > 3.5:
        snap["problems"].append(f"самый долгий перерыв между прогонами {gap:.1f} ч (норма 2 ч)")
    if snap["viewed"] == 0:
        snap["problems"].append("за сутки не просмотрено ни одного нового лота")
    return snap


def _longest_gap_h(recs: list[dict]) -> float:
    times = sorted(datetime.fromisoformat(r["ts"]) for r in recs)
    if len(times) < 2:
        return 0.0
    return max((b - a).total_seconds() / 3600 for a, b in zip(times, times[1:]))


def push_snapshot() -> None:
    """Called at the end of every Avito run; never breaks the run."""
    try:
        from utils.vps_sync import push_avito_stats
        push_avito_stats(collect())
    except Exception as e:
        logger.error("Avito stats snapshot failed: %s", e)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
