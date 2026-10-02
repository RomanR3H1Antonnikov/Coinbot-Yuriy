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
