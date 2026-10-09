import os
import re
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import yaml
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from db.database import (
    get_last_found_lots, get_rejected, count_rejected_by_stage,
)

logger = logging.getLogger(__name__)
router = Router()

MSK = timezone(timedelta(hours=3))


def _load_source_labels() -> dict[str, str]:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    labels: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        for group in ("meshok_sources", "auction_sources", "avito_sources"):
            for src in cfg.get(group) or []:
                labels[src["id"]] = src.get("label", src["id"])
    except Exception as e:
        logger.warning("Could not load source labels from config.yaml: %s", e)
    return labels


SOURCE_LABELS = _load_source_labels()


def _h(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_date(found_at: str) -> str:
    """DB timestamps are UTC; show Moscow time."""
    try:
        dt = datetime.fromisoformat(found_at).replace(tzinfo=timezone.utc).astimezone(MSK)
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
        "/list 20 — текстовый список последних N находок\n"
        "/rejected — что бот рассмотрел, но не прислал (за 24 ч, обиходные монеты)\n"
        "/rejected 48 ии — за 48 ч, отклонённые ИИ (ещё: правила, все)",
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

    await _send_chunks(message, lines)


async def _send_chunks(message: Message, lines: list[str]):
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) > 3800:
            await message.answer(chunk, parse_mode="HTML", disable_web_page_preview=True)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await message.answer(chunk, parse_mode="HTML", disable_web_page_preview=True)


STAGE_ALIASES = {
    "тиражка": "jubilee", "обиходные": "jubilee", "jubilee": "jubilee",
    "ии": "llm", "llm": "llm",
    "правила": "rules", "rules": "rules",
    "все": "all", "всё": "all", "all": "all",
}
STAGE_TITLES = {
    "jubilee": "обиходные монеты (тиражка)",
    "llm": "ИИ: нет брака или разновидности",
    "rules": "правила (годовик, копейки, до 1965, цена, россыпи)",
}
MAX_REJECTED_LINES = 100


@router.message(Command("rejected"))
async def cmd_rejected(message: Message):
    """Lots that passed keyword filter but were not sent, with the reason."""
    args = (message.text or "").split()[1:]
    hours, stage = 24, "jubilee"
    for a in args:
        if a.isdigit():
            hours = min(max(int(a), 1), 24 * 7)
        elif a.lower() in STAGE_ALIASES:
            stage = STAGE_ALIASES[a.lower()]

    counts = count_rejected_by_stage(hours)
    total = sum(counts.values())
    if not total:
        await message.answer(f"За последние {hours} ч отклонённых лотов нет.")
        return

    header = [f"🗑 <b>Отклонено за {hours} ч: {total}</b>"]
    for key, title in STAGE_TITLES.items():
        header.append(f" • {title}: {counts.get(key, 0)}")
    shown_title = "все причины" if stage == "all" else STAGE_TITLES[stage]
    header.append(f"\nПоказываю: <b>{shown_title}</b>\n")

    rows = get_rejected(hours, None if stage == "all" else stage, MAX_REJECTED_LINES)
    lines = ["\n".join(header)]
    if not rows:
        lines.append("— нет лотов с этой причиной за выбранный период —")
    for i, r in enumerate(rows, 1):
        label = SOURCE_LABELS.get(r["source"], r["source"])
        reason = f"\n   ↳ {_h(r['reason'] or '')}" if stage in ("all", "rules") else ""
        lines.append(
            f"{i}. <b>{_h(label)}</b> | {_fmt_date(r['rejected_at'])}\n"
            f"   {_h((r['title'] or '—')[:100])} | {_h(r['price'] or '—')}"
            f"{reason}\n"
            f"   {r['url'] or ''}\n"
        )
    shown_total = counts.get(stage, 0) if stage != "all" else total
    if shown_total > len(rows):
        lines.append(f"…показаны {len(rows)} из {shown_total} (самые свежие)")
    await _send_chunks(message, lines)
