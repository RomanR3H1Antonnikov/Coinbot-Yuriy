"""Daily Avito report, built from the run journal (no extra requests to Avito).

Runs on the PC that scrapes Avito. scraper_run.py calls maybe_send() after every Avito run;
it sends once a day, in the first run after 09:00 local time.

    python audit_avito.py --dry     # print the report for the last 24 h
"""
import argparse
import html
import logging
import os
from datetime import datetime

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = os.path.join(BASE_DIR, "logs", "avito_audit_date.txt")
SEND_AFTER_HOUR = 9
WINDOW_H = 24
logger = logging.getLogger("audit_avito")


def build_report() -> str:
    from db.database import db_conn
    from utils import run_journal

    recs = run_journal.read(WINDOW_H, "avito")
    if not recs:
        return f"📊 Сверка Авито за {WINDOW_H} ч\n\n⚠️ Ни одного прогона Авито за сутки. Проверьте, что ПК включён и задача Coinbot-Avito работает."

    empty = [r for r in recs if r["fetched"] == 0]
    ok = [r for r in recs if r["fetched"] > 0]
    fetched = sum(r["fetched"] for r in ok)
    with_photo = sum(r["with_photo"] for r in ok)
    rules = sum(r["rules_rejected"] for r in ok)
    hits = sum(r["hits"] for r in ok)
    expected = [i for r in recs for i in r["expected"]]

    with db_conn() as c:
        sent = {r[0] for r in c.execute("SELECT lot_id FROM found_lots WHERE source LIKE 'avito%'")}
        rejected = {r[0] for r in c.execute("SELECT lot_id FROM rejected_lots WHERE source LIKE 'avito%'")}
    lost = [i for i in expected if i not in sent and i not in rejected]

    queries = {r["src"] for r in recs}
    no_photo = fetched - with_photo
    lines = [
        f"Запросов выполнено: {len(ok)} из {len(recs)} (источников: {len(queries)})",
        f"Карточек просмотрено: {fetched}, без фото на странице: {no_photo}"
        + (f" ({no_photo * 100 // fetched}%)" if fetched else ""),
        f"Подошло по словам: {hits}, отсеяно правилами: {rules}, отправлено: {len(expected) - len(lost)}",
    ]
    problems = []
    if empty:
        names = ", ".join(sorted({r["src"].replace("avito_", "") for r in empty})[:8])
        problems.append(f"{len(empty)} запрос(ов) вернули 0 карточек (блок Авито или нет сети): {html.escape(names)}")
    if lost:
        problems.append(f"{len(lost)} лот(ов) подошли, но не отправлены и не отсеяны")
    gap = _longest_gap_h(recs)
    if gap > 3.5:
        problems.append(f"самый долгий перерыв между прогонами: {gap:.1f} ч (норма 2 ч)")
    verdict = "✅ Прогоны шли штатно, потерь нет." if not problems else "⚠️ " + "\n⚠️ ".join(problems)
    return f"📊 Сверка Авито за {WINDOW_H} ч\n\n" + "\n".join(lines) + "\n\n" + verdict


def _longest_gap_h(recs: list[dict]) -> float:
    times = sorted(datetime.fromisoformat(r["ts"]) for r in recs if r["fetched"] > 0)
    if len(times) < 2:
        return 0.0
    # records of one pass are minutes apart; a gap means no successful pass between them
    return max((b - a).total_seconds() / 3600 for a, b in zip(times, times[1:]))


def _send(text: str) -> None:
    from utils.notifier import BOT_TOKEN, _get_chat_ids
    for cid in _get_chat_ids():
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                          json={"chat_id": cid, "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=15)
        if not r.ok:
            logger.error("Telegram error [%s]: %s", cid, r.text[:200])


def maybe_send() -> None:
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    try:
        done = open(MARKER).read().strip() == today
    except OSError:
        done = False
    if done or now.hour < SEND_AFTER_HOUR:
        return
    try:
        _send(build_report())
        with open(MARKER, "w") as f:
            f.write(today)
    except Exception as e:  # never break the scraper run over a report
        logger.error("Avito audit report failed: %s", e)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.parse_args()
    print(build_report())
