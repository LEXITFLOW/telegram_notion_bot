import os, time, hmac, hashlib, json
from typing import List, Tuple
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from notion_client import Client
from notion_client.errors import APIResponseError
import httpx

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NOTION_TOKEN        = os.getenv("NOTION_TOKEN")
BOT_USERS_DB_ID     = os.getenv("BOT_USERS_DB_ID")

if not (TELEGRAM_BOT_TOKEN and NOTION_TOKEN and BOT_USERS_DB_ID):
    raise RuntimeError("Перевір .env: TELEGRAM_BOT_TOKEN, NOTION_TOKEN, BOT_USERS_DB_ID")

app = Flask(__name__)
notion = Client(auth=NOTION_TOKEN)

# антидубль 30с
RECENT = {}
DEDUP_WINDOW = 30.0

def dedup_key(page_id: str, notion_user_id: str, event: str) -> str:
    return f"{page_id}:{notion_user_id}:{event}"

def pass_dedup(pk: str) -> bool:
    now = time.time()
    last = RECENT.get(pk, 0)
    if now - last < DEDUP_WINDOW:
        return False
    RECENT[pk] = now
    return True

def tg_send(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
    with httpx.Client(timeout=10) as s:
        r = s.post(url, data=data)
        r.raise_for_status()

def get_page_title_url(page_id: str) -> Tuple[str, str]:
    page = notion.pages.retrieve(page_id=page_id)
    title = ""
    for _, prop in (page.get("properties") or {}).items():
        if prop.get("type") == "title" and prop.get("title"):
            title = "".join(t.get("plain_text","") for t in prop["title"]).strip()
            break
    if not title: title = "Notion page"
    url = page.get("url") or f"https://notion.so/{page_id.replace('-','')}"
    return title, url

def find_bot_user_chat_by_email(email: str) -> int | None:
    q = notion.databases.query(
        **{
            "database_id": BOT_USERS_DB_ID,
            "filter": {
                "and": [
                    {"property": "Email", "email": {"equals": email}},
                    {"property": "Linked", "checkbox": {"equals": True}},
                ]
            },
            "page_size": 1
        }
    )
    results = q.get("results", [])
    if not results: return None
    props = results[0].get("properties", {})
    chat = props.get("Telegram Chat ID", {}).get("number")
    return int(chat) if chat else None

def emails_for_notion_user_ids(user_ids: List[str]) -> List[str]:
    emails = []
    for uid in user_ids:
        try:
            u = notion.users.retrieve(user_id=uid)
            pe = u.get("person") or {}
            if pe.get("email"): emails.append(pe["email"])
        except APIResponseError:
            continue
    return emails

def extract_mentions_from_rich_text(rich: list) -> List[str]:
    ids = []
    for r in rich or []:
        m = r.get("mention")
        if not m: 
            if r.get("type") == "mention":
                m = r.get("mention")
        if not m: 
            continue
        if m.get("type") == "user":
            u = m.get("user") or {}
            uid = u.get("id")
            if uid: ids.append(uid)
    return list(dict.fromkeys(ids))

def handle_comment_event(evt: dict):
    page_id = (evt.get("parent") or {}).get("page_id") or (evt.get("context") or {}).get("page_id")
    if not page_id:
        page_id = (evt.get("discussion") or {}).get("parent", {}).get("page_id")
    rich = evt.get("rich_text") or []
    mentioned_ids = extract_mentions_from_rich_text(rich)
    if not (page_id and mentioned_ids):
        return
    title, url = get_page_title_url(page_id)
    snippet = "".join((x.get("plain_text","") for x in rich))[:200]
    for uid in mentioned_ids:
        for email in emails_for_notion_user_ids([uid]):
            chat = find_bot_user_chat_by_email(email)
            if not chat: 
                continue
            key = dedup_key(page_id, uid, "comment")
            if not pass_dedup(key): 
                continue
            tg_send(chat, f"🔔 Тебе згадали в коментарі\n<b>{title}</b>\n{url}\n\n💬 {snippet}")

def handle_page_updated_event(evt: dict):
    page_id = (evt.get("page") or {}).get("id") or (evt.get("resource") or {}).get("id")
    if not page_id:
        return
    rich = evt.get("rich_text") or []
    mentioned_ids = extract_mentions_from_rich_text(rich)
    if not mentioned_ids:
        return
    title, url = get_page_title_url(page_id)
    for uid in mentioned_ids:
        for email in emails_for_notion_user_ids([uid]):
            chat = find_bot_user_chat_by_email(email)
            if not chat: 
                continue
            key = dedup_key(page_id, uid, "page_mention")
            if not pass_dedup(key): 
                continue
            tg_send(chat, f"🔔 Тебе згадали на сторінці\n<b>{title}</b>\n{url}")

@app.post("/notion/webhook")
def notion_webhook():
    raw = request.get_data()
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        body = {}
    if "challenge" in body:
        token = (request.headers.get("X-Notion-Verification-Token")
             or body.get("verificationToken")
             or body.get("verification_token"))
        print(f"!!! NOTION VERIFY TOKEN: {token} !!!")
        return jsonify({"challenge": body["challenge"]}), 200

    events = body.get("events") or [body]
    for e in events:
        etype = e.get("type") or e.get("event_type") or ""
        if "comment" in etype:
            handle_comment_event(e)
        elif "page" in etype and "updated" in etype:
            handle_page_updated_event(e)
    return jsonify({"ok": True}), 200

@app.get("/")
def health():
    return "OK"

if __name__ == "__main__":
    print("Запускаємо Flask сервер...")
    app.run(host="127.0.0.1", port=3000, debug=True)