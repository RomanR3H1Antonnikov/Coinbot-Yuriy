import time
import re
import logging

from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://auction.ru"


def _make_session() -> cf_requests.Session:
    s = cf_requests.Session(impersonate="chrome124")
    s.headers.update({"Accept-Language": "ru-RU,ru;q=0.9"})
    return s


def _extract_lot_id(href: str) -> str | None:
    m = re.search(r"/offer/(\d+)", href)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=(\d+)", href)
    return m.group(1) if m else None


class AuctionScraper(BaseScraper):
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
            page_url = f"{self.url}?page={page}&sort=date"

            try:
                resp = s.get(page_url, timeout=20)
                resp.raise_for_status()
            except Exception as e:
                logger.error("Auction fetch error (%s): %s", page_url, e)
                break

            soup = BeautifulSoup(resp.text, "lxml")
            page_lots = self._parse_page(soup)

            if not page_lots:
                logger.debug("Auction: no lots on page %d, stopping", page)
                break

            lots.extend(page_lots)
            logger.debug("Auction page %d: %d lots", page, len(page_lots))

            time.sleep(2)

        return lots

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        lots = []
        seen = set()

        # Try card-based selectors first
        cards = soup.select(
            "div.offer-card, div.lot-item, article.offer, "
            "div[class*='offer'], li[class*='offer']"
        )

        if cards:
            for card in cards:
                a = card.find("a", href=lambda h: h and "/offer/" in h)
                if not a:
                    continue
                href = a.get("href", "")
                lot_id = _extract_lot_id(href)
                if not lot_id or lot_id in seen:
                    continue
                seen.add(lot_id)

                full_url = f"{BASE_URL}{href}" if href.startswith("/") else href

                title_el = card.select_one(".offer-title, .title, h3, h2")
                title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)

                price_el = card.select_one("[class*='price']")
                price = price_el.get_text(strip=True) if price_el else ""

                img = card.find("img")
                photo_url = None
                if img:
                    src = img.get("src") or img.get("data-src", "")
                    photo_url = f"{BASE_URL}{src}" if src.startswith("/") else src or None

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
        else:
            # Fallback: all offer links
            for a in soup.find_all("a", href=lambda h: h and "/offer/" in h):
                href = a.get("href", "")
                lot_id = _extract_lot_id(href)
                if not lot_id or lot_id in seen:
                    continue
                seen.add(lot_id)
                full_url = f"{BASE_URL}{href}" if href.startswith("/") else href
                lots.append({
                    "lot_id": lot_id,
                    "source": self.source_id,
                    "source_label": self.label,
                    "url": full_url,
                    "title": a.get_text(strip=True),
                    "price": "",
                    "photo_url": None,
                    "description": a.get_text(strip=True),
                    "published_at": None,
                })

        return lots
