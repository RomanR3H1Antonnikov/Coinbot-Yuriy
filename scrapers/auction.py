import time
import re
import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _extract_lot_id(href: str) -> str | None:
    m = re.search(r"/offer/(\d+)", href)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=(\d+)", href)
    return m.group(1) if m else None


class AuctionScraper(BaseScraper):
    def fetch_new_lots(self, since: str | None = None) -> list[dict]:
        lots = []
        page = 1

        while True:
            page_url = f"{self.url}?page={page}&sort=date"

            try:
                resp = SESSION.get(page_url, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.error("Auction fetch error (%s): %s", page_url, e)
                break

            soup = BeautifulSoup(resp.text, "lxml")

            cards = soup.select("div.offer-card, div.lot, article.offer, li.offer")
            if not cards:
                cards = soup.select("a[href*='/offer/']")
                lots_on_page = self._parse_links(cards, since)
            else:
                lots_on_page = self._parse_cards(cards, since)

            if not lots_on_page:
                break

            lots.extend(lots_on_page)

            if since and lots_on_page:
                last = lots_on_page[-1].get("published_at")
                if last and last < since:
                    break

            page += 1
            if page > 5:
                break

            time.sleep(1.5)

        return lots

    def _parse_cards(self, cards, since: str | None) -> list[dict]:
        lots = []
        for card in cards:
            a = card.select_one("a[href*='/offer/']")
            if not a:
                continue
            href = a.get("href", "")
            lot_id = _extract_lot_id(href)
            if not lot_id:
                continue

            full_url = f"https://auction.ru{href}" if href.startswith("/") else href

            title_el = card.select_one(".offer-title, .title, h3, h2")
            title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)

            price_el = card.select_one(".price, .offer-price, [class*='price']")
            price = price_el.get_text(strip=True) if price_el else ""

            img_el = card.select_one("img")
            photo_url = img_el.get("src") or img_el.get("data-src") if img_el else None

            date_el = card.select_one(".date, .time, [class*='date']")
            published_at = None
            if date_el:
                txt = date_el.get_text(strip=True)
                try:
                    dt = datetime.strptime(txt, "%d.%m.%Y")
                    published_at = dt.isoformat()
                except ValueError:
                    pass

            if since and published_at and published_at < since:
                continue

            lots.append({
                "lot_id": lot_id,
                "source": self.source_id,
                "source_label": self.label,
                "url": full_url,
                "title": title,
                "price": price,
                "photo_url": photo_url,
                "description": title,
                "published_at": published_at,
            })
        return lots

    def _parse_links(self, links, since: str | None) -> list[dict]:
        lots = []
        seen_ids = set()
        for a in links:
            href = a.get("href", "")
            lot_id = _extract_lot_id(href)
            if not lot_id or lot_id in seen_ids:
                continue
            seen_ids.add(lot_id)

            full_url = f"https://auction.ru{href}" if href.startswith("/") else href
            title = a.get_text(strip=True)

            lots.append({
                "lot_id": lot_id,
                "source": self.source_id,
                "source_label": self.label,
                "url": full_url,
                "title": title,
                "price": "",
                "photo_url": None,
                "description": title,
                "published_at": None,
            })
        return lots
