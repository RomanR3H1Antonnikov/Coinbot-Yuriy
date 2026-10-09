import sqlite3
import os
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "coinbot.db")

CREATE_SEEN_LOTS = """
CREATE TABLE IF NOT EXISTS seen_lots (
    lot_id      TEXT NOT NULL,
    source      TEXT NOT NULL,
    first_seen  TIMESTAMP DEFAULT (datetime('now')),
    PRIMARY KEY (lot_id, source)
)
"""

CREATE_FOUND_LOTS = """
CREATE TABLE IF NOT EXISTS found_lots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id      TEXT NOT NULL,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT,
    price       TEXT,
    photo_url   TEXT,
    summary     TEXT,
    found_at    TIMESTAMP DEFAULT (datetime('now'))
)
"""

CREATE_RUN_STATE = """
CREATE TABLE IF NOT EXISTS run_state (
    source          TEXT PRIMARY KEY,
    last_run_at     TIMESTAMP
)
"""


CREATE_REJECTED_LOTS = """
CREATE TABLE IF NOT EXISTS rejected_lots (
    lot_id      TEXT NOT NULL,
    source      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    reason      TEXT,
    url         TEXT,
    title       TEXT,
    price       TEXT,
    rejected_at TIMESTAMP DEFAULT (datetime('now')),
    PRIMARY KEY (lot_id, source)
)
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_conn():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_conn() as conn:
        conn.execute(CREATE_SEEN_LOTS)
        conn.execute(CREATE_FOUND_LOTS)
        conn.execute(CREATE_RUN_STATE)
        conn.execute(CREATE_REJECTED_LOTS)


def save_rejected(rows: list[tuple[dict, str, str]]):
    """rows: (lot, stage, reason). First rejection wins, so a lot stays in the
    report for the day it was first rejected."""
    if not rows:
        return
    with db_conn() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO rejected_lots
               (lot_id, source, stage, reason, url, title, price)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (lot["lot_id"], lot["source"], stage, reason,
                 lot.get("url"), lot.get("title"), lot.get("price"))
                for lot, stage, reason in rows
            ],
        )


def get_decided_ids(source: str) -> set[str]:
    """Lots already rejected by the LLM or jubilee check: not worth paying to re-check."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT lot_id FROM rejected_lots WHERE source=? AND stage IN ('llm', 'jubilee')",
            (source,),
        ).fetchall()
        return {r["lot_id"] for r in rows}


def get_rejected(hours: int, stage: str | None = None, limit: int = 150) -> list[dict]:
    query = "SELECT * FROM rejected_lots WHERE rejected_at >= datetime('now', ?)"
    params: list = [f"-{int(hours)} hours"]
    if stage:
        query += " AND stage=?"
        params.append(stage)
    query += " ORDER BY rejected_at DESC LIMIT ?"
    params.append(limit)
    with db_conn() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def count_rejected_by_stage(hours: int) -> dict[str, int]:
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT stage, COUNT(*) AS n FROM rejected_lots
               WHERE rejected_at >= datetime('now', ?) GROUP BY stage""",
            (f"-{int(hours)} hours",),
        ).fetchall()
        return {r["stage"]: r["n"] for r in rows}


def purge_rejected(days: int = 30):
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM rejected_lots WHERE rejected_at < datetime('now', ?)",
            (f"-{int(days)} days",),
        )


def is_seen(lot_id: str, source: str) -> bool:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_lots WHERE lot_id=? AND source=?", (lot_id, source)
        ).fetchone()
        return row is not None


def mark_seen(lot_id: str, source: str):
    with db_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_lots (lot_id, source) VALUES (?, ?)",
            (lot_id, source),
        )


def save_found_lot(lot: dict):
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO found_lots (lot_id, source, url, title, price, photo_url, summary)
               VALUES (:lot_id, :source, :url, :title, :price, :photo_url, :summary)""",
            lot,
        )


def get_last_found_lots(n: int = 20) -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM found_lots ORDER BY found_at DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_last_run_at(source: str):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT last_run_at FROM run_state WHERE source=?", (source,)
        ).fetchone()
        return row["last_run_at"] if row else None


def set_last_run_at(source: str, ts: str):
    with db_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO run_state (source, last_run_at) VALUES (?, ?)",
            (source, ts),
        )
