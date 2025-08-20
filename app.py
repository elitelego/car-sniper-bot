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

from db import init_db, save_filters, all_users_filters
from scraper.auto24 import fetch_latest_listings, debug_fetch

# ------------ ЛОГИРОВАНИЕ ------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("car-sniper")

# ------------ НАСТРОЙКИ ------------
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "120"))  # 2 минуты по умолчанию

# Состояния мастера
PRICE, YEAR, KM, BRANDS = range(4)

# 15 популярных брендов
BRANDS_ALL = [
    "Toyota","BMW","Mercedes-Benz","Audi","Volkswagen",
    "Skoda","Volvo","Honda","Ford","Nissan",
    "Hyundai","Kia","Peugeot","Opel","Mazda"
]

# Защита от повторной рассылки (на время жизни процесса)
SEEN: set = set()

# ------------ ВСПОМОГАТЕЛЬНЫЕ ------------
def normalize_brand(b: str) -> str:
    lb = (b or "").strip().lower()
    if lb in ["vw", "volkswagen"]:
        return "Volkswagen"
    if "mercedes" in lb:
        return "Mercedes-Benz"
    for x in BRANDS_ALL:
        if x.lower() == lb:
            return x
    return (b or "").strip()

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
    # строка формата: "2000-6000|2006-2020|250000|toyota,bmw"
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
    # brands
    if len(parts) > 3 and parts[3]:
        brands = [normalize_brand(b) for b in re.split(r"[,\s]+", parts[3]) if b.strip()]
        out["brands"] = brands
    return out

def is_match(item: Dict[str, Any], f: Dict[str, Any]) -> bool:
    """
    Мягкая фильтрация:
    - если поле в объявлении не распознано (None) — НЕ отбрасываем по нему
    - бренды проверяем только если пользователь их выбирал
    """
    price = item.get("price_eur")
    year  = item.get("year")
    km    = item.get("odometer_km")
    brand = normalize_brand(item.get("brand") or "")

    # Цена
    if f["price_min"] is not None and price is not None and price < f["price_min"]:
        return False
    if f["price_max"] is not None and price is not None and price > f["price_max"]:
        return False

    # Год
    if f["year_min"] is not None and year is not None and year < f["year_min"]:
        return False
    if f["year_max"] is not None and year is not None and year > f["year_max"]:
        return False

    # Пробег
    if f["km_max"] is not None and km is not None and km > f["km_max"]:
        return False

    # Бренды (строгая проверка только если указаны)
    if f["brands"]:
        if not brand or brand not in f["brands"]:
            return False

    return True

# ------------ ОТПРАВКА ------------
async def send_listing(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE, listing: Dict[str, Any]):
    title = listing.get("title") or "Новое объявление"
    url   = listing.get("url") or ""
    price = fmt_int(listing.get("price_eur"))
    year  = listing.get("year")
    km    = fmt_int(listing.get("odometer_km"))
    brand = listing.get("brand") or "-"
    site  = listing.get("site") or "auto24.ee"
    text = (
        f"🔔 *{title}*\n"
        f"Марка: *{brand}*  •  Год: *{year or '-'}*  •  Пробег: *{km} км*\n"
        f"Цена: *{price} €*\n"
        f"Источник: *{site}*\n"
        f"[Открыть объявление]({url})"
    )
    await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", disable_web_page_preview=True)

# ------------ КОМАНДЫ ------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я пришлю тебе новые объявления по твоим фильтрам.\n\n"
        "🔧 Набери /filter чтобы настроить фильтры пошагово.\n"
        "Для проверки парсера: /debug\n"
        "Для отладки сети/HTML: /debugraw"
    )

async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш chat_id: {update.effective_chat.id}")

async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручная проверка парсера: пришлём в чат первые 3 объявления без фильтрации."""
    await update.message.reply_text("⏳ Проверяю auto24…")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
        try:
            listings = await fetch_latest_listings(session)
        except Exception as e:
            logger.exception("Debug fetch error: %s", e)
            await update.message.reply_text(f"❌ Ошибка парсера: {e}")
            return

    if not listings:
        await update.message.reply_text("⚠️ Парсер вернул 0 объявлений.")
        return

    preview = listings[:3]
    for it in preview:
        url = it.get("url", "")
        title = it.get("title") or "Объявление"
        price = it.get("price_eur")
        year = it.get("year")
        km = it.get("odometer_km")
        brand = it.get("brand") or "-"
        text = (
            f"🔎 *Проверка*\n"
            f"{title}\n"
            f"Марка: {brand} • Год: {year} • Пробег: {km} • Цена: {price} €\n"
            f"[Открыть]({url})"
        )
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            logger.exception("Debug send failed: %s", e)

    await update.message.reply_text(f"✅ Нашёл {len(listings)} объявлений. Показал первые {len(preview)}.")

async def cmd_debugraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отладка сети и HTML: покажем статусы, размер, кол-во ссылок и первые URL."""
    await update.message.reply_text("🔧 Смотрю сеть/HTML auto24…")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
        try:
            diag = await debug_fetch(session)
        except Exception as e:
            logger.exception("DebugRaw error: %s", e)
            await update.message.reply_text(f"❌ Ошибка запроса: {e}")
            return

    txt = (
        f"🌐 Источники:\n"
        f"- desktop: status {diag['desktop_status']}, html {diag['desktop_len']} байт, ссылок {diag['desktop_links']}\n"
        f"- mobile:  status {diag['mobile_status']},  html {diag['mobile_len']} байт, ссылок {diag['mobile_links']}\n"
        f"Примеры ссылок:\n" + ("\n".join(diag["sample_links"]) if diag["sample_links"] else "—")
    )
    await update.message.reply_text(txt[:3900], disable_web_page_preview=True)

# ------------ МАСТЕР ФИЛЬТРОВ ------------
async def filter_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["filt"] = {"price_min": None,"price_max": None,"year_min": None,"year_max": None,"km_max": None,"brands": []}
    await update.message.reply_text("Укажи диапазон цены (например: 2000-6000):")
    return PRICE

async def filter_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip().replace(" ", "")
    m = re.match(r"^(\d+)-(\d+)$", t)
    if not m:
        await update.message.reply_text("Формат не распознан. Пример: 2000-6000\nПопробуй ещё раз:")
        return PRICE
    pmin, pmax = int(m.group(1)), int(m.group(2))
    if pmin > pmax: pmin, pmax = pmax, pmin
    context.user_data["filt"]["price_min"] = pmin
    context.user_data["filt"]["price_max"] = pmax
    await update.message.reply_text("Укажи годы выпуска (например: 2006-2020):")
    return YEAR

async def filter_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip().replace(" ", "")
    m = re.match(r"^(\d{4})-(\d{4})$", t)
    if not m:
        await update.message.reply_text("Формат не распознан. Пример: 2006-2020\nПопробуй ещё раз:")
        return YEAR
    ymin, ymax = int(m.group(1)), int(m.group(2))
    if ymin > ymax: ymin, ymax = ymax, ymin
    context.user_data["filt"]["year_min"] = ymin
    context.user_data["filt"]["year_max"] = ymax
    await update.message.reply_text("Максимальный пробег в км (пример: 250000):")
    return KM

async def filter_km(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip().replace(" ", "")
    if not t.isdigit():
        await update.message.reply_text("Нужно число, пример: 250000\nПопробуй ещё раз:")
        return KM
    context.user_data["filt"]["km_max"] = int(t)
    selected = context.user_data["filt"].get("brands", [])
    await update.message.reply_text(
        "Выбери марки (нажимай, чтобы отметить/снять), затем нажми «✅ Сохранить».",
        reply_markup=brands_keyboard(selected)
    )
    return BRANDS

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
        f = context.user_data.get("filt", {})
        price_s  = f"{f.get('price_min','')}-{f.get('price_max','')}"
        year_s   = f"{f.get('year_min','')}-{f.get('year_max','')}"
        km_s     = f"{f.get('km_max','')}"
        brands_s = ",".join(f.get("brands", []))
        s = f"{price_s}|{year_s}|{km_s}|{brands_s}"

        chat_id = q.message.chat.id
        save_filters(chat_id, s)

        await q.edit_message_text("✅ Фильтр сохранён!")
        return ConversationHandler.END

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END

# ------------ СКАН И РАССЫЛКА ------------
async def scan_job(context: ContextTypes.DEFAULT_TYPE):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
        try:
            listings = await fetch_latest_listings(session)
        except Exception as e:
            logger.exception("Fetch error: %s", e)
            return

    if not listings:
        logger.info("Новых объявлений нет")
        return

    logger.info("Найдено объявлений: %d. Пример: %s", len(listings), listings[0].get("url",""))

    users: List[Tuple[int, str]] = all_users_filters()
    for user_id, filt_text in users:
        f = parse_filters_text(filt_text or "")
        matched = 0
        for it in listings:
            lid = it.get("id") or it.get("url")
            if not lid or lid in SEEN:
                continue
            if is_match(it, f):
                try:
                    await send_listing(user_id, context, it)
                    SEEN.add(lid)
                    matched += 1
                except Exception as e:
                    logger.exception("Send failed to %s: %s", user_id, e)
        logger.info("Для chat_id=%s подошло объявлений: %d", user_id, matched)

# ------------ СБОРКА И ЗАПУСК ------------
def build_app():
    if not BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN env var")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("filter", filter_entry)],
        states={
            PRICE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_price)],
            YEAR:   [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_year)],
            KM:     [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_km)],
            BRANDS: [CallbackQueryHandler(brands_toggle)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("debugraw", cmd_debugraw))
    app.add_handler(conv)

    # Планировщик: не допускаем одновременных запусков и объединяем «пропуски»
    app.job_queue.run_repeating(
        scan_job,
        interval=SCAN_INTERVAL,
        first=5,
        job_kwargs={"max_instances": 1, "coalesce": True, "misfire_grace_time": 60},
    )
    return app

def main():
    init_db()
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
