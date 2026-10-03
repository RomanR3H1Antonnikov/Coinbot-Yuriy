import time
import re
import logging
import os

from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.avito.ru"
_PROXY = os.getenv("AVITO_PROXY")  # http://user:pass@host:port


def _make_session() -> cf_requests.Session:
    kwargs = {"impersonate": "chrome124"}
    if _PROXY:
        kwargs["proxies"] = {"http": _PROXY, "https": _PROXY}
    s = cf_requests.Session(**kwargs)
    s.headers.update({
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://www.avito.ru/",
    })
    return s


def _extract_lot_id(href: str) -> str | None:
    # Avito item URL: /city/category/title-123456789
    m = re.search(r"-(\d{7,})$", href.split("?")[0])
    return m.group(1) if m else None


class AvitoScraper(BaseScraper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session: cf_requests.Session | None = None

    def _get_session(self) -> cf_requests.Session:
        if self._session is None:
            self._session = _make_session()
        return self._session

    def fetch_new_lots(self, since: str | None = None) -> list[dict]:
        if not _PROXY:
            logger.warning(
                "Avito [%s]: AVITO_PROXY not set — Avito blocks datacenter IPs. "
                "Set AVITO_PROXY=http://user:pass@host:port in .env to enable.",
                self.source_id,
            )

        lots = []
        s = self._get_session()

        for page in range(1, 4):
            page_url = f"{self.url}&p={page}" if "?" in self.url else f"{self.url}?p={page}"

            try:
                resp = s.get(page_url, timeout=20)
            except Exception as e:
                logger.error("Avito fetch error (%s): %s", page_url, e)
                break

            if resp.status_code == 429:
                logger.warning("Avito [%s]: 429 rate-limited — datacenter IP blocked", self.source_id)
                break
            if resp.status_code == 403:
                logger.warning("Avito [%s]: 403 forbidden", self.source_id)
                break
            if not resp.ok:
                logger.error("Avito [%s]: HTTP %d", self.source_id, resp.status_code)
                break

            soup = BeautifulSoup(resp.text, "lxml")
            page_lots = self._parse_page(soup)

            if not page_lots:
                logger.debug("Avito: no lots on page %d, stopping", page)
                break

            lots.extend(page_lots)
            logger.debug("Avito page %d: %d lots", page, len(page_lots))
            time.sleep(3)

        return lots

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        lots = []
        seen = set()

        # Avito item containers: data-marker="item"
        items = soup.find_all("div", attrs={"data-marker": "item"})

        if not items:
            # Fallback: look for item links directly
            items = soup.find_all("a", attrs={"data-marker": "item-title"})

        for item in items:
            # Title link
            a = (
                item.find("a", attrs={"data-marker": "item-title"})
                if item.name != "a"
                else item
            )
            if not a:
                a = item.find("a", href=lambda h: h and "/rossiya/" not in h and h.startswith("/"))
            if not a:
                continue

            href = a.get("href", "")
            if not href:
                continue

            lot_id = _extract_lot_id(href)
            if not lot_id or lot_id in seen:
                continue
            seen.add(lot_id)

            full_url = f"{BASE_URL}{href}" if href.startswith("/") else href
            title = a.get_text(strip=True)

            # Price
            price = ""
            price_el = item.find(attrs={"data-marker": "item-price"}) if item.name != "a" else None
            if not price_el and item.name != "a":
                price_el = item.find(class_=re.compile(r"price"))
            if price_el:
                price = price_el.get_text(strip=True)

            # Photo
            photo_url = None
            img = item.find("img") if item.name != "a" else None
            if img:
                src = img.get("src") or img.get("data-src") or ""
                if src and not src.endswith("gif"):
                    photo_url = src if src.startswith("http") else f"{BASE_URL}{src}"

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
