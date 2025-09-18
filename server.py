import os
import json
from flask import Flask, request, jsonify

app = Flask(__name__)

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

    return jsonify({"ok": True}), 200

@app.get("/")
def health():
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)))