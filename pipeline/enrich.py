import logging
import time

from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

logger = logging.getLogger(__name__)

MAX_ENRICH_PER_RUN = 40
_session: cf_requests.Session | None = None


def _get_session() -> cf_requests.Session:
    global _session
    if _session is None:
        _session = cf_requests.Session(impersonate="chrome124")
        _session.headers.update({"Accept-Language": "ru-RU,ru;q=0.9"})
    return _session


def fetch_description(url: str) -> str:
    """Seller's lot description from <meta name="description"> (auction.ru).
    Returns "" when the page has none (Meshok serves a bare SPA shell) or on any error."""
    try:
        resp = _get_session().get(url, timeout=20)
        resp.raise_for_status()
        meta = BeautifulSoup(resp.text, "lxml").find("meta", attrs={"name": "description"})
        return (meta.get("content") or "").strip() if meta else ""
    except Exception as e:
        logger.warning("Could not fetch description for %s: %s", url, e)
        return ""


def enrich_with_description(lots: list[dict]) -> None:
    """Append the page description to lot["description"] in place, once per lot."""
    done = 0
    for lot in lots:
        # Only auction.ru pages carry the description in HTML; Meshok/Avito would be wasted requests
        if lot.get("_enriched") or "auction.ru" not in (lot.get("url") or ""):
            continue
        if done >= MAX_ENRICH_PER_RUN:
            logger.info("Description enrichment capped at %d lots", MAX_ENRICH_PER_RUN)
            break
        lot["_enriched"] = True
        text = fetch_description(lot["url"])
        done += 1
        if text and text.lower() not in (lot.get("description") or "").lower():
            lot["description"] = ((lot.get("description") or "") + " " + text).strip()
        time.sleep(1)
