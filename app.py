#!/usr/bin/env python3
import asyncio
import logging
import os
from typing import List, Dict, Any

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)

from db import init_db, save_filters, get_filters
from scraper.auto24 import fetch_latest_listings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("car-sniper")

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))

# --- Простые шаги фильтрации (как раньше) ---
BRANDS = ["Toyota", "BMW", "Mercedes-Benz", "Audi", "Volkswagen",
          "Skoda", "Volvo", "Honda", "Ford", "Nissan",
          "Hyundai", "Kia", "Peugeot", "Opel", "Mazda"]

user_state: Dict[int, Dict[str, Any]] = {}  # временное хранилище ответов

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я пришлю тебе новые объявления по твоим фильтрам.\n"
        "Настроить фильтры: /filter"
    )

async def filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    user_state[uid] = {}
    await update.message.reply_text("Введите диапазон цены, например: 2000-6000")

async def price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state:
        return
    user_state[uid]["price"] = (update.message.text or "").strip()
    await update.message.reply_text("Введите диапазон годов выпуска, например: 2006-2020")

async def year_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state:
        return
    user_state[uid]["year"] = (update.message.text or "").strip()
    await update.message.reply_text("Введите максимальный пробег, например: 250000")

async def km_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in user_state:
        return
    user_state[uid]["km"] = (update.message.text or "").strip()

    # Кнопки-«чекбоксы» брендов + Сохранить
    keyboard = []
    row = []
    for i, b in enumerate(BRANDS, start=1):
        row.append(InlineKeyboardButton(b, callback_data=f"brand:{b}"))
        if i % 3 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("Сохранить ✅", callback_data="SAVE"),
                     InlineKeyboardButton("Отмена ❌", callback_data="CANCEL")])
    await update.message.reply_text("Выберите бренды (можно несколько):", reply_markup=InlineKeyboardMarkup(keyboard))

async def brands_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user_state.setdefault(uid, {})
    user_state[uid].setdefault("brands", [])

    data = q.data or ""
    if data == "CANCEL":
        user_state.pop(uid, None)
        await q.edit_message_text("Отменено.")
        return

    if data == "SAVE":
        # Сохраняем прям простой текст (как ты делал раньше). Можно поменять на JSON.
        f = user_state.get(uid, {})
        filters_text = f"{f.get('price','')}" \
                       f"|{f.get('year','')}" \
                       f"|{f.get('km','')}" \
                       f"|{','.join(f.get('brands', []))}"
        save_filters(uid, filters_text)
        user_state.pop(uid, None)
        await q.edit_message_text("Фильтры сохранены ✅")
        return

    if data.startswith("brand:"):
        b = data.split(":", 1)[1]
        if b in user_state[uid]["brands"]:
            user_state[uid]["brands"].remove(b)
        else:
            user_state[uid]["brands"].append(b)

        # Отрисуем список выбранных брендов
        chosen = ", ".join(user_state[uid]["brands"]) or "ничего"
        try:
            await q.edit_message_text(
                f"Выбранные бренды: {chosen}\n"
                f"Нажми «Сохранить ✅», когда закончишь.",
                reply_markup=q.message.reply_markup  # оставить те же кнопки
            )
        except Exception:
            pass

# --- Планировщик: регулярный скан и рассылка ---
async def scan_job(context: ContextTypes.DEFAULT_TYPE):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        try:
            listings: List[Dict[str, Any]] = await fetch_latest_listings(session)
        except Exception as e:
            logger.exception("Fetch error: %s", e)
            return

    if not listings:
        logger.info("Новых объявлений нет")
        return

    # выведем первые 3 URL для контроля
    preview = ", ".join([l.get("url","") for l in listings[:3]])
    logger.info("Найдено объявлений: %d. Примеры: %s", len(listings), preview)

    # TODO: здесь фильтруем по БД и шлём пользователям подходящие варианты

    # 2) создаём HTTP-сессию и передаём её в парсер
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        try:
            listings: List[Dict[str, Any]] = await fetch_latest_listings(session)
        except Exception as e:
            logger.exception("Fetch error: %s", e)
            return

    # 3) пока просто логируем кол-во; сюда добавишь фильтрацию и рассылку
    if listings:
        logger.info("Найдено объявлений: %d", len(listings))
    else:
        logger.info("Новых объявлений нет")

def build_app() -> "Application":
    if not TELEGRAM_TOKEN:
        raise SystemExit("Set BOT_TOKEN (or TELEGRAM_TOKEN) env var")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("filter", filter_cmd))
    # Три шага текстом подряд — простейший вариант;
    # при желании можно заменить на ConversationHandler.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, price_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, year_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, km_handler))
    app.add_handler(CallbackQueryHandler(brands_button))

    # Планировщик (JobQueue) — заменяет самописный while True
    app.job_queue.run_repeating(scan_job, interval=SCAN_INTERVAL, first=5)
    return app

def main():
    init_db()
    app = build_app()
    # Самый простой и правильный запуск для PTB 20/21:
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
