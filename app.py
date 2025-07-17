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

        # ✅ ลบรายการ
        if text.lower().startswith("ลบ"):
            try:
                match = re.match(r"ลบ\s+(\d{1,2} \w{3} \d{4})(?:\s+(.+))?", text, re.IGNORECASE)
                if not match:
                    raise ValueError("pattern not matched")

                date_text = match.group(1).strip()
                item_filter = match.group(2).strip() if match.group(2) else None
                date_obj = datetime.strptime(date_text, "%d %b %Y")
                date_str = date_obj.strftime("%Y-%m-%d")

                conn = sqlite3.connect("ingredients.db")
                cur = conn.cursor()
                if item_filter:
                    cur.execute("DELETE FROM ingredients WHERE date=? AND item=?", (date_str, item_filter))
                    msg = f"🗑️ ลบ '{item_filter}' ของวันที่ {date_obj.strftime('%d-%m-%Y')} แล้ว"
                else:
                    cur.execute("DELETE FROM ingredients WHERE date=?", (date_str,))
                    msg = f"🗑️ ลบข้อมูลทั้งหมดของวันที่ {date_obj.strftime('%d-%m-%Y')} แล้ว"
                conn.commit()
                conn.close()
                reply_text(reply_token, msg)
            except:
                reply_text(reply_token, "❌ รูปแบบวันที่ไม่ถูกต้อง เช่น:\nลบ 26 Jul 2025\nลบ 26 Jul 2025 หมู")
            return "ok", 200

        # ✅ รายงานช่วงวันที่
        if " - " in text:
            try:
                parts = text.split(" - ")
                start = datetime.strptime(parts[0].strip(), "%d %b %Y")
                end = datetime.strptime(parts[1].strip(), "%d %b %Y")
                conn = sqlite3.connect("ingredients.db")
                df = pd.read_sql_query(
                    "SELECT item, quantity FROM ingredients WHERE date BETWEEN ? AND ?",
                    conn, params=(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
                )
                conn.close()
                if df.empty:
                    reply_text(reply_token, "ไม่มีข้อมูลในช่วงที่ระบุ")
                    return "ok", 200
                df = df.groupby("item")["quantity"].apply(list).reset_index()
                summary = f"📦 สรุปวัตถุดิบ {start.strftime('%d-%m-%Y')} ถึง {end.strftime('%d-%m-%Y')}:\n"
                for _, row in df.iterrows():
                    total = " + ".join(row["quantity"])
                    summary += f"- {row['item']} {total}\n"
                reply_text(reply_token, summary.strip())
            except:
                reply_text(reply_token, "❌ รูปแบบช่วงวันที่ไม่ถูกต้อง เช่น:\n1 Jul 2025 - 31 Jul 2025")
            return "ok", 200

        # ✅ เพิ่มข้อมูลใหม่
        lines = text.split("\n")
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
        for line in lines:
            parts = line.strip().rsplit(" ", 2)
            if len(parts) == 3:
                item, qty, unit = parts
                records.append((item, f"{qty} {unit}", date_str, datetime.now().isoformat()))

        if not records:
            reply_text(reply_token, "❌ กรุณาพิมพ์รูปแบบ: หมู 5 กก หรือ\n26 Jul 2025\nไข่ 30 ฟอง")
            return "invalid", 200

        conn = sqlite3.connect("ingredients.db")
        conn.executemany("INSERT INTO ingredients (item, quantity, date, created_at) VALUES (?, ?, ?, ?)", records)
        conn.commit()
        conn.close()

        lines = [f"📅 บันทึกวัตถุดิบวันที่ {date_display}"]
        for r in records:
            lines.append(f"- {r[0]} {r[1]}")
        reply_text(reply_token, "\n".join(lines))
    return "ok", 200

@app.route("/export")
def export():
    conn = sqlite3.connect("ingredients.db")
    df = pd.read_sql_query("SELECT item, quantity, date FROM ingredients ORDER BY date DESC", conn)
    filename = "ingredients_export.xlsx"
    df.to_excel(filename, index=False)
    return send_file(filename, as_attachment=True)

@app.route("/")
def index():
    return "✅ LINE Ingredients Bot is running!"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
