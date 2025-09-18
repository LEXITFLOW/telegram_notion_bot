import os, re
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from notion_client import Client

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
BOT_USERS_DB_ID = os.getenv("BOT_USERS_DB_ID")

if not (TOKEN and NOTION_TOKEN and BOT_USERS_DB_ID):
    raise RuntimeError("Перевір .env: TELEGRAM_BOT_TOKEN, NOTION_TOKEN, BOT_USERS_DB_ID")

notion = Client(auth=NOTION_TOKEN)

ASK_EMAIL = 1
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привіт! Надішли свій робочий email у Notion для зв’язування з ботом.")
    return ASK_EMAIL

def _find_notion_user_by_email(email: str):
    # Витягуємо всіх користувачів і шукаємо по email
    users = notion.users.list()
    for u in users.get("results", []):
        pe = u.get("person") or {}
        if pe.get("email", "").lower() == email.lower():
            return u  # має id, name, person.email
    return None

def _upsert_bot_user(notion_user, email: str, chat_id: int):
    # шукаємо існуючий запис за Email
    q = notion.databases.query(
        **{
            "database_id": BOT_USERS_DB_ID,
            "filter": {
                "property": "Email",
                "email": {"equals": email}
            },
            "page_size": 1
        }
    )
    props = {
        "Name": {"title": [{"text": {"content": notion_user.get("name") or email}}]},
        "Email": {"email": email},
        "Notion user": {"people": [{"id": notion_user["id"]}]},
        "Telegram Chat ID": {"number": chat_id},
        "Linked": {"checkbox": True},
    }
    if q.get("results"):
        page_id = q["results"][0]["id"]
        notion.pages.update(page_id=page_id, properties=props)
        return page_id
    else:
        p = notion.pages.create(parent={"database_id": BOT_USERS_DB_ID}, properties=props)
        return p["id"]

async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (update.message.text or "").strip()
    if not EMAIL_RE.match(msg):
        await update.message.reply_text("Не схоже на email. Спробуй ще раз або /cancel.")
        return ASK_EMAIL

    u = _find_notion_user_by_email(msg)
    if not u:
        await update.message.reply_text("Не знайшов такого користувача у Notion. Перевір email або доступ до воркспейсу.")
        return ASK_EMAIL

    chat_id = update.effective_chat.id
    page_id = _upsert_bot_user(u, msg, chat_id)
    await update.message.reply_text("Готово! ✅ Ви зв’язані. Тепер згадки в Notion будуть приходити сюди.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Скасовано.")
    return ConversationHandler.END

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(update.message.text or "")

def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    print("Бот запущено. Ctrl+C щоб зупинити.")
    app.run_polling()

if __name__ == "__main__":
    main()