#!/usr/bin/env python3
"""
Entry point for cron: python scraper_run.py --source meshok|auction|avito|all
"""
import argparse
import logging
import os
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

load_dotenv()

from db.database import (
    init_db, get_last_run_at, set_last_run_at, save_found_lot,
    is_seen, mark_seen, save_rejected, purge_rejected, title_already_found,
)
from pipeline.keyword_filter import keyword_filter
from pipeline.pre_filter import pre_filter
from pipeline.enrich import enrich_with_description
from pipeline.dedup import dedup
from scrapers.meshok import MeshokScraper
from scrapers.auction import AuctionScraper
from scrapers.avito import AvitoScraper
from utils.notifier import send_alert
from utils.logger import setup_logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
setup_logger("root", os.path.join(BASE_DIR, "logs", "scraper.log"))
logger = logging.getLogger(__name__)


def load_config() -> dict:
    with open(os.path.join(BASE_DIR, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _keyword_sets(cfg: dict) -> tuple[list[str], list[str], list[str]]:
    """(all, direct, always). Direct also contains always; all contains every list."""
    always = cfg.get("keywords_always", [])
    direct = list(dict.fromkeys(cfg.get("keywords_direct", []) + always))
    every = list(dict.fromkeys(cfg.get("keywords", []) + direct + cfg.get("keywords_llm", [])))
    return every, direct, always


def _run_source(src: dict, scraper, cfg: dict):
    """Common pipeline for any source."""
    src_id = src["id"]
    kw_all, kw_direct, kw_always = _keyword_sets(cfg)

    since = get_last_run_at(src_id)
    logger.info("[%s] since=%s", src_id, since)

    lots = scraper.fetch_new_lots(since=since)
    logger.info("[%s] Fetched %d lots", src_id, len(lots))

    if not lots:
        set_last_run_at(src_id, datetime.now(timezone.utc).isoformat())
        return

    rejected: list[tuple[dict, str, str]] = []  # (lot, stage, reason) for the /rejected report

    # Since 10.10 there is no AI: text rules (россыпь, годовик, копейки, до 1965, дешёвый buy-now)
    # plus repeats are the only filters; every other keyword hit is sent.
    pre_rejected: list[tuple[dict, str]] = []
    lots = pre_filter(lots, kw_direct, kw_always, rejected=pre_rejected)
    # Only lots that carry a keyword count as "reviewed" in the report
    reviewed = {id(l) for l in keyword_filter([l for l, _ in pre_rejected], kw_all)}
    rejected += [(l, "rules", reason) for l, reason in pre_rejected if id(l) in reviewed]
    logger.info("[%s] After pre_filter: %d lots (%d rejected by rules)", src_id, len(lots), len(pre_rejected))

    unseen = [l for l in lots if not is_seen(l["lot_id"], src_id)]
    confirmed = keyword_filter(unseen, kw_all)

    # Title has no keyword: the defect may be named only in the lot description (auction.ru).
    # Checked lots are remembered as seen so their pages are not fetched again every run.
    matched_ids = {id(l) for l in confirmed}
    rest = [l for l in unseen if id(l) not in matched_ids]
    enrich_with_description(rest)
    for lot in rest:
        if lot.get("_enriched"):
            if keyword_filter([lot], kw_all):
                confirmed.append(lot)
            else:
                mark_seen(lot["lot_id"], src_id)
    logger.info("[%s] Keyword hits: %d (of %d unseen)", src_id, len(confirmed), len(unseen))

    # Same title already sent = seller re-listed the lot
    kept = []
    for lot in confirmed:
        if title_already_found(lot.get("title", "")):
            rejected.append((lot, "rules", "повтор (уже присылали)"))
            mark_seen(lot["lot_id"], src_id)
        else:
            kept.append(lot)
    confirmed = kept

    save_rejected(rejected)

    new_finds = dedup(confirmed)
    logger.info("[%s] After dedup: %d new finds", src_id, len(new_finds))

    for lot in new_finds:
        send_alert(lot)
        save_found_lot({
            "lot_id": lot["lot_id"],
            "source": lot["source"],
            "url": lot["url"],
            "title": lot.get("title"),
            "price": lot.get("price"),
            "photo_url": lot.get("photo_url"),
            "summary": None,
        })

    set_last_run_at(src_id, datetime.now(timezone.utc).isoformat())


def run_meshok(cfg: dict):
    for src in cfg.get("meshok_sources", []):
        scraper = MeshokScraper(src["id"], src["label"], src["url"])
        _run_source(src, scraper, cfg)


def run_auction(cfg: dict):
    for src in cfg.get("auction_sources", []):
        scraper = AuctionScraper(src["id"], src["label"], src["url"])
        _run_source(src, scraper, cfg)


def run_avito(cfg: dict):
    for src in cfg.get("avito_sources", []):
        scraper = AvitoScraper(src["id"], src["label"], src["url"])
        _run_source(src, scraper, cfg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["meshok", "auction", "avito", "all"], default="all")
    args = parser.parse_args()

    init_db()
    purge_rejected(30)
    cfg = load_config()

    if args.source in ("meshok", "all"):
        run_meshok(cfg)
    if args.source in ("auction", "all"):
        run_auction(cfg)
    if args.source in ("avito", "all"):
        run_avito(cfg)


if __name__ == "__main__":
    main()
