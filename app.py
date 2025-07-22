from flask import Flask, request, send_file
import os
import sqlite3
from datetime import datetime
import requests
import pandas as pd

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

def parse_date(line):
    try:
        return datetime.strptime(line.strip(), "%d %b %Y")
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

        # ลบข้อมูล
        if text.lower().startswith("ลบ "):
            parts = text[4:].strip().split(" ", 1)
            try:
                date_obj = datetime.strptime(parts[0], "%d %b %Y")
                date_str = date_obj.strftime("%Y-%m-%d")
                conn = sqlite3.connect("ingredients.db")
                if len(parts) == 2:
                    item = parts[1].strip()
                    result = conn.execute("DELETE FROM ingredients WHERE date = ? AND item = ?", (date_str, item))
                else:
                    result = conn.execute("DELETE FROM ingredients WHERE date = ?", (date_str,))
                count = result.rowcount
                conn.commit()
                conn.close()
                reply_text(reply_token, f"🗑️ ลบข้อมูล {count} รายการสำเร็จ")
            except:
                reply_text(reply_token, "❌ รูปแบบวันที่ไม่ถูกต้อง เช่น:\nลบ 26 Jul 2025\nลบ 26 Jul 2025 หมู")
            return "ok", 200

        # สรุปช่วงวัน
        if "-" in text:
            try:
                start_text, end_text = text.split("-")
                start_date = datetime.strptime(start_text.strip(), "%d %b %Y").strftime("%Y-%m-%d")
                end_date = datetime.strptime(end_text.strip(), "%d %b %Y").strftime("%Y-%m-%d")
                conn = sqlite3.connect("ingredients.db")
                df = pd.read_sql_query("""
                    SELECT item, quantity, unit FROM ingredients
                    WHERE date BETWEEN ? AND ?
                """, conn, params=(start_date, end_date))
                conn.close()

                if df.empty:
                    reply_text(reply_token, f"📦 ไม่พบข้อมูลระหว่าง {start_date} ถึง {end_date}")
                else:
                    summary = df.groupby(["item", "unit"]).agg({"quantity": lambda x: " + ".join(x)}).reset_index()
                    msg = f"📦 สรุปวัตถุดิบ {start_date} ถึง {end_date}:\n"
                    for _, row in summary.iterrows():
                        msg += f"- {row['item']} {row['quantity']} {row['unit']}\n"
                    reply_text(reply_token, msg.strip())
                return "ok", 200
            except:
                pass

        # export
        if text.lower() == "export":
            conn = sqlite3.connect("ingredients.db")
            df = pd.read_sql_query("SELECT item, quantity, unit, date FROM ingredients ORDER BY date DESC", conn)
            conn.close()
            filename = "ingredients_export.xlsx"
            df.to_excel(filename, index=False)
            return send_file(filename, as_attachment=True)

        # วันจากข้อความ
        try:
            date_obj = parse_date(lines[0])
            if date_obj:
                date_str = date_obj.strftime("%Y-%m-%d")
                date_display = date_obj.strftime("%d-%m-%Y")
                lines = lines[1:]
            else:
                raise ValueError
        except:
            date_obj = datetime.now()
            date_str = date_obj.strftime("%Y-%m-%d")
            date_display = date_obj.strftime("%d-%m-%Y")

        # อ่านข้อมูล
        records, errors = [], []
        for line in lines:
            parts = line.strip().rsplit(" ", 2)
            if len(parts) != 3 or line.count(" ") > 2:
                errors.append(line)
                continue
            item, qty, unit = parts
            records.append((item.strip(), qty.strip(), unit.strip(), date_str, datetime.now().isoformat()))

        if not records:
            reply_text(reply_token, "❌ กรุณาพิมพ์รูปแบบ: หมู 5 กก หรือ\n26 Jul 2025\nไข่ 30 ฟอง")
            return "invalid", 200

        # บันทึกลงฐานข้อมูล
        conn = sqlite3.connect("ingredients.db")
        conn.executemany("INSERT INTO ingredients (item, quantity, unit, date, created_at) VALUES (?, ?, ?, ?, ?)", records)
        conn.commit()
        conn.close()

        # ตอบกลับ
        msg = f"📅 บันทึกวัตถุดิบวันที่ {date_display}\n"
        for r in records:
            msg += f"- {r[0]} {r[1]} {r[2]}\n"
        if errors:
            msg += "\n⚠️ ไม่ได้บันทึกรายการ:\n" + "\n".join(f"- {e}" for e in errors)
        reply_text(reply_token, msg.strip())

    return "ok", 200

@app.route("/")
def index():
    return "✅ LINE Bot วัตถุดิบทำงานแล้ว!"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
