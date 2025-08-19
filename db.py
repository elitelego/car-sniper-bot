import os
import sqlite3
from typing import List, Tuple, Optional

DB_PATH = os.getenv("DB_PATH", "filters.db")

def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_filters (
            user_id INTEGER PRIMARY KEY,
            filters TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_filters(user_id: int, filters: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('REPLACE INTO user_filters (user_id, filters) VALUES (?, ?)', (user_id, filters))
    conn.commit()
    conn.close()

def get_filters(user_id: int) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT filters FROM user_filters WHERE user_id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def all_users_filters() -> List[Tuple[int, str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT user_id, filters FROM user_filters')
    rows = c.fetchall()
    conn.close()
    return rows
