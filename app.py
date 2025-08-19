import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from db import init_db, save_filters, get_filters
from scraper.auto24 import fetch_latest_listings
import config

init_db()

BRANDS = ["Toyota", "BMW", "Mercedes", "Skoda", "VW", "Audi",
          "Ford", "Nissan", "Honda", "Opel", "Renault", "Mazda",
          "Kia", "Hyundai", "Peugeot"]

user_data = {}  # временно хранит ввод пользователя по шагам

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я пришлю тебе новые объявления по твоим фильтрам.\n"
        "Настроить фильтры: /filter"
    )

async def filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data[user_id] = {}
    await update.message.reply_text("Введите диапазон цены в формате: 2000-6000")
    return

async def price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data:
        return
    user_data[user_id]["price"] = update.message.text
    await update.message.reply_text("Введите диапазон годов выпуска: 2006-2020")
    return

async def year_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data[user_id]["year"] = update.message.text
    await update.message.reply_text("Введите максимальный пробег, например: 250000")
    return

async def km_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data[user_id]["km"] = update.message.text

    # Создаем кнопки для брендов
    keyboard = []
    for brand in BRANDS:
        keyboard.append([InlineKeyboardButton(brand, callback_data=brand)])
    keyboard.append([InlineKeyboardButton("Сохранить ✅", callback_data="SAVE")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите бренды (можно несколько):", reply_markup=reply_markup)
    return

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if user_id not in user_data:
        user_data[user_id] = {}

    if query.data == "SAVE":
        # Сохраняем фильтры в БД
        filters_text = f"{user_data[user_id]['price']}|{user_data[user_id]['year']}|{user_data[user_id]['km']}|{','.join(user_data[user_id].get('brands', []))}"
        save_filters(user_id, filters_text)
        await query.edit_message_text(text="Фильтры сохранены ✅")
        user_data.pop(user_id)
    else:
        if "brands" not in user_data[user_id]:
            user_data[user_id]["brands"] = []
        if query.data not in user_data[user_id]["brands"]:
            user_data[user_id]["brands"].append(query.data)
        await query.edit_message_text(text=f"Выбранные бренды: {', '.join(user_data[user_id]['brands'])}\nНажмите 'Сохранить ✅', когда закончите")

async def main_loop():
    while True:
        listings = await fetch_latest_listings()
        # Тут можно проверить фильтры каждого пользователя и отправить новые объявления
        await asyncio.sleep(60)

async def main():
    app = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("filter", filter_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, price_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, year_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, km_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    loop = asyncio.get_event_loop()
    loop.create_task(main_loop())

    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())
