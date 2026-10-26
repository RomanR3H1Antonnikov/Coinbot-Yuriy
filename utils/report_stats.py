"""Figures shared by the daily reports: lots viewed per platform and photo quality of alerts."""
from db.database import count_viewed
from utils import run_journal

NAMES = {"meshok": "Мешок", "auction": "Аукцион", "avito": "Авито"}


def viewed_block(platforms: list[str], hours: int = 24) -> str:
    """New lots the scraper looked at per platform. 0 means the platform was not read at all."""
    lines = []
    for p in platforms:
        n = count_viewed(p, hours)
        lines.append(f"{NAMES[p]}: {n}" + ("  ⚠️ 0 — проверьте, нет ли сбоя" if n == 0 else ""))
    return "<b>Просмотрено новых лотов за сутки</b>\n" + "\n".join(lines)


def photo_block(platforms: list[str], hours: int = 24) -> str:
    """Alerts by how their picture was sent: uploaded (big), small, via link (Telegram fetched
    it, usually a tiny preview), or no photo on the lot at all."""
    recs = run_journal.read(hours, "photo:")
    lines = []
    for p in platforms:
        mine = [r for r in recs if r["src"][len("photo:"):].startswith(p)]
        if not mine:
            lines.append(f"{NAMES[p]}: алертов не было")
            continue
        small = sum(1 for r in mine if r["mode"] == "upload" and r.get("small"))
        link = sum(1 for r in mine if r["mode"] == "url")
        none = sum(1 for r in mine if r["mode"] == "none")
        lines.append(f"{NAMES[p]}: алертов {len(mine)}, маленькое фото {small}, ссылкой {link}, без фото {none}")
    return "<b>Фото в алертах</b>\n" + "\n".join(lines)
