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

        # ลบข้อมูล
        if text.startswith("ลบ"):
            try:
                parts = text[3:].strip().split()
                date_obj = datetime.strptime(" ".join(parts[:3]), "%d %b %Y")
                date_str = date_obj.strftime("%Y-%m-%d")
                conn = sqlite3.connect("ingredients.db")
                if len(parts) > 3:
                    item = " ".join(parts[3:])
                    conn.execute("DELETE FROM ingredients WHERE date=? AND item=?", (date_str, item))
                    reply_text(reply_token, f"🗑️ ลบ {item} วันที่ {date_obj.strftime('%d-%m-%Y')} แล้ว")
                else:
                    conn.execute("DELETE FROM ingredients WHERE date=?", (date_str,))
                    reply_text(reply_token, f"🗑️ ลบข้อมูลวันที่ {date_obj.strftime('%d-%m-%Y')} แล้ว")
                conn.commit()
                conn.close()
                return "deleted", 200
            except:
                reply_text(reply_token, "❌ รูปแบบผิด เช่น: ลบ 26 Jul 2025 หรือ ลบ 26 Jul 2025 หมู")
                return "invalid", 200

        # รวมข้อมูลช่วงวันที่
        if re.match(r"^\d{1,2} \w{3} \d{4}\s*-\s*\d{1,2} \w{3} \d{4}$", text):
            try:
                d1_str, d2_str = [s.strip() for s in text.split("-")]
                d1 = datetime.strptime(d1_str, "%d %b %Y")
                d2 = datetime.strptime(d2_str, "%d %b %Y")
                conn = sqlite3.connect("ingredients.db")
                df = pd.read_sql_query("SELECT item, quantity, unit FROM ingredients WHERE date BETWEEN ? AND ?", conn, params=(d1.strftime("%Y-%m-%d"), d2.strftime("%Y-%m-%d")))
                if df.empty:
                    reply_text(reply_token, "📍 ไม่พบข้อมูลในช่วงวันที่ที่ระบุ")
                    return "no data", 200
                df["full"] = df["item"] + " (" + df["unit"] + ")"
                summary = df.groupby("full")["quantity"].apply(lambda x: ", ".join(x)).reset_index()
                reply = [f"📊 สรุปวัตถุดิบ {d1.strftime('%d/%m')} - {d2.strftime('%d/%m')}:"]
                for _, row in summary.iterrows():
                    reply.append(f"- {row['full']}: {row['quantity']}")
                reply_text(reply_token, "\n".join(reply))
                return "summary", 200
            except:
                reply_text(reply_token, "❌ รูปแบบผิด เช่น: 1 Jul 2025 - 31 Jul 2025")
                return "invalid", 200

        # ตรวจสอบวันที่นำหน้า
        try:
            date_obj = datetime.strptime(lines[0], "%d %b %Y")
            date_str = date_obj.strftime("%Y-%m-%d")
            date_display = date_obj.strftime("%d-%m-%Y")
            lines = lines[1:]
        except:
            date_obj = datetime.now()
            date_str = date_obj.strftime("%Y-%m-%d")
            date_display = date_obj.strftime("%d-%m-%Y")

        # ตรวจสอบและบันทึก
        records = []
        skipped = []
        for line in lines:
            parts = line.strip().rsplit(" ", 2)
            if len(parts) == 3 and line.count(" ") == 2 and re.match(r"^\d+(\.\d+)?$", parts[1]):
                item, qty, unit = parts
                records.append((item.strip(), qty.strip(), unit.strip(), date_str, datetime.now().isoformat()))
            else:
                skipped.append(line)

        if not records:
            reply_text(reply_token, "❌ กรุณาพิมพ์รูปแบบ: หมู 5 กก หรือ\n26 Jul 2025\nไข่ 30 ฟอง")
            return "invalid", 200

        conn = sqlite3.connect("ingredients.db")
        conn.executemany("INSERT INTO ingredients (item, quantity, unit, date, created_at) VALUES (?, ?, ?, ?, ?)", records)
        conn.commit()
        conn.close()

        reply = [f"📅 บันทึกวัตถุดิบวันที่ {date_display}"]
        reply += [f"- {r[0]} {r[1]} {r[2]}" for r in records]
        if skipped:
            reply.append("\n❌ ไม่สามารถบันทึก:")
            reply += [f"- {l}" for l in skipped]
        reply_text(reply_token, "\n".join(reply))
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
