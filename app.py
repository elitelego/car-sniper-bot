#!/usr/bin/env python3
import asyncio
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

from scraper.auto24 import fetch_latest_listings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("car-sniper")

DB_PATH = os.environ.get("DB_PATH", "data.db")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

DEFAULT_SITES = ["auto24"]

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        filters_json TEXT NOT NULL,
        sites_json TEXT NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS seen (
        id TEXT PRIMARY KEY,
        first_seen_ts INTEGER NOT NULL
    );
    """)
    conn.commit()
    conn.close()

def now_ts() -> int:
    return int(time.time())

def human_int(x: Optional[int]) -> str:
    if x is None: return "-"
    s = f"{x:,}".replace(",", " ")
    return s

def parse_filters_from_text(text: str) -> Dict[str, Any]:
    # Example: price=2000-6000 year=2006-2020 km<250000 brand=toyota,bmw
    filters = {
        "price_min": None, "price_max": None,
        "year_min": None, "year_max": None,
        "km_max": None,
        "brands": [],
    }
    # price
    m = re.search(r"price\s*=\s*(\d+)\s*-\s*(\d+)", text, re.I)
    if m:
        filters["price_min"] = int(m.group(1))
        filters["price_max"] = int(m.group(2))
    # year
    m = re.search(r"year\s*=\s*(\d{4})\s*-\s*(\d{4})", text, re.I)
    if m:
        filters["year_min"] = int(m.group(1))
        filters["year_max"] = int(m.group(2))
    # km
    m = re.search(r"km\s*[<=]\s*(\d+)", text, re.I)
    if m:
        filters["km_max"] = int(m.group(1))
    # brand(s)
    m = re.search(r"brand[s]?\s*=\s*([A-Za-z0-9 ,\-]+)", text, re.I)
    if m:
        brands = [b.strip().lower() for b in re.split(r"[,\s]+", m.group(1)) if b.strip()]
        filters["brands"] = brands
    return filters

def filter_listing(item: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    # Apply inclusive filters; if a filter is None/empty => ignore that criterion
    price = item.get("price_eur")
    year = item.get("year")
    km = item.get("odometer_km")
    brand = (item.get("brand") or "").lower()

    if filters.get("price_min") is not None and (price is None or price < filters["price_min"]):
        return False
    if filters.get("price_max") is not None and (price is None or price > filters["price_max"]):
        return False
    if filters.get("year_min") is not None and (year is None or year < filters["year_min"]):
        return False
    if filters.get("year_max") is not None and (year is None or year > filters["year_max"]):
        return False
    if filters.get("km_max") is not None and (km is None or km > filters["km_max"]):
        return False
    if filters.get("brands"):
        if brand:
            ok = any(brand.startswith(b) or b in brand for b in filters["brands"])
            if not ok:
                return False
        else:
            return False
    return True

def load_user_filters(chat_id: int) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT filters_json FROM users WHERE chat_id=?", (chat_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {}
    try:
        return json.loads(row["filters_json"])
    except Exception:
        return {}

def save_user(chat_id: int, filters: Dict[str, Any], sites: Optional[List[str]]=None):
    if sites is None:
        sites = DEFAULT_SITES
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO users (chat_id, created_at, filters_json, sites_json) VALUES (?, ?, ?, ?);",
        (chat_id, datetime.now(timezone.utc).isoformat(), json.dumps(filters), json.dumps(sites))
    )
    conn.commit()
    conn.close()

async def send_listing(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE, listing: Dict[str, Any]):
    title = listing.get("title") or "Новое объявление"
    url = listing.get("url")
    price = human_int(listing.get("price_eur"))
    year = listing.get("year")
    km = human_int(listing.get("odometer_km"))
    brand = listing.get("brand") or "-"
    site = listing.get("site") or ""
    text = (
        f"🔔 *{title}*\n"
        f"Марка: *{brand}*  •  Год: *{year or '-'}*  •  Пробег: *{km} км*\n"
        f"Цена: *{price} €*\n"
        f"Источник: *{site}*\n"
        f"[Открыть объявление]({url})"
    )
    try:
        await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Failed to send listing: %s", e)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    default_text = (
        "Привет! Я пришлю тебе новые объявления по твоим фильтрам.\n\n"
        "Задай фильтры командой /filter в формате:\n"
        "`/filter price=2000-6000 year=2006-2020 km<=250000 brand=toyota,bmw,mercedes`"
    )
    await update.message.reply_text(default_text, parse_mode="Markdown")

    # Seed with default demo filters (if provided via env DEFAULT_FILTERS_JSON) else keep empty
    default_filters = os.environ.get("DEFAULT_FILTERS_JSON")
    if default_filters:
        try:
            filters = json.loads(default_filters)
            save_user(chat_id, filters)
            await update.message.reply_text("⚙️ Поставил фильтры по умолчанию. Можно изменить через /filter.")
        except Exception:
            pass

async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    args = text.partition(" ")[2]
    if not args:
        current = load_user_filters(chat_id)
        await update.message.reply_text(
            "Текущие фильтры:\n"
            f"{json.dumps(current, ensure_ascii=False, indent=2)}\n\n"
            "Формат установки:\n"
            "`/filter price=2000-6000 year=2010-2020 km<=250000 brand=toyota,bmw`",
            parse_mode="Markdown"
        )
        return

    filters = parse_filters_from_text(args)
    save_user(chat_id, filters)
    await update.message.reply_text(
        "✅ Обновил фильтры:\n" + json.dumps(filters, ensure_ascii=False, indent=2)
    )

async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OK")

async def scan_and_notify(app: Application):
    """Fetch latest from sources, filter per user, and notify new ones."""
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT chat_id, filters_json, sites_json FROM users")
    users = cur.fetchall()
    conn.close()

    if not users:
        return

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        listings: List[Dict[str, Any]] = []
        try:
            if "auto24" in DEFAULT_SITES:
                items = await fetch_latest_listings(session)
                listings.extend(items)
        except Exception as e:
            logger.exception("Source fetch error: %s", e)

    if not listings:
        return

    # filter per user and deduplicate via 'seen'
    conn = db()
    cur = conn.cursor()
    for user in users:
        chat_id = user["chat_id"]
        try:
            filters = json.loads(user["filters_json"])
        except Exception:
            filters = {}

        for item in listings:
            lid = item.get("id") or item.get("url")
            if not lid:
                continue
            # seen?
            cur.execute("SELECT 1 FROM seen WHERE id=?", (lid,))
            if cur.fetchone():
                continue

            if filter_listing(item, filters):
                # mark as seen + notify
                try:
                    cur.execute("INSERT OR IGNORE INTO seen (id, first_seen_ts) VALUES (?, ?);", (lid, now_ts()))
                    conn.commit()
                except Exception:
                    pass
                try:
                    await send_listing(chat_id, app.bot, item)  # app.bot used to have same ContextTypes
                except Exception as e:
                    logger.exception("Notify error: %s", e)
    conn.close()

async def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN env var is required")

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("filter", cmd_filter))
    application.add_handler(CommandHandler("health", health))

    # Scheduler: scan every 60 seconds
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(scan_and_notify, "interval", seconds=int(os.environ.get("SCAN_INTERVAL", "60")), args=[application])
    scheduler.start()

    # Start the bot (long-polling)
    await application.initialize()
    await application.start()
    logger.info("Bot started. Polling...")
    try:
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        # Keep running
        while True:
            await asyncio.sleep(3600)
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
