from flask import Flask, request, send_file
import os
import sqlite3
from datetime import datetime
import requests
import pandas as pd
import re
from collections import defaultdict

app = Flask(__name__)
LINE_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")
DOMAIN = os.environ.get("DOMAIN", "https://your-render-url.com")  # <-- ใส่ domain ของคุณที่นี่

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
            quantity REAL,
            unit TEXT,
            date TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def parse_date(text):
    try:
        return datetime.strptime(text.strip(), "%d %b %Y")
    except:
        return None

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

        # ✅ Export
        if text.lower() == "export":
            filename = "ingredients_export.xlsx"
            conn = sqlite3.connect("ingredients.db")
            df = pd.read_sql_query("SELECT item, quantity, unit, date FROM ingredients ORDER BY date DESC", conn)
            conn.close()
            df.to_excel(filename, index=False)
            reply_text(reply_token, f"📎 ดาวน์โหลดวัตถุดิบ: {DOMAIN}/{filename}")
            return "ok", 200

        # ✅ ลบข้อมูล
        if text.lower().startswith("ลบ"):
            match = re.match(r"ลบ\s+(\d{1,2} \w{3} \d{4})(?:\s+(.*))?", text)
            if not match:
                reply_text(reply_token, "❌ รูปแบบวันที่ไม่ถูกต้อง เช่น:\nลบ 26 Jul 2025\nลบ 26 Jul 2025 หมู")
                return "ok", 200
            try:
                date = datetime.strptime(match.group(1), "%d %b %Y").strftime("%Y-%m-%d")
            except:
                reply_text(reply_token, "❌ ไม่สามารถแปลงวันที่ได้")
                return "ok", 200
            item = match.group(2)
            conn = sqlite3.connect("ingredients.db")
            c = conn.cursor()
            if item:
                c.execute("DELETE FROM ingredients WHERE date = ? AND item = ?", (date, item.strip()))
            else:
                c.execute("DELETE FROM ingredients WHERE date = ?", (date,))
            conn.commit()
            conn.close()
            reply_text(reply_token, f"🗑 ลบข้อมูล{' ' + item if item else ''} วันที่ {match.group(1)} แล้ว")
            return "ok", 200

        # ✅ สรุปช่วงวันที่
        match_range = re.match(r"(\d{1,2} \w{3} \d{4})\s*-\s*(\d{1,2} \w{3} \d{4})", text)
        if match_range:
            try:
                d1 = datetime.strptime(match_range.group(1), "%d %b %Y")
                d2 = datetime.strptime(match_range.group(2), "%d %b %Y")
                conn = sqlite3.connect("ingredients.db")
                df = pd.read_sql_query(
                    "SELECT item, quantity, unit, date FROM ingredients WHERE date BETWEEN ? AND ?",
                    conn, params=(d1.strftime("%Y-%m-%d"), d2.strftime("%Y-%m-%d"))
                )
                conn.close()

                if df.empty:
                    reply_text(reply_token, "📦 ไม่พบข้อมูลในช่วงที่ระบุ")
                    return "ok", 200

                summary = defaultdict(lambda: defaultdict(float))
                for _, row in df.iterrows():
                    summary[row['item']][row['unit']] += row['quantity']

                lines = [f"📊 สรุปวัตถุดิบ {d1.strftime('%d/%m')} - {d2.strftime('%d/%m')}:"] 
                for item, units in summary.items():
                    for unit, qty in units.items():
                        lines.append(f"- {item} ({unit}): {qty:g}")
                reply_text(reply_token, "\n".join(lines))
                return "ok", 200
            except:
                reply_text(reply_token, "❌ รูปแบบช่วงวันที่ไม่ถูกต้อง เช่น: 1 Jul 2025 - 31 Jul 2025")
                return "ok", 200

        # ✅ ตรวจสอบวัน
        date_obj = parse_date(lines[0])
        if date_obj:
            lines = lines[1:]
        else:
            date_obj = datetime.now()

        date_str = date_obj.strftime("%Y-%m-%d")
        date_display = date_obj.strftime("%d-%m-%Y")

        # ✅ ตรวจสอบ pattern
        records = []
        skipped = []
        for line in lines:
            parts = line.strip().rsplit(" ", 2)
            if len(parts) == 3:
                item, qty, unit = parts
                if line.count(" ") <= 2 and re.match(r"^\d+(\.\d+)?$", qty):
                    records.append((item, float(qty), unit, date_str, datetime.now().isoformat()))
                else:
                    skipped.append(line)
            else:
                skipped.append(line)

        if not records:
            reply_text(reply_token, "❌ กรุณาพิมพ์รูปแบบ: หมู 5 กก หรือ\n26 Jul 2025\nไข่ 30 ฟอง")
            return "ok", 200

        conn = sqlite3.connect("ingredients.db")
        conn.executemany("INSERT INTO ingredients (item, quantity, unit, date, created_at) VALUES (?, ?, ?, ?, ?)", records)
        conn.commit()
        conn.close()

        lines = [f"🗓 บันทึกวัตถุดิบวันที่ {date_display}"]
        for r in records:
            lines.append(f"- {r[0]} {r[1]:g} {r[2]}")
        if skipped:
            lines.append("\n⚠️ ไม่สามารถบันทึก:")
            lines += [f"- {s}" for s in skipped]
        reply_text(reply_token, "\n".join(lines))
    return "ok", 200

@app.route("/ingredients_export.xlsx")
def download_excel():
    return send_file("ingredients_export.xlsx", as_attachment=True)

@app.route("/")
def index():
    return "✅ LINE Ingredients Bot is running!"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
