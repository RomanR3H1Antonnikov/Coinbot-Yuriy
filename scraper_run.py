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

from db.database import init_db, get_last_run_at, set_last_run_at, save_found_lot
from pipeline.keyword_filter import keyword_filter
from pipeline.pre_filter import pre_filter
from pipeline.llm_checker import llm_check, get_llm_stats
from pipeline.jubilee_check import is_jubilee, get_jubilee_stats
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


def _run_source(src: dict, scraper, cfg: dict):
    """Common pipeline for any source."""
    keywords_direct = cfg.get("keywords_direct", [])
    keywords_all = cfg.get("keywords", [])
    direct_set = {k.lower() for k in keywords_direct}

    since = get_last_run_at(src["id"])
    logger.info("[%s] since=%s", src["id"], since)

    lots = scraper.fetch_new_lots(since=since)
    logger.info("[%s] Fetched %d lots", src["id"], len(lots))

    if not lots:
        set_last_run_at(src["id"], datetime.now(timezone.utc).isoformat())
        return

    # Pre-filter: drop годовики, копейки, pre-1965, cheap buy-now
    lots = pre_filter(lots, keywords_direct)
    logger.info("[%s] After pre_filter: %d lots", src["id"], len(lots))

    # Keyword filter (all keywords)
    candidates = keyword_filter(lots, keywords_all)
    logger.info("[%s] After keyword_filter: %d candidates", src["id"], len(candidates))

    if src.get("skip_llm"):
        confirmed = candidates
        logger.info("[%s] LLM skipped (skip_llm=true)", src["id"])
    else:
        # Split: direct keywords → skip LLM; rest → LLM check
        def _text(lot):
            return (lot.get("title", "") + " " + (lot.get("description") or "")).lower()

        direct_hits = [l for l in candidates if any(k in _text(l) for k in direct_set)]
        llm_hits = [l for l in candidates if l not in direct_hits]

        if direct_hits:
            logger.info("[%s] Direct keywords: %d lots (no LLM)", src["id"], len(direct_hits))
        if llm_hits:
            llm_confirmed = [l for l in llm_hits if llm_check(l)]
            logger.info("[%s] After LLM: %d/%d confirmed", src["id"], len(llm_confirmed), len(llm_hits))
        else:
            llm_confirmed = []

        confirmed = direct_hits + llm_confirmed

    # Circulation (тиражные) coins are not wanted even with real defects.
    # Sources that are already the jubilee category skip the check.
    if confirmed and not src.get("jubilee_source"):
        before = len(confirmed)
        confirmed = [l for l in confirmed if is_jubilee(l)]
        logger.info("[%s] After jubilee check: %d/%d", src["id"], len(confirmed), before)

    new_finds = dedup(confirmed)
    logger.info("[%s] After dedup: %d new finds", src["id"], len(new_finds))

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


def run_meshok(cfg: dict):
    for src in cfg.get("meshok_sources", []):
        scraper = MeshokScraper(src["id"], src["label"], src["url"])
        _run_source(src, scraper, cfg)
    _log_llm_stats()


def run_auction(cfg: dict):
    for src in cfg.get("auction_sources", []):
        scraper = AuctionScraper(src["id"], src["label"], src["url"])
        _run_source(src, scraper, cfg)
    _log_llm_stats()


def run_avito(cfg: dict):
    for src in cfg.get("avito_sources", []):
        scraper = AvitoScraper(src["id"], src["label"], src["url"])
        _run_source(src, scraper, cfg)
    _log_llm_stats()


def _log_llm_stats():
    stats = get_llm_stats()
    logger.info("LLM stats: calls=%d tokens=%d", stats["calls"], stats["tokens"])
    jstats = get_jubilee_stats()
    logger.info("Jubilee stats: calls=%d tokens=%d", jstats["calls"], jstats["tokens"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["meshok", "auction", "avito", "all"], default="all")
    args = parser.parse_args()

    init_db()
    cfg = load_config()

    if args.source in ("meshok", "all"):
        run_meshok(cfg)
    if args.source in ("auction", "all"):
        run_auction(cfg)
    if args.source in ("avito", "all"):
        run_avito(cfg)


if __name__ == "__main__":
    main()
