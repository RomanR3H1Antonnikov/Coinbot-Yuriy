"""Daily completeness audit for Meshok: re-read everything the site published in the last
24h (via the same API the scraper uses), run the same rules and keywords, and compare with
what was actually sent / rejected. Any keyword lot that is in neither place is reported.

    python audit_run.py            # send the report to Telegram
    python audit_run.py --dry      # print only
"""
import argparse
import html
import logging
import os
from datetime import datetime, timedelta, timezone

import requests
import yaml
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from db.database import init_db, db_conn
from pipeline.keyword_filter import keyword_filter
from pipeline.pre_filter import pre_filter
from scrapers.meshok import MeshokScraper
from scrapers.auction import AuctionScraper
from scraper_run import _keyword_sets
from utils.notifier import BOT_TOKEN, _get_chat_ids

logger = logging.getLogger("audit")
GRACE_H = 1   # newest lots may not have been through a cron run yet
WINDOW_H = 24


def audit(cfg: dict) -> tuple[str, int]:
    kw_all, kw_direct, kw_always = _keyword_sets(cfg)
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=WINDOW_H + GRACE_H)).isoformat()
    edge = now - timedelta(hours=GRACE_H)

    with db_conn() as c:
        sent = {r[0] for r in c.execute("SELECT lot_id FROM found_lots")}
        rejected = {r[0] for r in c.execute("SELECT lot_id FROM rejected_lots")}

    lines, missing_all, total_missing = [], [], 0
    for src in cfg.get("meshok_sources", []):
        lots = MeshokScraper(src["id"], src["label"], src["url"]).fetch_new_lots(since)
        lots = [l for l in lots if datetime.fromisoformat(l["published_at"]) <= edge
                and datetime.fromisoformat(l["published_at"]) >= now - timedelta(hours=WINDOW_H + GRACE_H)]
        rules_rej: list = []
        kept = pre_filter(lots, kw_direct, kw_always, rejected=rules_rej)
        hits = keyword_filter(kept, kw_all)
        n_sent = sum(1 for l in hits if l["lot_id"] in sent)
        n_rej = sum(1 for l in hits if l["lot_id"] not in sent and l["lot_id"] in rejected)
        miss = [l for l in hits if l["lot_id"] not in sent and l["lot_id"] not in rejected]
        total_missing += len(miss)
        missing_all += [(src["label"], l) for l in miss]
        lines.append(f"{html.escape(src['label'])}: на сайте {len(lots)}, по словам {len(hits) + sum(1 for l, _ in rules_rej if keyword_filter([l], kw_all))}, "
                     f"прислано {n_sent}, отсеяно правилами {len(rules_rej)}, не дошло {len(miss)}")

    a_lines, a_missing = audit_auction(cfg, kw_all, kw_direct, kw_always, sent, rejected)
    total_missing += len(a_missing)
    missing_all += a_missing

    head = (f"📊 Сверка за {WINDOW_H} ч\n\n<b>Мешок</b>\n" + "\n".join(lines)
            + "\n\n<b>Аукцион</b> (свежие лоты каждого раздела, по заголовкам)\n" + "\n".join(a_lines) + "\n\n"
            + ("✅ Всё, что подошло по словам, дошло или отсеяно правилами." if not total_missing
               else f"⚠️ Не дошло лотов: {total_missing}"))
    for label, l in missing_all[:10]:
        head += f"\n• {html.escape(l['title'][:70])} — {l['url']}"
    return head, total_missing


def audit_auction(cfg, kw_all, kw_direct, kw_always, sent, rejected):
    """Auction listings have no dates, so the control is the newest ~180 lots of each section
    right now (newest first). Lots at the very top that the cron has not seen yet are just
    too fresh and are skipped; any later lot that matches a keyword but was neither sent nor
    rejected is reported."""
    lines, missing = [], []
    for src in cfg.get("auction_sources", []):
        lots = AuctionScraper(src["id"], src["label"], src["url"]).fetch_new_lots()
        if not lots:
            lines.append(f"{html.escape(src['label'])}: ⚠️ сайт не отдал лотов")
            continue
        with db_conn() as c:
            seen = {r[0] for r in c.execute("SELECT lot_id FROM seen_lots WHERE source=?", (src["id"],))}
        rules_rej: list = []
        kept = pre_filter(lots, kw_direct, kw_always, rejected=rules_rej)
        fresh = 0
        while fresh < len(kept) and kept[fresh]["lot_id"] not in seen:
            fresh += 1
        checked = kept[fresh:]
        hits = keyword_filter(checked, kw_all)
        n_sent = sum(1 for l in hits if l["lot_id"] in sent)
        n_rej = sum(1 for l in hits if l["lot_id"] not in sent and l["lot_id"] in rejected)
        miss = [l for l in hits if l["lot_id"] not in sent and l["lot_id"] not in rejected]
        missing += [(src["label"], l) for l in miss]
        warn = " ⚠️ бот давно не обрабатывал раздел" if fresh > len(kept) * 0.4 and len(kept) >= 30 else ""
        lines.append(f"{html.escape(src['label'])}: на сайте {len(lots)}, по словам {len(hits)}, "
                     f"прислано {n_sent}, отсеяно правилами {n_rej}, не дошло {len(miss)}{warn}")
    return lines, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    init_db()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    text, missing = audit(cfg)
    print(text)
    logger.info("audit done, missing=%d", missing)
    if args.dry:
        return
    for cid in _get_chat_ids():
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                          json={"chat_id": cid, "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=15)
        if not r.ok:
            logger.error("Telegram error [%s]: %s", cid, r.text[:200])


if __name__ == "__main__":
    main()
