# server.py
from flask import Flask, request, jsonify
import os, json, datetime

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOG_FILE = os.path.join(DATA_DIR, "notion_webhook.log")
TOKEN_FILE = os.path.join(DATA_DIR, "notion_token.txt")
os.makedirs(DATA_DIR, exist_ok=True)

def append_line(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")

@app.route("/notion/webhook", methods=["POST"])
def notion_webhook():
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # 1) Тіло запиту (challenge)
    payload = request.get_json(silent=True) or {}
    challenge = payload.get("challenge")

    # 2) Заголовок із верифікаційним токеном
    vtoken = request.headers.get("X-Notion-Verification-Token", "")

    # 3) Логуємо все в один файл
    append_line(LOG_FILE, json.dumps({
        "ts": now,
        "headers": {"X-Notion-Verification-Token": vtoken},
        "payload": payload
    }, ensure_ascii=False))

    # 4) Якщо прийшов токен — перезаписуємо окремий файл із поточним значенням
    if vtoken:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(vtoken)

    # 5) Для стадії підтвердження Notion очікує повернення challenge
    if challenge:
        return jsonify({"challenge": challenge}), 200

    # 6) Для звичайних подій просто 200 OK
    return ("", 200)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
