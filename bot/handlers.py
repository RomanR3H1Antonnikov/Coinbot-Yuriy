import re
import asyncio
import logging
from datetime import datetime
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from db.database import get_last_found_lots

logger = logging.getLogger(__name__)
router = Router()

SOURCE_LABELS = {
    "meshok_braki": "Мешок — Браки",
    "meshok_yub_main": "Мешок — Юбилейка",
    "meshok_yub_tir": "Мешок — Юбилейка+Тиражные",
    "meshok_russia_9196": "Мешок — Россия 1991–1996",
    "meshok_ussr_1rub": "Мешок — СССР 1 рубль",
    "auction_post1991": "Аукцион — Россия после 1991",
    "auction_yub": "Аукцион — Юбилейные",
    "auction_1rub": "Аукцион — 1 рубль",
}


def _h(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_date(found_at: str) -> str:
    try:
        dt = datetime.fromisoformat(found_at)
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return found_at


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Coinbot — нумизматический мониторинг</b>\n\n"
        "Слежу за Мешком и Аукционом в поисках монет с браком и разновидностями.\n\n"
        "Команды:\n"
        "/logs — последние 5 находок с фото\n"
        "/logs 10 — последние N находок с фото\n"
        "/list 20 — текстовый список последних N находок",
        parse_mode="HTML",
    )


@router.message(Command("logs"))
async def cmd_logs(message: Message):
    """Send last N lots as individual photo messages (like real alerts)."""
    text = message.text or ""
    m = re.search(r"/logs\s+(\d+)", text)
    n = int(m.group(1)) if m else 5
    n = min(n, 20)

    lots = get_last_found_lots(n)
    if not lots:
        await message.answer("Находок пока нет.")
        return

    for lot in lots:
        source_id = lot.get("source", "")
        source_label = SOURCE_LABELS.get(source_id, source_id)
        title = lot.get("title") or "—"
        price = lot.get("price") or "—"
        url = lot.get("url", "")
        photo_url = lot.get("photo_url")
        found_at = _fmt_date(lot.get("found_at", ""))

        caption = (
            f"🔍 <b>{_h(source_label)}</b>  <i>{found_at}</i>\n\n"
            f"{_h(title)}\n"
            f"💰 {_h(price)}\n\n"
            f"{url}"
        )

        try:
            if photo_url:
                await message.answer_photo(photo=photo_url, caption=caption, parse_mode="HTML")
            else:
                await message.answer(caption, parse_mode="HTML")
        except Exception:
            await message.answer(caption, parse_mode="HTML")

        await asyncio.sleep(0.3)


@router.message(Command("list"))
async def cmd_list(message: Message):
    """Send compact text list of last N lots."""
    text = message.text or ""
    m = re.search(r"/list\s+(\d+)", text)
    n = int(m.group(1)) if m else 20
    n = min(n, 50)

    lots = get_last_found_lots(n)
    if not lots:
        await message.answer("Находок пока нет.")
        return

    lines = [f"📋 <b>Последние находки ({len(lots)}):</b>\n"]
    for i, lot in enumerate(lots, 1):
        source_id = lot.get("source", "")
        source_label = SOURCE_LABELS.get(source_id, source_id)
        title = (lot.get("title") or "—")[:60]
        price = lot.get("price") or "—"
        url = lot.get("url", "")
        found_at = _fmt_date(lot.get("found_at", ""))

        lines.append(
            f"{i}. <b>{_h(source_label)}</b> | {found_at}\n"
            f"   {_h(title)} | {_h(price)}\n"
            f"   {url}\n"
        )

    chunk = ""
    for line in lines:
        if len(chunk) + len(line) > 3800:
            await message.answer(chunk, parse_mode="HTML", disable_web_page_preview=True)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await message.answer(chunk, parse_mode="HTML", disable_web_page_preview=True)
