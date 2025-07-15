from flask import Flask, request, send_file
import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
import requests
from openpyxl import Workbook

load_dotenv()  # โหลด .env
app = Flask(__name__)

LINE_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")

def reply_text(reply_token, text):
    headers = {
        'Authorization': f'Bearer {LINE_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'replyToken': reply_token,
        'messages': [{'type': 'text', 'text': text}]
    }
    requests.post('https://api.line.me/v2/bot/message/reply', headers=headers, json=payload)

@app.route("/")
def index():
    return "✅ LINE Ingredients Bot is running!"

@app.route("/ingredients_export.xlsx")
def download_file():
    return send_file("ingredients_export.xlsx", as_attachment=True)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    try:
        msg = data["events"][0]["message"]["text"]
        reply_token = data["events"][0]["replyToken"]
        source = data["events"][0]["source"]
        user_id = source["userId"]
        group_id = source.get("groupId")
        room_id = source.get("roomId")
        context_id = group_id or room_id or user_id
    except:
        return "ignored", 200

    conn = sqlite3.connect("ingredients.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingredients (
            context_id TEXT,
            item TEXT,
            quantity REAL,
            unit TEXT,
            category TEXT,
            date TEXT
        )
    """)

    # === Export
    if msg.lower().strip() == "export วัตถุดิบ":
        rows = conn.execute("SELECT item, quantity, unit, category, date FROM ingredients WHERE context_id=?", (context_id,)).fetchall()
        if not rows:
            reply_text(reply_token, "📍 ไม่มีข้อมูลวัตถุดิบ")
            return "no data", 200
        wb = Workbook()
        ws = wb.active
        ws.title = "Ingredients"
        ws.append(["Item", "Quantity", "Unit", "Category", "Date"])
        for r in rows:
            ws.append([r[0], r[1], r[2], r[3], datetime.strptime(r[4], "%Y-%m-%d").strftime("%d-%m-%Y")])
        wb.save("ingredients_export.xlsx")
        reply_text(reply_token, f"📦 ดาวน์โหลดวัตถุดิบ:\nhttps://{request.host}/ingredients_export.xlsx")
        return "export ok", 200

    # === บันทึกวัตถุดิบ
    lines = msg.strip().split("\n")
    try:
        date_obj = datetime.strptime(lines[0].strip(), "%d %b %Y")
        lines = lines[1:]
    except:
        date_obj = datetime.now()
    date_iso = date_obj.strftime("%Y-%m-%d")
    date_display = date_obj.strftime("%d-%m-%Y")

    records = []
    for line in lines:
        parts = line.strip().rsplit(" ", 2)
        if len(parts) == 3:
            item, qty, unit = parts
            try:
                qty = float(qty.replace(",", ""))
                records.append((context_id, item, qty, unit, "-", date_iso))
            except:
                continue

    if records:
        conn.executemany("INSERT INTO ingredients VALUES (?, ?, ?, ?, ?, ?)", records)
        conn.commit()
        reply = [f"📅 บันทึกวัตถุดิบวันที่ {date_display}"]
        for r in records:
            reply.append(f"- {r[1]} {r[2]:,.0f} {r[3]}")
        reply_text(reply_token, "\n".join(reply))
        return "saved", 200

    reply_text(reply_token, "❌ รูปแบบไม่ถูกต้อง เช่น:\nหมู 5 กก\nหรือ\n15 Jul 2025\nไก่ 3 กก")
    return "fail", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
