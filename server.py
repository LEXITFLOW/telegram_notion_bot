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
NOTION_VERIFY_SECRET= os.getenv("NOTION_VERIFY_SECRET", "")


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

def check_notion_signature(req) -> bool:

    """
    Notion надсилає підпис у X-Notion-Signature-256:
    hex(HMAC_SHA256(raw_body, NOTION_VERIFY_SECRET)).
    (деякі клієнти можуть додавати префікс 'sha256=').
    """
    if not NOTION_VERIFY_SECRET:
        return True

    raw = req.get_data()  # читаємо сире тіло без cache=False

    sig = (
        req.headers.get("X-Notion-Signature-256")
        or req.headers.get("X-Notion-Signature")  # fallback на старий заголовок
        or ""
    )
    if sig.lower().startswith("sha256="):
        sig = sig[7:]

    expected = hmac.new(
        NOTION_VERIFY_SECRET.encode("utf-8"),
        raw,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, sig)

def tg_send(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
    with httpx.Client(timeout=10) as s:
        r = s.post(url, data=data)
        r.raise_for_status()

def get_page_title_url(page_id: str) -> Tuple[str, str]:
    page = notion.pages.retrieve(page_id=page_id)
    # шукаємо title
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
    # витягуємо по одному (users.list не має фільтра по id, але users.retrieve існує)
    for uid in user_ids:
        try:
            u = notion.users.retrieve(user_id=uid)
            pe = u.get("person") or {}
            if pe.get("email"): emails.append(pe["email"])
        except APIResponseError:
            continue
    return emails

def extract_mentions_from_rich_text(rich: list) -> List[str]:
    # повертає список notion_user_id, згаданих у rich_text
    ids = []
    for r in rich or []:
        m = r.get("mention")
        if not m: 
            # іноді Notion упаковує як {"type":"mention","mention":{"type":"user","user":{"id":...}}}
            if r.get("type") == "mention":
                m = r.get("mention")
        if not m: 
            # якщо є annotations але без mention — пропускаємо
            continue
        if m.get("type") == "user":
            u = m.get("user") or {}
            uid = u.get("id")
            if uid: ids.append(uid)
    return list(dict.fromkeys(ids))  # унікальні з порядком

def handle_comment_event(evt: dict):
    # намагаємось дістати page_id і rich_text з payload
    page_id = (evt.get("parent") or {}).get("page_id") or (evt.get("context") or {}).get("page_id")
    if not page_id:
        # фолбек: інколи є discussion.parent.page_id
        page_id = (evt.get("discussion") or {}).get("parent", {}).get("page_id")
    rich = evt.get("rich_text") or []
    mentioned_ids = extract_mentions_from_rich_text(rich)
    if not (page_id and mentioned_ids):
        return  # нічого надсилати

    title, url = get_page_title_url(page_id)
    # готуємо уривок коментаря (перші 200 символів plain_text)
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
    # якщо payload містить rich_text з mentions (деякі вебхуки так роблять)
    page_id = (evt.get("page") or {}).get("id") or (evt.get("resource") or {}).get("id")
    if not page_id:
        return
    # спроба знайти mentions у payload (спрощено). Якщо немає — можна пропустити або додати аудит.
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
    # парсимо сире тіло, щоб зловити challenge і уникнути побічних ефектів cache=False
    raw = request.get_data()
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        body = {}

    # якщо це перевірочний запит від Notion — повертаємо challenge
    if "challenge" in body:
    # зчитаємо одноразовий токен, щоб показати його в логах
        token = (request.headers.get("X-Notion-Verification-Token")
             or body.get("verificationToken")
             or body.get("verification_token"))
        app.logger.info(f"[Notion Verify] token={token}")
        return jsonify({"challenge": body["challenge"]}), 200
    
        # звичайні івенти – спочатку валідую підпис
    # Завжди перевіряємо підпис, якщо секрет встановлено
    # Якщо секрет 'dev-local' — помилку 401 не повертаємо, щоб пройти верифікацію
    if NOTION_VERIFY_SECRET and NOTION_VERIFY_SECRET != 'dev-local':
        if not check_notion_signature(request):
            return jsonify({"ok": False, "error": "bad signature"}), 401
    elif NOTION_VERIFY_SECRET == 'dev-local':
        app.logger.warning("WARN: Skipping signature check because NOTION_VERIFY_SECRET is 'dev-local'. This should be updated after verification.")
    
    events = body.get("events") or [body]  # іноді приходить масив, іноді один
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