#!/usr/bin/env python3
"""
Entry point for cron: python scraper_run.py --source meshok|auction|all
"""
import argparse
import logging
import os
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

load_dotenv()

from db.database import init_db, get_last_run_at, set_last_run_at, save_found_lot
from pipeline.keyword_filter import keyword_filter
from pipeline.llm_checker import llm_check, get_llm_stats
from pipeline.dedup import dedup
from scrapers.meshok import MeshokScraper
from scrapers.auction import AuctionScraper
from utils.notifier import send_alert
from utils.logger import setup_logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
setup_logger("root", os.path.join(BASE_DIR, "logs", "scraper.log"))
logger = logging.getLogger(__name__)


def load_config() -> dict:
    with open(os.path.join(BASE_DIR, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_meshok(cfg: dict):
    keywords = cfg["keywords"]
    for src in cfg.get("meshok_sources", []):
        scraper = MeshokScraper(src["id"], src["label"], src["url"])
        since = get_last_run_at(src["id"])
        logger.info("Meshok [%s] since=%s", src["id"], since)

        lots = scraper.fetch_new_lots(since=since)
        logger.info("Fetched %d lots from %s", len(lots), src["id"])

        candidates = keyword_filter(lots, keywords)
        logger.info("After keyword_filter: %d candidates", len(candidates))

        confirmed = [lot for lot in candidates if llm_check(lot)]
        logger.info("After LLM: %d confirmed", len(confirmed))

        new_finds = dedup(confirmed)
        logger.info("After dedup: %d new finds", len(new_finds))

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

        set_last_run_at(src["id"], datetime.now(timezone.utc).isoformat())

    stats = get_llm_stats()
    logger.info("LLM stats: calls=%d tokens=%d", stats["calls"], stats["tokens"])


def run_auction(cfg: dict):
    keywords = cfg["keywords"]
    for src in cfg.get("auction_sources", []):
        scraper = AuctionScraper(src["id"], src["label"], src["url"])
        since = get_last_run_at(src["id"])
        logger.info("Auction [%s] since=%s", src["id"], since)

        lots = scraper.fetch_new_lots(since=since)
        logger.info("Fetched %d lots from %s", len(lots), src["id"])

        candidates = keyword_filter(lots, keywords)
        logger.info("After keyword_filter: %d candidates", len(candidates))

        confirmed = [lot for lot in candidates if llm_check(lot)]
        logger.info("After LLM: %d confirmed", len(confirmed))

        new_finds = dedup(confirmed)
        logger.info("After dedup: %d new finds", len(new_finds))

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

        set_last_run_at(src["id"], datetime.now(timezone.utc).isoformat())

    stats = get_llm_stats()
    logger.info("LLM stats: calls=%d tokens=%d", stats["calls"], stats["tokens"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["meshok", "auction", "all"], default="all")
    args = parser.parse_args()

    init_db()
    cfg = load_config()

    if args.source in ("meshok", "all"):
        run_meshok(cfg)

    if args.source in ("auction", "all"):
        run_auction(cfg)


if __name__ == "__main__":
    main()
