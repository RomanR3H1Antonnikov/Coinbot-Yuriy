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
PROFILE_DIR = os.path.join(BASE_DIR, ".avito_profile_cdp")    # persistent Chrome profile (cookies)
CDP_PORT = 9223
BLOCK_FILE = os.path.join(BASE_DIR, "logs", "avito_blocked_until.txt")
BLOCK_BACKOFF_H = 3          # after a soft block stay away from Avito this long
PAGES_PER_SOURCE = 2
VISIBLE = os.getenv("AVITO_VISIBLE", "0") == "1"   # show the Chrome window (debugging)

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


def _find_chrome() -> str:
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.exists(path):
                return path
    raise RuntimeError("Google Chrome not found")


def _content(page) -> str:
    """page.content() raises while a redirect is still navigating; retry a few times."""
    for _ in range(6):
        try:
            return page.content()
        except Exception as e:
            if "navigating" not in str(e):
                raise
            time.sleep(2)
    return page.content()


class _Browser:
    """A normally launched Google Chrome driven over CDP.

    Playwright-launched Chrome (automation flags) is flagged by QRATOR with "проблема с IP" even on a clean
    residential IP; a regular chrome.exe with a remote-debugging port is accepted. One Chrome is shared by
    all Avito sources of a run.
    """

    def __init__(self) -> None:
        self._proc = None
        self._pw = None
        self._browser = None
        self._page = None
        self.warmed = False

    @staticmethod
    def _kill_stale_chrome() -> None:
        """A Chrome left over from a hung/aborted run still owns the profile and CDP port:
        the next launch then just attaches to a dead window or waits forever."""
        import subprocess
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
              "Where-Object { $_.CommandLine -like '*avito_profile_cdp*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except Exception:
            pass

    @staticmethod
    def _wait_for_network(max_wait: int = 300) -> None:
        """After sleep/hibernate or a VPN reconnect DNS is down for a while (ERR_NAME_NOT_RESOLVED)."""
        import socket
        waited = 0
        while waited < max_wait:
            try:
                socket.getaddrinfo("www.avito.ru", 443)
                if waited:
                    logger.info("Avito: network is back after %ds", waited)
                return
            except OSError:
                if waited == 0:
                    logger.warning("Avito: www.avito.ru does not resolve, waiting for the network...")
                time.sleep(10)
                waited += 10
        logger.warning("Avito: network still down after %ds, trying anyway", max_wait)

    def start(self) -> None:
        import subprocess
        from playwright.sync_api import sync_playwright
        self._wait_for_network()
        self._kill_stale_chrome()
        os.makedirs(PROFILE_DIR, exist_ok=True)
        args = [
            _find_chrome(), f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run", "--no-default-browser-check", "--lang=ru-RU", "--window-size=1400,900",
        ]
        if not VISIBLE:
            args += ["--window-position=-2400,-2400"]
        args.append("about:blank")
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._pw = sync_playwright().start()
        last = None
        for _ in range(20):
            time.sleep(1)
            try:
                self._browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
                break
            except Exception as e:
                last = e
        if not self._browser:
            raise RuntimeError(f"cannot attach to Chrome: {last}")
        ctx = self._browser.contexts[0]
        self._page = ctx.pages[0] if ctx.pages else ctx.new_page()
        logger.info("Avito: Chrome started")

    def close(self) -> None:
        for obj in (self._browser, self._pw):
            try:
                if obj:
                    obj.close() if hasattr(obj, "close") else obj.stop()
            except Exception:
                pass
        if self._proc:
            try:
                import subprocess
                subprocess.run(["taskkill", "/PID", str(self._proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = self._pw = self._browser = self._page = None
        self.warmed = False

    def _settle(self, page) -> str:
        """Wait for the QRATOR JS challenge to resolve and return the page HTML."""
        time.sleep(5)
        html = _content(page)
        for attempt in range(6):
            if not _is_challenge_or_block(html):
                break
            logger.info("Avito: challenge page, waiting (%d/6)...", attempt + 1)
            time.sleep(5)
            html = _content(page)
        return html

    def warm_up(self) -> None:
        if self.warmed:
            return
        self._page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=45_000)
        html = self._settle(self._page)
        if _is_challenge_or_block(html):
            raise AvitoBlocked("homepage challenge/soft block")
        time.sleep(random.uniform(3, 6))
        self.warmed = True

    def fetch(self, url: str, referer: str = BASE_URL + "/") -> str:
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=45_000, referer=referer)
        status = resp.status if resp else 0
        html = self._settle(self._page)
        if _is_challenge_or_block(html) or status in (403, 429, 439):
            raise AvitoBlocked(f"HTTP {status}, challenge/soft block")
        html = self._scroll_and_read(html)
        time.sleep(random.uniform(2, 4))
        return html

    def _scroll_and_read(self, html: str) -> str:
        """Scroll down in steps so lazy-loaded card photos get their src, then re-read the HTML."""
        try:
            # Bring every 3rd card into view (works even when the window is in the background,
            # unlike wheel events), then the bottom, so lazy images get their src
            total = self._page.evaluate("document.querySelectorAll('[data-marker=item]').length")
            for i in range(0, total, 3):
                self._page.evaluate(
                    "i => { const e = document.querySelectorAll('[data-marker=item]')[i];"
                    " if (e) e.scrollIntoView({block: 'center'}); }", i)
                time.sleep(random.uniform(0.4, 0.7))
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            fresh = _content(self._page)
            if not _is_challenge_or_block(fresh):
                return fresh
        except Exception as e:
            logger.debug("Avito: scroll failed: %s", e)
        return html


def _photo_candidate(tag) -> str | None:
    """Best image URL from an <img>/<source> tag: src, data-src, or the last (largest) srcset entry."""
    for attr in ("src", "data-src", "data-lazy-src"):
        v = (tag.get(attr) or "").strip()
        if v and not v.startswith("data:") and not v.endswith(".gif"):
            return v
    for attr in ("srcset", "data-srcset"):
        v = (tag.get(attr) or "").strip()
        if v:
            first = v.split(",")[-1].strip().split(" ")[0]
            if first and not first.startswith("data:"):
                return first
    return None


_SLIDER_PREFIX = "slider-image/image-"
_AVITO_IMG = re.compile(r"https?://[\w.-]*img\.avito\.st/image/[^\s\"'<>)]+")


def _extract_photo(item) -> str | None:
    for tag in item.find_all(["img", "source"]):
        v = _photo_candidate(tag)
        if v:
            return v if v.startswith("http") else (f"https:{v}" if v.startswith("//") else f"{BASE_URL}{v}")
    # Slider cards have no <img>: the picture URLs sit in <li data-marker="slider-image/image-https://...">
    for el in item.find_all(attrs={"data-marker": re.compile("^" + re.escape(_SLIDER_PREFIX))}):
        v = el["data-marker"][len(_SLIDER_PREFIX):]
        if v.startswith("http"):
            return v
    m = _AVITO_IMG.search(str(item))
    return m.group(0).replace("&amp;", "&") if m else None


_NOPHOTO_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "avito_nophoto.txt")
_nophoto_logged = 0  # per process: a few samples are enough to see why a card has no picture


def _log_no_photo(source_id: str, item) -> None:
    global _nophoto_logged
    if _nophoto_logged >= 4:
        return
    try:
        if os.path.exists(_NOPHOTO_LOG) and os.path.getsize(_NOPHOTO_LOG) > 300_000:
            return
        with open(_NOPHOTO_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now().isoformat()} {source_id}\n{str(item)[:2500]}\n")
        _nophoto_logged += 1
    except OSError:
        pass


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

            for page_no in range(1, (getattr(self, 'pages', None) or PAGES_PER_SOURCE) + 1):
                page_url = f"{self.url}&p={page_no}" if "?" in self.url else f"{self.url}?p={page_no}"
                html = _browser.fetch(page_url)
                page_lots = self._parse_page(BeautifulSoup(html, "lxml"))
                if not page_lots:
                    logger.info("Avito [%s]: no lots on page %d (%.0f KB)",
                                self.source_id, page_no, len(html) / 1024)
                    break
                known = {l["lot_id"] for l in lots}
                fresh = [l for l in page_lots if l["lot_id"] not in known]
                if not fresh:  # short result: page 2 repeats page 1
                    break
                lots.extend(fresh)
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
            full_url = full_url.split("?")[0]  # drop tracking query (slocation, context=...)
            title = a.get_text(strip=True)

            # Price
            price = ""
            price_el = item.find(attrs={"data-marker": "item-price"}) if item.name != "a" else None
            if not price_el and item.name != "a":
                price_el = item.find(class_=re.compile(r"price"))
            if price_el:
                price = price_el.get_text(strip=True)

            # Photo
            photo_url = _extract_photo(item) if item.name != "a" else None
            if not photo_url and item.name != "a":
                _log_no_photo(self.source_id, item)

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
