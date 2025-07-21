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

        # 1. EXPORT
        if text.lower() == "export":
            filename = "ingredients_export.xlsx"
            conn = sqlite3.connect("ingredients.db")
            df = pd.read_sql_query("SELECT item, quantity, date FROM ingredients ORDER BY date DESC", conn)
            conn.close()

            # แยก quantity เป็น amount และ unit
            df[["amount", "unit"]] = df["quantity"].str.extract(r"(\d+(?:\.\d+)?)\s*(.+)")
            df["amount"] = df["amount"].astype(float)
            df = df[["item", "amount", "unit", "date"]]

            df.to_excel(filename, index=False)
            reply_text(reply_token, "📦 ดาวน์โหลดวัตถุดิบ: https://line-ingredients-bot.onrender.com/download")
            return "ok", 200

        # 2. DELETE
        delete_match = re.match(r"^ลบ (\d{1,2} \w+ \d{4})(?: (.+))?$", text)
        if delete_match:
            try:
                date_obj = datetime.strptime(delete_match.group(1), "%d %b %Y")
                date_str = date_obj.strftime("%Y-%m-%d")
                item = delete_match.group(2)

                conn = sqlite3.connect("ingredients.db")
                if item:
                    cur = conn.execute("DELETE FROM ingredients WHERE date = ? AND item = ?", (date_str, item))
                else:
                    cur = conn.execute("DELETE FROM ingredients WHERE date = ?", (date_str,))
                deleted = cur.rowcount
                conn.commit()
                conn.close()

                if deleted > 0:
                    reply_text(reply_token, f"✅ ลบ{'รายการ ' + item if item else 'ทั้งหมด'}ของวันที่ {date_str} แล้ว")
                else:
                    reply_text(reply_token, f"⚠️ ไม่พบข้อมูลของวันที่ {date_str}")
                return "ok", 200
            except:
                reply_text(reply_token, "❌ รูปแบบวันที่ไม่ถูกต้อง เช่น:\nลบ 26 Jul 2025\nลบ 26 Jul 2025 หมู")
                return "ok", 200

        # 3. SUMMARY
        summary_match = re.match(r"^(\d{1,2} \w+ \d{4}) - (\d{1,2} \w+ \d{4})$", text)
        if summary_match:
            try:
                start_date = datetime.strptime(summary_match.group(1), "%d %b %Y").strftime("%Y-%m-%d")
                end_date = datetime.strptime(summary_match.group(2), "%d %b %Y").strftime("%Y-%m-%d")

                conn = sqlite3.connect("ingredients.db")
                rows = conn.execute("SELECT item, quantity FROM ingredients WHERE date BETWEEN ? AND ?", (start_date, end_date)).fetchall()
                conn.close()

                if not rows:
                    reply_text(reply_token, "😔 ไม่พบข้อมูลในช่วงที่ระบุ")
                    return "ok", 200

                summary = {}
                for item, qty in rows:
                    summary.setdefault(item, []).append(qty)

                lines = [f"📦 สรุปวัตถุดิบ {start_date} ถึง {end_date}:"]
                for item, qtys in summary.items():
                    lines.append(f"- {item} {' + '.join(qtys)}")

                reply_text(reply_token, "\n".join(lines))
                return "ok", 200
            except:
                reply_text(reply_token, "❌ รูปแบบไม่ถูกต้อง เช่น:\n1 Jul 2025 - 31 Jul 2025")
                return "ok", 200

        # 4. SAVE INGREDIENTS
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
            return "ok", 200

        conn = sqlite3.connect("ingredients.db")
        conn.executemany("INSERT INTO ingredients (item, quantity, date, created_at) VALUES (?, ?, ?, ?)", records)
        conn.commit()

        all_rows = conn.execute("SELECT item, quantity FROM ingredients WHERE date = ?", (date_str,)).fetchall()
        conn.close()

        lines = [f"📅 บันทึกวัตถุดิบวันที่ {date_display}"]
        for r in all_rows:
            lines.append(f"- {r[0]} {r[1]}")
        reply_text(reply_token, "\n".join(lines))
    return "ok", 200

@app.route("/download")
def download():
    return send_file("ingredients_export.xlsx", as_attachment=True)

@app.route("/")
def index():
    return "✅ LINE Ingredients Bot is running!"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
