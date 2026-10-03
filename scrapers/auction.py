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


def _extract_lot_id(href: str, data_id: str = "") -> str | None:
    if data_id and re.match(r"^\d+$", data_id):
        return data_id
    # href: /offer/slug-iNNNNNNN.html
    m = re.search(r"-i(\d{8,})\.html", href)
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
        import json as _json

        # auction.ru card containers
        cards = soup.find_all("div", class_="offers__item")

        for card in cards:
            data_id = card.get("data-id", "")
            link = card.find("a", class_="offer_snippet__link")
            if not link:
                continue

            href = link.get("href", "")
            lot_id = _extract_lot_id(href, data_id)
            if not lot_id or lot_id in seen:
                continue
            seen.add(lot_id)

            full_url = f"{BASE_URL}{href}" if href.startswith("/") else href

            # Title from aria-label (most reliable)
            title = link.get("aria-label", "").strip()
            if not title:
                title_el = card.find("a", class_="offer_snippet_body_top--title")
                title = title_el.get_text(strip=True) if title_el else ""

            # Price: strip rouble symbol garbage
            price = ""
            price_el = card.find("div", class_="offer_snippet_body_price--value")
            if price_el:
                raw = price_el.get_text(separator=" ", strip=True)
                price = re.sub(r"\s*a\s*$", " ₽", raw).strip()

            # Photo: data-img JSON array on div.snippet_photo.lazy
            photo_url = None
            photo_div = card.find("div", class_="snippet_photo")
            if photo_div:
                data_img = photo_div.get("data-img", "")
                if data_img:
                    try:
                        imgs = _json.loads(data_img)
                        if imgs:
                            photo_url = imgs[0]
                    except Exception:
                        pass

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

        if not lots:
            logger.warning("Auction [%s]: card parser found 0 lots — page structure may have changed", self.source_id)

        return lots
