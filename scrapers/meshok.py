import time
import re
import logging

from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://meshok.net"


def _make_session() -> cf_requests.Session:
    s = cf_requests.Session(impersonate="chrome124")
    s.headers.update({"Accept-Language": "ru-RU,ru;q=0.9"})
    return s


def _extract_lot_id(href: str) -> str | None:
    m = re.search(r"/item/(\d+)", href)
    return m.group(1) if m else None


def _clean_price(text: str) -> str:
    # Keep first price occurrence, normalize whitespace
    m = re.search(r"[\d\s\xa0]+₽", text)
    if m:
        return re.sub(r"\s+|\xa0", " ", m.group()).strip()
    return ""


def _title_from_href(href: str) -> str:
    m = re.search(r"/item/\d+_(.*)", href)
    if m:
        return m.group(1).replace("_", " ")
    return ""


class MeshokScraper(BaseScraper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session: cf_requests.Session | None = None

    def _get_session(self) -> cf_requests.Session:
        if self._session is None:
            self._session = _make_session()
        return self._session

    def fetch_new_lots(self, since: str | None = None) -> list[dict]:
        lots = []
        s = self._get_session()

        for page in range(1, 6):
            if "?" in self.url:
                page_url = f"{self.url}&page={page}&sort=endDate"
            else:
                page_url = f"{self.url}?page={page}&sort=endDate"

            resp = None
            for attempt in range(3):
                try:
                    resp = s.get(page_url, timeout=20)
                    resp.raise_for_status()
                    break
                except Exception as e:
                    resp = None
                    logger.warning("Meshok fetch attempt %d/3 failed (%s): %s", attempt + 1, page_url, e)
                    time.sleep(3 * (attempt + 1))
            if resp is None:
                logger.error("Meshok fetch error (%s): giving up after 3 attempts", page_url)
                break

            soup = BeautifulSoup(resp.text, "lxml")
            page_lots = self._parse_page(soup)

            if not page_lots:
                logger.debug("Meshok: no lots on page %d, stopping", page)
                break

            lots.extend(page_lots)
            logger.debug("Meshok page %d: %d lots", page, len(page_lots))

            time.sleep(2)

        return lots

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        lots = []
        seen = set()

        item_links = [
            a for a in soup.find_all("a", href=True)
            if "/item/" in a.get("href", "")
        ]

        for a in item_links:
            href = a.get("href", "")
            lot_id = _extract_lot_id(href)
            if not lot_id or lot_id in seen:
                continue
            seen.add(lot_id)

            full_url = f"{BASE_URL}{href}" if href.startswith("/") else href

            # Title: from URL slug (cleaner than full text which has prices mixed in)
            title = _title_from_href(href)

            # Price: first monetary value in link text
            link_text = a.get_text(separator=" ", strip=True)
            price = _clean_price(link_text)

            # Photo: look for img tag near the link
            photo_url = None
            parent = a
            for _ in range(4):
                parent = parent.parent
                if parent is None:
                    break
                img = parent.find("img")
                if img:
                    src = img.get("src") or img.get("data-src") or ""
                    if src and "/i/" in src:
                        photo_url = f"{BASE_URL}{src}" if src.startswith("/") else src
                    break

            lots.append({
                "lot_id": lot_id,
                "source": self.source_id,
                "source_label": self.label,
                "url": full_url,
                "title": title,
                "price": price,
                "photo_url": photo_url,
                "description": title,
                "published_at": None,
            })

        return lots
