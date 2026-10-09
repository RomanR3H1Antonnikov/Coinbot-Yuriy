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
    is_seen, save_rejected, get_decided_ids, purge_rejected,
)
from pipeline.keyword_filter import keyword_filter, build_matcher, lot_text
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
    is_direct = build_matcher(kw_direct)
    is_always = build_matcher(kw_always)

    since = get_last_run_at(src_id)
    logger.info("[%s] since=%s", src_id, since)

    lots = scraper.fetch_new_lots(since=since)
    logger.info("[%s] Fetched %d lots", src_id, len(lots))

    if not lots:
        set_last_run_at(src_id, datetime.now(timezone.utc).isoformat())
        return

    rejected: list[tuple[dict, str, str]] = []  # (lot, stage, reason) for the /rejected report

    # Pre-filter: годовики, копейки, до 1965, дешёвый buy-now, россыпи
    pre_rejected: list[tuple[dict, str]] = []
    lots = pre_filter(lots, kw_direct, kw_always, rejected=pre_rejected)
    # Only lots that carry a keyword count as "reviewed" in the report
    reviewed = {id(l) for l in keyword_filter([l for l, _ in pre_rejected], kw_all)}
    rejected += [(l, "rules", reason) for l, reason in pre_rejected if id(l) in reviewed]
    logger.info("[%s] After pre_filter: %d lots (%d rejected by rules)", src_id, len(lots), len(pre_rejected))

    candidates = keyword_filter(lots, kw_all)
    logger.info("[%s] After keyword_filter: %d candidates", src_id, len(candidates))

    # Do not pay again for lots we already alerted about or already rejected
    decided = get_decided_ids(src_id)
    fresh = [
        l for l in candidates
        if is_always(lot_text(l))
        or (l["lot_id"] not in decided and not is_seen(l["lot_id"], src_id))
    ]
    logger.info("[%s] New to review: %d (skipped %d already seen/decided)",
                src_id, len(fresh), len(candidates) - len(fresh))

    if src.get("skip_llm"):
        confirmed = fresh
        logger.info("[%s] LLM skipped (skip_llm=true)", src_id)
    else:
        direct_hits = [l for l in fresh if is_direct(lot_text(l))]
        direct_ids = {id(l) for l in direct_hits}
        llm_hits = [l for l in fresh if id(l) not in direct_ids]

        llm_confirmed = []
        for lot in llm_hits:
            verdict = llm_check(lot)
            if verdict:
                llm_confirmed.append(lot)
            elif verdict is False:
                rejected.append((lot, "llm", "ИИ: нет брака или разновидности"))
            # None = API failure: keep it out of the table so the next run retries it
        logger.info("[%s] Direct keywords: %d lots (no LLM); LLM confirmed %d/%d",
                    src_id, len(direct_hits), len(llm_confirmed), len(llm_hits))
        confirmed = direct_hits + llm_confirmed

    # Circulation (тиражные) coins are not wanted even with real defects.
    # Jubilee-category sources and "always" keywords skip the check.
    if confirmed and not src.get("jubilee_source"):
        kept = []
        for lot in confirmed:
            if is_always(lot_text(lot)) or is_jubilee(lot):
                kept.append(lot)
            else:
                rejected.append((lot, "jubilee", "обиходная монета (тиражка)"))
        logger.info("[%s] After jubilee check: %d/%d", src_id, len(kept), len(confirmed))
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
