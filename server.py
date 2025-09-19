# server.py
from flask import Flask, request, jsonify
import os, datetime

app = Flask(__name__)

@app.route("/notion/webhook", methods=["POST"])
def notion_webhook():
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # 1) Тіло запиту (challenge)
    payload = request.get_json(silent=True) or {}
    challenge = payload.get("challenge")

    # 2) Заголовок із верифікаційним токеном
    vtoken = request.headers.get("X-Notion-Verification-Token", "")

    # 3) Виводимо у лог Render
    print("=" * 40)
    print(f"[{now}] Запит від Notion")
    print(f"Verification token: {vtoken}")
    print(f"Challenge: {challenge}")
    print(f"Повний payload: {payload}")
    print("=" * 40)

    # 4) Для підтвердження Notion треба повернути challenge
    if challenge:
        return jsonify({"challenge": challenge}), 200

    return ("", 200)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
