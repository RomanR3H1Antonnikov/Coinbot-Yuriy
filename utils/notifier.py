import logging
import os
import struct

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Support multiple recipients: CHAT_IDS=id1,id2 or legacy CHAT_ID=id
def _get_chat_ids() -> list[str]:
    raw = os.getenv("CHAT_IDS") or os.getenv("CHAT_ID", "")
    return [cid.strip() for cid in raw.split(",") if cid.strip()]


def send_alert(lot: dict, bot_token: str = None, chat_id: str = None):
    token = bot_token or BOT_TOKEN
    if not token:
        logger.error("send_alert: BOT_TOKEN not set")
        return

    recipients = [chat_id] if chat_id else _get_chat_ids()
    if not recipients:
        logger.error("send_alert: no CHAT_IDS configured")
        return

    title = lot.get("title", "—")
    price = lot.get("price", "—")
    url = lot.get("url", "")
    source_label = lot.get("source_label", lot.get("source", ""))
    photo_url = lot.get("photo_url")

    matched = lot.get("matched") or []
    text = (
        f"🔍 <b>{_h(source_label)}</b>\n\n"
        f"{_h(title)}\n"
        f"💰 {_h(price)}\n"
        + (f"🔎 Совпало: {_h(', '.join(matched))}\n" if matched else "")
        + f"\n{url}"
    )

    base_url = f"https://api.telegram.org/bot{token}"

    # One download per alert, not per recipient; the size goes to the journal for the daily report
    data = None
    if photo_url:
        data, photo_url = _download_best(photo_url)
    _note_photo(lot, data, photo_url)

    for cid in recipients:
        _send_to(base_url, cid, text, photo_url, title, data)


def _image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) of a PNG or JPEG from its header."""
    try:
        if data[:8] == bytes.fromhex("89504e470d0a1a0a"):
            w, h = struct.unpack(">II", data[16:24])
            return w, h
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            if data[i + 1] in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    except struct.error:
        pass
    return None


SMALL_PX = 500  # shorter side below this is shown as a small picture in Telegram


def _note_photo(lot: dict, data: bytes | None, photo_url: str | None) -> None:
    """mode: none (lot has no photo) | upload | url (download failed, Telegram fetches the link
    itself, usually a tiny preview). Read by the daily reports."""
    from utils import run_journal
    if not photo_url:
        mode, w, h = "none", 0, 0
    elif data:
        mode = "upload"
        w, h = _image_size(data) or (0, 0)
    else:
        mode, w, h = "url", 0, 0
    run_journal.write("photo:" + lot.get("source", ""), mode=mode, w=w, h=h, small=bool(w and min(w, h) < SMALL_PX))


def _download_best(photo_url: str) -> tuple[bytes | None, str]:
    """auction.ru lists /mid/ pictures (<= 400x300); /big/ is ~2x larger. Try the larger first."""
    candidates = [photo_url]
    if "/mid/" in photo_url:
        candidates = [photo_url.replace("/mid/", "/big/"), photo_url]
    for url in candidates:
        data = _download_photo(url)
        if data:
            return data, url
    return None, photo_url


def _download_photo(photo_url: str) -> bytes | None:
    """Telegram cannot fetch some hosts itself (meshok.net -> 'failed to get HTTP URL content'),
    so the image is downloaded here and uploaded; otherwise the alert shows only a tiny link preview."""
    try:
        from curl_cffi import requests as cf
        r = cf.get(photo_url, impersonate="chrome124", timeout=20)
        if r.status_code == 200 and r.content[:2] in (bytes.fromhex("ffd8"), bytes.fromhex("8950"), b"GI", b"RI"):
            return r.content
    except Exception as e:
        logger.warning("photo download failed (%s): %s", photo_url, e)
    return None


def _send_photo(base_url: str, cid: str, photo_url: str, text: str, data: bytes | None):
    """Always upload the downloaded image first (a big photo, no dependence on Telegram being
    able to fetch the host); fall back to passing the URL if the download failed."""
    if data:
        resp = requests.post(f"{base_url}/sendPhoto",
                             data={"chat_id": cid, "caption": text, "parse_mode": "HTML"},
                             files={"photo": ("lot.jpg", data)}, timeout=30)
        if resp.ok:
            return resp
    return requests.post(f"{base_url}/sendPhoto",
                         json={"chat_id": cid, "photo": photo_url, "caption": text, "parse_mode": "HTML"},
                         timeout=10)


def _send_to(base_url: str, cid: str, text: str, photo_url: str | None, title: str, data: bytes | None = None):
    try:
        if photo_url:
            resp = _send_photo(base_url, cid, photo_url, text, data)
            if not resp.ok:
                resp = requests.post(
                    f"{base_url}/sendMessage",
                    json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
                    timeout=10,
                )
        else:
            resp = requests.post(
                f"{base_url}/sendMessage",
                json={"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False},
                timeout=10,
            )

        if not resp.ok:
            logger.error("Telegram error [chat=%s] %s: %s", cid, resp.status_code, resp.text[:200])
        else:
            logger.info("Alert sent to %s: %s", cid, title[:50])

    except requests.RequestException as e:
        logger.error("send_alert network error [chat=%s]: %s", cid, e)


def _h(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
