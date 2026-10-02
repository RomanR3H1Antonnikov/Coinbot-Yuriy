import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


def send_alert(lot: dict, bot_token: str = None, chat_id: str = None):
    token = bot_token or BOT_TOKEN
    cid = chat_id or CHAT_ID

    if not token or not cid:
        logger.error("send_alert: BOT_TOKEN or CHAT_ID not set")
        return

    title = lot.get("title", "—")
    price = lot.get("price", "—")
    url = lot.get("url", "")
    source_label = lot.get("source_label", lot.get("source", ""))
    photo_url = lot.get("photo_url")

    text = f"🔍 *{_escape(source_label)}*\n\n{_escape(title)}\n💰 {_escape(price)}\n\n{url}"

    base_url = f"https://api.telegram.org/bot{token}"

    try:
        if photo_url:
            resp = requests.post(
                f"{base_url}/sendPhoto",
                json={
                    "chat_id": cid,
                    "photo": photo_url,
                    "caption": text,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
        else:
            resp = requests.post(
                f"{base_url}/sendMessage",
                json={
                    "chat_id": cid,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                },
                timeout=10,
            )

        if not resp.ok:
            logger.error("Telegram API error %s: %s", resp.status_code, resp.text[:200])
        else:
            logger.info("Alert sent: %s", title[:60])

    except requests.RequestException as e:
        logger.error("send_alert network error: %s", e)


def _escape(text: str) -> str:
    # Escape Markdown special chars that can break formatting
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text
