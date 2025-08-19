import os, re, logging, aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters
from db import init_db, save_filters, get_filters, all_users_filters
from scraper.auto24 import fetch_latest_listings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL","60"))
PRICE,YEAR,KM,BRANDS=range(4)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Используй /filter для настройки фильтров.")

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__=='__main__': main()
