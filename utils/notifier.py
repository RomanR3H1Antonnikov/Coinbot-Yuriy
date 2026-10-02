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

    text = (
        f"🔍 <b>{_h(source_label)}</b>\n\n"
        f"{_h(title)}\n"
        f"💰 {_h(price)}\n\n"
        f"{url}"
    )

    base_url = f"https://api.telegram.org/bot{token}"

    try:
        if photo_url:
            resp = requests.post(
                f"{base_url}/sendPhoto",
                json={
                    "chat_id": cid,
                    "photo": photo_url,
                    "caption": text,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            if not resp.ok:
                # fallback: send text only
                resp = requests.post(
                    f"{base_url}/sendMessage",
                    json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
                    timeout=10,
                )
        else:
            resp = requests.post(
                f"{base_url}/sendMessage",
                json={
                    "chat_id": cid,
                    "text": text,
                    "parse_mode": "HTML",
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


def _h(text: str) -> str:
    """Escape HTML special chars for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
