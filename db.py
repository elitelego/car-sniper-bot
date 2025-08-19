import sqlite3

DB_PATH = "filters.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_filters (
            user_id INTEGER PRIMARY KEY,
            filters TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_filters(user_id, filters_text):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO user_filters (user_id, filters)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET filters=excluded.filters
    ''', (user_id, filters_text))
    conn.commit()
    conn.close()

def get_filters(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT filters FROM user_filters WHERE user_id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None
