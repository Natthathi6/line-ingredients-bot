from flask import Flask, request, send_file
import os
import sqlite3
from datetime import datetime
import pandas as pd
import re
import uuid

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
            quantity REAL,
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

        # export = สั่งดาวน์โหลด
        if text.lower() == "export":
            file_id = str(uuid.uuid4())
            filename = f"ingredients_{file_id}.xlsx"
            conn = sqlite3.connect("ingredients.db")
            df = pd.read_sql_query("SELECT item, quantity, unit, date FROM ingredients ORDER BY date DESC", conn)
            conn.close()
            df.to_excel(filename, index=False)
            return reply_text(reply_token, f"📎 ดาวน์โหลด: https://<your-render-url>/{filename}"), 200

        # สรุปช่วงวันที่
        match = re.match(r"^(\d{1,2} \w{3} \d{4})\s*-\s*(\d{1,2} \w{3} \d{4})$", text)
        if match:
            try:
                start = datetime.strptime(match.group(1), "%d %b %Y")
                end = datetime.strptime(match.group(2), "%d %b %Y")
                conn = sqlite3.connect("ingredients.db")
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT item, unit, SUM(quantity) FROM ingredients
                    WHERE date BETWEEN ? AND ?
                    GROUP BY item, unit
                """, (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
                rows = cursor.fetchall()
                conn.close()
                lines = [f"📊 สรุปวัตถุดิบ {start.strftime('%d/%m')} - {end.strftime('%d/%m')}:"] + \
                        [f"- {r[0]} ({r[1]}): {r[2]}" for r in rows]
                reply_text(reply_token, "\n".join(lines))
                return "ok", 200
            except:
                pass

        # ลบข้อมูล
        if text.lower().startswith("ลบ "):
            try:
                parts = text[3:].strip().split(" ", 2)
                date_obj = datetime.strptime(f"{parts[0]} {parts[1]} {parts[2]}", "%d %b %Y")
                date_str = date_obj.strftime("%Y-%m-%d")
                conn = sqlite3.connect("ingredients.db")
                if len(parts) == 3:
                    conn.execute("DELETE FROM ingredients WHERE date = ?", (date_str,))
                    conn.commit()
                    reply_text(reply_token, f"🗑️ ลบข้อมูล วันที่ {parts[0]} {parts[1]} {parts[2]} แล้ว")
                elif len(parts) == 4:
                    item = parts[3]
                    conn.execute("DELETE FROM ingredients WHERE date = ? AND item = ?", (date_str, item))
                    conn.commit()
                    reply_text(reply_token, f"🗑️ ลบข้อมูล {item} วันที่ {parts[0]} {parts[1]} {parts[2]} แล้ว")
                else:
                    reply_text(reply_token, "❌ รูปแบบวันที่ไม่ถูกต้อง เช่น:\nลบ 26 Jul 2025\nลบ 26 Jul 2025 หมู")
                conn.close()
                return "ok", 200
            except:
                reply_text(reply_token, "❌ รูปแบบวันที่ไม่ถูกต้อง เช่น:\nลบ 26 Jul 2025\nลบ 26 Jul 2025 หมู")
                return "bad", 200

        # รับวัตถุดิบ
        lines = text.split("\n")
        try:
            date_obj = datetime.strptime(lines[0], "%d %b %Y")
            date_str = date_obj.strftime("%Y-%m-%d")
            lines = lines[1:]
        except:
            date_str = datetime.now().strftime("%Y-%m-%d")

        records = []
        skipped = []
        for line in lines:
            if line.count(" ") > 2:
                skipped.append(line)
                continue
            parts = line.strip().rsplit(" ", 2)
            if len(parts) == 3:
                item, qty, unit = parts
                try:
                    qty = float(qty)
                    records.append((item, qty, unit, date_str, datetime.now().isoformat()))
                except:
                    skipped.append(line)
            else:
                skipped.append(line)

        if records:
            conn = sqlite3.connect("ingredients.db")
            conn.executemany(
                "INSERT INTO ingredients (item, quantity, unit, date, created_at) VALUES (?, ?, ?, ?, ?)", records
            )
            conn.commit()
            conn.close()
            reply_lines = [f"📅 บันทึกวัตถุดิบวันที่ {date_str}"] + [f"- {r[0]} {r[1]} {r[2]}" for r in records]
            if skipped:
                reply_lines.append("❌ ไม่สามารถบันทึก:")
                reply_lines += [f"- {l}" for l in skipped]
            reply_text(reply_token, "\n".join(reply_lines))
        else:
            reply_text(reply_token, "❌ กรุณาพิมพ์รูปแบบ: หมู 5 กก หรือ\n26 Jul 2025\nไข่ 30 ฟอง")
    return "ok", 200

@app.route("/<filename>")
def download_excel(filename):
    return send_file(filename, as_attachment=True)

@app.route("/")
def index():
    return "✅ LINE Ingredients Bot is running!"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
