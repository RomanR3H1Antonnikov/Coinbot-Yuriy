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


def _parse_price(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_lot_id(href: str) -> str | None:
    m = re.search(r"/item/(\d+)", href)
    return m.group(1) if m else None


def _parse_date(text: str) -> str | None:
    """
    Meshok shows dates like '02.10.2025 14:32' or relative 'сегодня 14:32'.
    Returns ISO string or None.
    """
    text = text.strip()
    now = datetime.now(timezone.utc)

    if "сегодня" in text.lower():
        time_part = text.lower().replace("сегодня", "").strip()
        try:
            t = datetime.strptime(time_part, "%H:%M")
            return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0).isoformat()
        except ValueError:
            return now.isoformat()

    if "вчера" in text.lower():
        from datetime import timedelta
        time_part = text.lower().replace("вчера", "").strip()
        try:
            t = datetime.strptime(time_part, "%H:%M")
            yesterday = now - timedelta(days=1)
            return yesterday.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0).isoformat()
        except ValueError:
            return None

    try:
        dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
        return dt.isoformat()
    except ValueError:
        pass
    return None


class MeshokScraper(BaseScraper):
    def fetch_new_lots(self, since: str | None = None) -> list[dict]:
        lots = []
        page = 1

        while True:
            url = self.url
            if "?" in url:
                page_url = f"{url}&page={page}&sort=date_desc"
            else:
                page_url = f"{url}?page={page}&sort=date_desc"

            try:
                resp = SESSION.get(page_url, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.error("Meshok fetch error (%s): %s", page_url, e)
                break

            soup = BeautifulSoup(resp.text, "lxml")

            # Meshok item cards
            cards = soup.select("div.item-card, article.item, li.item, div.lot-card")

            # fallback: find links to /item/NNN
            if not cards:
                cards = soup.select("a[href*='/item/']")
                lots_on_page = self._parse_links(cards, since)
            else:
                lots_on_page = self._parse_cards(cards, since)

            if not lots_on_page:
                break

            lots.extend(lots_on_page)

            # if since is set and last lot is older — stop paging
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
            a = card.select_one("a[href*='/item/']")
            if not a:
                continue
            href = a.get("href", "")
            lot_id = _extract_lot_id(href)
            if not lot_id:
                continue

            full_url = f"https://meshok.net{href}" if href.startswith("/") else href

            title_el = card.select_one(".item-title, .lot-title, h3, h2, .title")
            title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)

            price_el = card.select_one(".price, .lot-price, .item-price, [class*='price']")
            price = _parse_price(price_el.get_text()) if price_el else ""

            img_el = card.select_one("img")
            photo_url = img_el.get("src") or img_el.get("data-src") if img_el else None

            date_el = card.select_one(".date, .time, .item-date, [class*='date'], [class*='time']")
            published_at = _parse_date(date_el.get_text()) if date_el else None

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

            full_url = f"https://meshok.net{href}" if href.startswith("/") else href
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
