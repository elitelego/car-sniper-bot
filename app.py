#!/usr/bin/env python3
import logging
import os
import re
from typing import Dict, Any, List, Tuple, Optional

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, ConversationHandler, filters
)

from db import init_db, save_filters, get_filters, all_users_filters
from scraper.auto24 import fetch_latest_listings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("car-sniper")

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))

# Состояния мастера
PRICE, YEAR, KM, BRANDS = range(4)

# 15 популярных брендов
BRANDS_ALL = [
    "Toyota","BMW","Mercedes-Benz","Audi","Volkswagen",
    "Skoda","Volvo","Honda","Ford","Nissan",
    "Hyundai","Kia","Peugeot","Opel","Mazda"
]

# Простая защита от повторов (на период жизни процесса)
SEEN: set[str] = set()

async def brands_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data.startswith("brand:"):
        brand = data.split(":", 1)[1]
        sel = context.user_data["filt"].get("brands", [])
        nb = normalize_brand(brand)
        if nb in sel:
            sel.remove(nb)
        else:
            sel.append(nb)
        context.user_data["filt"]["brands"] = sel
        await q.edit_message_reply_markup(reply_markup=brands_keyboard(sel))
        return BRANDS

    if data == "confirm:cancel":
        await q.edit_message_text("Отменено.")
        return ConversationHandler.END

    if data == "confirm:save":
        # ⚡️ вот здесь мы объявляем f, чтобы не было NameError
        f = context.user_data.get("filt", {})

        price_s  = f"{f.get('price_min','')}-{f.get('price_max','')}"
        year_s   = f"{f.get('year_min','')}-{f.get('year_max','')}"
        km_s     = f"{f.get('km_max','')}"
        brands_s = ",".join(f.get("brands", []))

        s = f"{price_s}|{year_s}|{km_s}|{brands_s}"
        save_filters(q.message.chat_id, s)

        await q.edit_message_text("✅ Фильтр сохранён!")
        return ConversationHandler.END


def brands_keyboard(selected: List[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(BRANDS_ALL), 3):
        row = []
        for b in BRANDS_ALL[i:i+3]:
            mark = "✅" if normalize_brand(b) in selected else "▫️"
            row.append(InlineKeyboardButton(f"{mark} {b}", callback_data=f"brand:{b}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("✅ Сохранить", callback_data="confirm:save"),
        InlineKeyboardButton("❌ Отмена",   callback_data="confirm:cancel")
    ])
    return InlineKeyboardMarkup(rows)

def fmt_int(x: Optional[int]) -> str:
    if x is None:
        return "-"
    return f"{x:,}".replace(",", " ")

def parse_filters_text(s: str) -> Dict[str, Any]:
    # формат: "2000-6000|2006-2020|250000|toyota,bmw"
    out = {"price_min":None,"price_max":None,"year_min":None,"year_max":None,"km_max":None,"brands":[]}
    if not s:
        return out
    parts = s.split("|")
    # price
    if len(parts) > 0 and parts[0]:
        m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", parts[0])
        if m:
            out["price_min"] = int(m.group(1)); out["price_max"] = int(m.group(2))
    # year
    if len(parts) > 1 and parts[1]:
        m = re.match(r"^\s*(\d{4})\s*-\s*(\d{4})\s*$", parts[1])
        if m:
            out["year_min"] = int(m.group(1)); out["year_max"] = int(m.group(2))
    # km
    if len(parts) > 2 and parts[2]:
        try:
            out["km_max"] = int(parts[2].strip())
        except:
            pass
    price_s  = f"{f.get('price_min','')}-{f.get('price_max','')}"
year_s   = f"{f.get('year_min','')}-{f.get('year_max','')}"
km_s     = f"{f.get('km_max','')}"
brands_s = ",".join(f.get("brands", []))
s = f"{price_s}|{year_s}|{km_s}|{brands_s}"

