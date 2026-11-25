"""Fast, on-demand figures from the bot database and the latest Avito snapshot."""
import json
import os
from datetime import datetime, timedelta, timezone

import yaml

from db.database import count_viewed, db_conn
from pipeline.keyword_filter import matched_keywords

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MSK = timezone(timedelta(hours=3))
PLATFORMS = {"meshok": "Мешок", "auction": "Аукцион", "avito": "Авито"}


def load_config() -> dict:
    with open(os.path.join(BASE_DIR, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _platform(source: str) -> str | None:
    return next((name for name in PLATFORMS if source.startswith(name + "_")), None)


def _msk_time(value: str | None) -> str:
    if not value:
        return "нет данных"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MSK).strftime("%d.%m %H:%M")
    except ValueError:
        return "нет данных"


def _avito_snapshot() -> dict | None:
    try:
        with open(os.path.join(BASE_DIR, "logs", "avito_stats.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def recent_found(hours: int = 24) -> list[dict]:
    with db_conn() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM found_lots WHERE found_at >= datetime('now', ?) "
            "ORDER BY found_at DESC, id DESC", (f"-{hours} hours",)
        )]


def important_found(cfg: dict, hours: int = 24) -> list[dict]:
    """Highlight the client's direct keywords without changing alert delivery.

    Historical found_lots stores titles but not descriptions, so this view
    can only classify words visible in the title.
    """
    direct = list(dict.fromkeys((cfg.get("keywords_always") or []) +
                                (cfg.get("keywords_direct") or [])))
    always = cfg.get("keywords_always") or []
    found, seen = [], set()
    for lot in recent_found(hours):
        platform = _platform(lot["source"])
        key = (platform, lot["lot_id"])
        if key in seen:
            continue
        seen.add(key)
        hits = matched_keywords({"title": lot.get("title") or ""}, direct)
        if hits:
            lot["important_keywords"] = hits
            lot["importance"] = 2 if matched_keywords({"title": lot.get("title") or ""}, always) else 1
            found.append(lot)
    found.sort(key=lambda lot: (lot["importance"], lot["found_at"]), reverse=True)
    return found


def stats_text(cfg: dict, hours: int = 24) -> str:
    """Recent unique lots by platform; Avito's viewed count is its last pushed 24h snapshot."""
    with db_conn() as conn:
        found_rows = conn.execute(
            "SELECT source, lot_id FROM found_lots WHERE found_at >= datetime('now', ?)",
            (f"-{hours} hours",)).fetchall()
        rejected_rows = conn.execute(
            "SELECT source, lot_id FROM rejected_lots WHERE rejected_at >= datetime('now', ?)",
            (f"-{hours} hours",)).fetchall()
        runs = conn.execute("SELECT source, last_run_at FROM run_state").fetchall()

    found = {name: set() for name in PLATFORMS}
    rejected = {name: set() for name in PLATFORMS}
    last_run = {}
    for rows, target in ((found_rows, found), (rejected_rows, rejected)):
        for row in rows:
            platform = _platform(row["source"])
            if platform:
                target[platform].add(row["lot_id"])
    for row in runs:
        platform = _platform(row["source"])
        if platform and row["last_run_at"]:
            last_run[platform] = max(last_run.get(platform, ""), row["last_run_at"])

    important = {name: set() for name in PLATFORMS}
    for lot in important_found(cfg, hours):
        platform = _platform(lot["source"])
        if platform:
            important[platform].add(lot["lot_id"])

    avito = _avito_snapshot() if hours == 24 else None
    stamp = datetime.now(MSK).strftime("%d.%m %H:%M")
    lines = [f"📈 <b>Статистика за {hours} ч</b> · {stamp} МСК", ""]
    for platform, label in PLATFORMS.items():
        if platform == "avito":
            viewed = avito.get("viewed") if avito else None
            viewed_label = str(viewed) if viewed is not None else "нет данных"
            run_at = avito.get("ts") if avito else None
        else:
            viewed = count_viewed(platform, hours)
            viewed_label = str(viewed)
            run_at = last_run.get(platform)
        lines.append(f"<b>{label}</b>: просмотрено новых {viewed_label}, "
                     f"отправлено {len(found[platform])}, отсеяно {len(rejected[platform])}, "
                     f"важных {len(important[platform])}")
        lines.append("Последняя проверка: " + (_msk_time(run_at) + " МСК" if run_at else "нет данных"))
    lines += ["", "Важные — лоты со словами из списка прямой отправки в заголовке. Список: /important"]
    return "\n".join(lines)
