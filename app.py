from flask import Flask, request, send_file
import os
import sqlite3
from datetime import datetime
import requests
import pandas as pd

app = Flask(__name__)

# อ่าน LINE TOKEN จาก .env
LINE_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")

# ---------- 1. ตอบกลับข้อความ ----------
def reply_text(reply_token, text):
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=data)

# ---------- 2. สร้าง DB ถ้ายังไม่มี ----------
def init_db():
    conn = sqlite3.connect("ingredients.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT,
            quantity TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

# ---------- 3. บันทึกข้อความลง DB ----------
def save_to_db(item, quantity):
    conn = sqlite3.connect("ingredients.db")
    c = conn.cursor()
    c.execute('''
        INSERT INTO ingredients (item, quantity, created_at)
        VALUES (?, ?, ?)
    ''', (item, quantity, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ---------- 4. ดึงข้อมูลออกเป็น Excel ----------
@app.route("/export", methods=["GET"])
def export_excel():
    conn = sqlite3.connect("ingredients.db")
    df = pd.read_sql_query("SELECT * FROM ingredients", conn)
    conn.close()
    filename = "ingredients_export.xlsx"
    df.to_excel(filename, index=False)
    return send_file(filename, as_attachment=True)

# ---------- 5. Webhook LINE ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json()
    events = payload.get("events", [])
    for event in events:
        if event.get("type") == "message":
            reply_token = event["replyToken"]
            text = event["message"]["text"]

            # แยกข้อความ: เช่น "หมู 5 กก"
            parts = text.strip().split(" ", 1)
            if len(parts) == 2:
                item, quantity = parts
                save_to_db(item, quantity)
                reply_text(reply_token, f"บันทึกแล้ว: {item} {quantity}")
            else:
                reply_text(reply_token, "กรุณาพิมพ์ในรูปแบบ: หมู 5 กก")
    return "OK", 200

# ---------- 6. Index ----------
@app.route("/", methods=["GET"])
def index():
    return "✅ LINE Ingredients Bot is running!"

# ---------- 7. Run app ----------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
