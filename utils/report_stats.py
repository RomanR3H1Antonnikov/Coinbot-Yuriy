"""Figures shared by the daily report: lots viewed per platform and photo quality of alerts.
Avito runs on another machine, so its figures come in as `extra` (the pushed snapshot)."""
from db.database import count_viewed
from utils import run_journal

NAMES = {"meshok": "Мешок", "auction": "Аукцион", "avito": "Авито"}


def photo_counts(platform: str, hours: int = 24) -> dict:
    """Alerts by how their picture was sent: uploaded big, uploaded small, via link (download
    failed, Telegram shows a tiny preview), or the lot has no photo at all."""
    mine = [r for r in run_journal.read(hours, "photo:") if r["src"][len("photo:"):].startswith(platform)]
    return {
        "alerts": len(mine),
        "small": sum(1 for r in mine if r["mode"] == "upload" and r.get("small")),
        "link": sum(1 for r in mine if r["mode"] == "url"),
        "none": sum(1 for r in mine if r["mode"] == "none"),
    }


def viewed_block(platforms: list[str], extra: dict[str, int | None] | None = None, hours: int = 24) -> str:
    """New lots the scraper looked at per platform. 0 means the platform was not read at all;
    None (extra only) means no data came in."""
    lines = []
    for p in platforms:
        n = (extra or {})[p] if extra and p in extra else count_viewed(p, hours)
        if n is None:
            lines.append(f"{NAMES[p]}: нет данных  ⚠️")
        else:
            lines.append(f"{NAMES[p]}: {n}" + ("  ⚠️ 0 — проверьте, нет ли сбоя" if n == 0 else ""))
    return "<b>Просмотрено новых лотов за сутки</b>\n" + "\n".join(lines)


def photo_block(platforms: list[str], extra: dict[str, dict | None] | None = None, hours: int = 24) -> str:
    lines = []
    for p in platforms:
        c = (extra or {})[p] if extra and p in extra else photo_counts(p, hours)
        if c is None:
            lines.append(f"{NAMES[p]}: нет данных")
        elif not c["alerts"]:
            lines.append(f"{NAMES[p]}: алертов не было")
        else:
            lines.append(f"{NAMES[p]}: алертов {c['alerts']}, маленькое фото {c['small']}, "
                         f"ссылкой {c['link']}, без фото {c['none']}")
    return "<b>Фото в алертах</b>\n" + "\n".join(lines)
