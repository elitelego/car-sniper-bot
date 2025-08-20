import os
import sqlite3
from datetime import datetime, timezone
from typing import List, Tuple, Optional

DB_PATH = os.getenv("DB_PATH", "data.db")

_conn = None

def db():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn

def init_db():
    conn = db()
    cur = conn.cursor()
    # Таблица фильтров пользователей
    cur.execute("""
    CREATE TABLE IF NOT EXISTS filters (
        chat_id     INTEGER PRIMARY KEY,
        filters     TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """)
    # Таблица отправленных объявлений
    # Ключ: (chat_id, listing_id, price_eur) — если цена та же, не шлём снова.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sent (
        chat_id     INTEGER NOT NULL,
        listing_id  TEXT    NOT NULL,
        price_eur   INTEGER,
        title       TEXT,
        url         TEXT,
        sent_at     TEXT NOT NULL,
        PRIMARY KEY (chat_id, listing_id, price_eur)
    )
    """)
    conn.commit()

def save_filters(chat_id: int, filters_text: str):
    ts = datetime.now(timezone.utc).isoformat()
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO filters (chat_id, filters, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            filters=excluded.filters,
            updated_at=excluded.updated_at
    """, (chat_id, filters_text, ts))
    conn.commit()

def get_filters(chat_id: int) -> Optional[str]:
    cur = db().cursor()
    cur.execute("SELECT filters FROM filters WHERE chat_id=?", (chat_id,))
    row = cur.fetchone()
    return row["filters"] if row else None

def all_users_filters() -> List[Tuple[int, str]]:
    cur = db().cursor()
    cur.execute("SELECT chat_id, filters FROM filters")
    return [(int(r["chat_id"]), r["filters"]) for r in cur.fetchall()]

def was_already_sent(chat_id: int, listing_id: str, price_eur: Optional[int]) -> bool:
    cur = db().cursor()
    cur.execute("""
        SELECT 1 FROM sent
        WHERE chat_id=? AND listing_id=? AND (price_eur IS ? OR price_eur=?)
        LIMIT 1
    """, (chat_id, listing_id, price_eur, price_eur))
    return cur.fetchone() is not None

def mark_sent(chat_id: int, listing_id: str, price_eur: Optional[int], title: str, url: str):
    ts = datetime.now(timezone.utc).isoformat()
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO sent (chat_id, listing_id, price_eur, title, url, sent_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (chat_id, listing_id, price_eur, title or "", url or "", ts))
    conn.commit()
