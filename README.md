# Telegram - Notion notifier

This project delivers personal Telegram notifications whenever someone is mentioned in Notion comments or page updates.

## What is inside
- **Bot (`bot.py`)** – registers Telegram users, links their email to a Notion database, and stores the chat ID for future pings.
- **Server (`server.py`)** – Flask webhook endpoint that validates Notion signatures, resolves mentioned users, and pushes alerts through the Telegram Bot API.

## Requirements
- Python 3.10+
- Notion integration with access to your workspace and the Bot Users database
- Telegram bot token (from BotFather)

## Environment variables
Copy `.env.example` to `.env` and fill the required secrets:

```
TELEGRAM_BOT_TOKEN=...
NOTION_TOKEN=...
BOT_USERS_DB_ID=...
NOTION_VERIFY_SECRET=...
NOTION_VERIFICATION_TOKEN=...
TELEGRAM_CHAT_ID=           # optional: admin chat notified during webhook verification
# DEDUP_WINDOW_SECONDS=30   # optional override for deduplication window
```

## Local setup
```
python -m venv venv
./venv/Scripts/activate      # on Windows
source venv/bin/activate     # on macOS / Linux
pip install -r requirements.txt
```

### Run the Telegram bot
```
python bot.py
```

### Run the webhook server
```
python server.py
```

Expose the Flask server to Notion (e.g. via Render, ngrok, or another HTTPS endpoint), then configure the webhook in Notion using the verification token and signing secret from your `.env` file.

## Deployment notes
Render is already supported through the included `Procfile`. Make sure the environment variables above are set in your hosting platform and point your Notion webhook to the deployed `/notion/webhook` route.
