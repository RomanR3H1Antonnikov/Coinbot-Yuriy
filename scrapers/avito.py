import atexit
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.avito.ru"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(BASE_DIR, ".avito_profile")        # persistent Chrome profile (cookies)
BLOCK_FILE = os.path.join(BASE_DIR, "logs", "avito_blocked_until.txt")
BLOCK_BACKOFF_H = 3          # after a soft block stay away from Avito this long
PAGES_PER_SOURCE = 2
HEADLESS = os.getenv("AVITO_HEADLESS", "1") != "0"

# Removes the main automation fingerprints that QRATOR checks (same idea as the old MarketRadar parser)
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
if (!window.chrome) { window.chrome = {app: {isInstalled: false}, csi: function(){}, loadTimes: function(){}, runtime: {}}; }
Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
"""


class AvitoBlocked(Exception):
    """Avito/QRATOR refused this session (soft block or unresolved challenge)."""


def _is_challenge_or_block(html: str) -> bool:
    if len(html) > 60_000:
        return False
    low = html[:4000].lower()
    return any(sig in low for sig in (
        "доступ ограничен", "проблема с ip", "проверка безопасности",
        "captcha", "я не робот", "qrator", "checking your browser",
    ))


def _blocked_until() -> datetime | None:
    try:
        with open(BLOCK_FILE, encoding="utf-8") as f:
            return datetime.fromisoformat(f.read().strip())
    except Exception:
        return None


def _set_block() -> None:
    try:
        os.makedirs(os.path.dirname(BLOCK_FILE), exist_ok=True)
        until = datetime.now(timezone.utc) + timedelta(hours=BLOCK_BACKOFF_H)
        with open(BLOCK_FILE, "w", encoding="utf-8") as f:
            f.write(until.isoformat())
    except Exception:
        pass


def _clear_block() -> None:
    try:
        os.remove(BLOCK_FILE)
    except OSError:
        pass


def _extract_lot_id(href: str) -> str | None:
    # Avito item URL: /city/category/title-123456789  (older: ..._123456789)
    m = re.search(r"[-_](\d{7,})$", href.split("?")[0])
    return m.group(1) if m else None


class _Browser:
    """One real Chrome (persistent profile) shared by all Avito sources of a run."""

    def __init__(self) -> None:
        self._pw = None
        self._ctx = None
        self.warmed = False

    def start(self) -> None:
        from playwright.sync_api import sync_playwright
        os.makedirs(PROFILE_DIR, exist_ok=True)
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            channel="chrome",                    # system Google Chrome: real TLS/HTTP2 fingerprint
            headless=HEADLESS,
            viewport={"width": 1600, "height": 900},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            args=["--disable-blink-features=AutomationControlled", "--lang=ru-RU"],
        )
        self._ctx.add_init_script(_STEALTH_JS)
        logger.info("Avito: Chrome started (headless=%s)", HEADLESS)

    def close(self) -> None:
        for obj in (self._ctx, self._pw):
            try:
                if obj:
                    obj.close() if hasattr(obj, "close") else obj.stop()
            except Exception:
                pass
        self._ctx = self._pw = None
        self.warmed = False

    def _settle(self, page) -> str:
        """Wait for the QRATOR JS challenge to resolve and return the page HTML."""
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            pass
        html = page.content()
        for attempt in range(6):
            if not _is_challenge_or_block(html):
                break
            logger.info("Avito: challenge page, waiting (%d/6)...", attempt + 1)
            time.sleep(5)
            try:
                page.wait_for_load_state("networkidle", timeout=6_000)
            except Exception:
                pass
            html = page.content()
        return html

    def warm_up(self) -> None:
        if self.warmed:
            return
        page = self._ctx.new_page()
        try:
            page.goto(BASE_URL + "/", wait_until="load", timeout=40_000)
            html = self._settle(page)
            if _is_challenge_or_block(html):
                raise AvitoBlocked("homepage challenge/soft block")
            time.sleep(random.uniform(3, 6))
            self.warmed = True
        finally:
            page.close()

    def fetch(self, url: str, referer: str = BASE_URL + "/") -> str:
        page = self._ctx.new_page()
        try:
            resp = page.goto(url, wait_until="load", timeout=40_000, referer=referer)
            status = resp.status if resp else 0
            html = self._settle(page)
            if _is_challenge_or_block(html) or status in (403, 429, 439):
                raise AvitoBlocked(f"HTTP {status}, challenge/soft block")
            time.sleep(random.uniform(2, 4))
            return html
        finally:
            page.close()


_browser: _Browser | None = None


def close_browser() -> None:
    global _browser
    if _browser:
        _browser.close()
        _browser = None


atexit.register(close_browser)


class AvitoScraper(BaseScraper):
    def fetch_new_lots(self, since: str | None = None) -> list[dict]:
        global _browser
        until = _blocked_until()
        if until and until > datetime.now(timezone.utc):
            logger.warning("Avito [%s]: skipped, cooling down after a block until %s UTC",
                           self.source_id, until.strftime("%d.%m %H:%M"))
            return []

        lots: list[dict] = []
        try:
            if _browser is None:
                _browser = _Browser()
                _browser.start()
            _browser.warm_up()

            for page_no in range(1, PAGES_PER_SOURCE + 1):
                page_url = f"{self.url}&p={page_no}" if "?" in self.url else f"{self.url}?p={page_no}"
                html = _browser.fetch(page_url)
                page_lots = self._parse_page(BeautifulSoup(html, "lxml"))
                if not page_lots:
                    logger.info("Avito [%s]: no lots on page %d (%.0f KB)",
                                self.source_id, page_no, len(html) / 1024)
                    break
                lots.extend(page_lots)
                time.sleep(random.uniform(6, 12))
            _clear_block()
        except AvitoBlocked as e:
            logger.warning("Avito [%s]: BLOCKED (%s). Pausing Avito for %dh.",
                           self.source_id, e, BLOCK_BACKOFF_H)
            _set_block()
            close_browser()
        except Exception as e:
            logger.error("Avito [%s]: browser error: %s", self.source_id, e)
            close_browser()

        time.sleep(random.uniform(5, 10))
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
