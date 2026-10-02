import re
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from db.database import get_last_found_lots

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 *Coinbot — нумизматический мониторинг*\n\n"
        "Слежу за Мешком и Аукционом в поисках монет с браком и разновидностями.\n\n"
        "Команды:\n"
        "/logs — последние 20 находок\n"
        "/logs 10 — последние N находок",
        parse_mode="Markdown",
    )


@router.message(Command("logs"))
async def cmd_logs(message: Message):
    text = message.text or ""
    m = re.search(r"/logs\s+(\d+)", text)
    n = int(m.group(1)) if m else 20
    n = min(n, 50)

    lots = get_last_found_lots(n)
    if not lots:
        await message.answer("Находок пока нет.")
        return

    lines = [f"📋 *Последние находки ({len(lots)}):*\n"]
    for i, lot in enumerate(lots, 1):
        found_at = lot.get("found_at", "")
        if found_at:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(found_at)
                found_at = dt.strftime("%d.%m %H:%M")
            except Exception:
                pass

        source = lot.get("source", "")
        title = lot.get("title", "—")[:60]
        price = lot.get("price", "—")
        url = lot.get("url", "")

        lines.append(
            f"{i}. {source} | {found_at}\n"
            f"   {title} | {price}\n"
            f"   {url}\n"
        )

    # Split into chunks to avoid Telegram 4096-char limit
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) > 3800:
            await message.answer(chunk, disable_web_page_preview=True)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await message.answer(chunk, disable_web_page_preview=True)
