from flask import Flask, request, send_file
import os
import sqlite3
from datetime import datetime
import requests
import pandas as pd
import re

app = Flask(__name__)
LINE_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")

def reply_text(reply_token, text):
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)

def init_db():
    conn = sqlite3.connect("ingredients.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT,
            quantity TEXT,
            unit TEXT,
            date TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    events = data.get("events", [])
    for event in events:
        if event.get("type") != "message":
            continue

        reply_token = event["replyToken"]
        text = event["message"]["text"].strip()
        lines = text.split("\n")

        # ตรวจสอบวันที่
        try:
            date_obj = datetime.strptime(lines[0], "%d %b %Y")
            date_str = date_obj.strftime("%Y-%m-%d")
            date_display = date_obj.strftime("%d-%m-%Y")
            lines = lines[1:]
        except:
            date_obj = datetime.now()
            date_str = date_obj.strftime("%Y-%m-%d")
            date_display = date_obj.strftime("%d-%m-%Y")

        records = []
        skipped_lines = []
        for line in lines:
            parts = line.strip().rsplit(" ", 2)
            if len(parts) == 3:
                item, qty, unit = parts
                if line.count(" ") <= 2 and re.match(r"^\d+(\.\d+)?$", qty):
                    records.append((item, qty, unit, date_str, datetime.now().isoformat()))
                else:
                    skipped_lines.append(line)
            else:
                skipped_lines.append(line)

        if not records:
            reply_text(reply_token, "❌ กรุณาพิมพ์รูปแบบ: หมู 5 กก หรือ\n26 Jul 2025\nไข่ 30 ฟอง")
            return "no valid lines", 200

        # บันทึก
        conn = sqlite3.connect("ingredients.db")
        conn.executemany("INSERT INTO ingredients (item, quantity, unit, date, created_at) VALUES (?, ?, ?, ?, ?)", records)
        conn.commit()
        conn.close()

        # ตอบกลับ
        lines = [f"📅 บันทึกวัตถุดิบวันที่ {date_display}"]
        for r in records:
            lines.append(f"- {r[0]} {r[1]} {r[2]}")
        if skipped_lines:
            lines.append("\n❌ ไม่สามารถบันทึก:")
            lines += [f"- {l}" for l in skipped_lines]

        reply_text(reply_token, "\n".join(lines))
    return "ok", 200

@app.route("/export")
def export():
    conn = sqlite3.connect("ingredients.db")
    df = pd.read_sql_query("SELECT item, quantity, unit, date FROM ingredients ORDER BY date DESC", conn)
    filename = "ingredients_export.xlsx"
    df.to_excel(filename, index=False)
    return send_file(filename, as_attachment=True)

@app.route("/")
def index():
    return "✅ LINE Ingredients Bot is running!"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
