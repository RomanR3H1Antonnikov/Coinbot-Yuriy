import logging
import os

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

    text = (
        f"🔍 <b>{_h(source_label)}</b>\n\n"
        f"{_h(title)}\n"
        f"💰 {_h(price)}\n\n"
        f"{url}"
    )

    base_url = f"https://api.telegram.org/bot{token}"

    for cid in recipients:
        _send_to(base_url, cid, text, photo_url, title)


def _send_to(base_url: str, cid: str, text: str, photo_url: str | None, title: str):
    try:
        if photo_url:
            resp = requests.post(
                f"{base_url}/sendPhoto",
                json={"chat_id": cid, "photo": photo_url, "caption": text, "parse_mode": "HTML"},
                timeout=10,
            )
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
