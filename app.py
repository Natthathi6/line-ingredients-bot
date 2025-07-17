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

        # ✅ สรุปช่วงวันที่ เช่น: 1 Jul 2025 - 31 Jul 2025
        if " - " in text and len(text.split("\n")) == 1:
            try:
                d1_str, d2_str = text.split("-")
                d1 = datetime.strptime(d1_str.strip(), "%d %b %Y")
                d2 = datetime.strptime(d2_str.strip(), "%d %b %Y")
                d1_iso = d1.strftime("%Y-%m-%d")
                d2_iso = d2.strftime("%Y-%m-%d")
                conn = sqlite3.connect("ingredients.db")
                df = pd.read_sql_query(
                    "SELECT item, quantity FROM ingredients WHERE date BETWEEN ? AND ?",
                    conn,
                    params=(d1_iso, d2_iso)
                )
                conn.close()

                if df.empty:
                    reply_text(reply_token, f"📍 ไม่มีข้อมูลในช่วง {d1.strftime('%d-%m-%Y')} ถึง {d2.strftime('%d-%m-%Y')}")
                    return "no data", 200

                df[["qty", "unit"]] = df["quantity"].str.extract(r"(\d+(?:\.\d+)?)\s*(.+)")
                df["qty"] = df["qty"].astype(float)
                summary = df.groupby(["item", "unit"])["qty"].sum().reset_index()

                reply = [f"📦 สรุปวัตถุดิบ {d1.strftime('%d-%m-%Y')} ถึง {d2.strftime('%d-%m-%Y')}:"]
                for _, row in summary.iterrows():
                    reply.append(f"- {row['item']} {row['qty']:,.0f} {row['unit']}")
                reply_text(reply_token, "\n".join(reply))
                return "summary ok", 200
            except:
                reply_text(reply_token, "❌ รูปแบบไม่ถูกต้อง เช่น: 1 Jul 2025 - 31 Jul 2025")
                return "invalid range", 200

        # ✅ export
        if text.lower() == "export":
            reply_text(reply_token, f"📦 ดาวน์โหลดวัตถุดิบ:\nhttps://{request.host}/export")
            return "export sent", 200

        # ✅ ลบ 26 Jul 2025 หรือ ลบ 26 Jul 2025 ไข่
        if text.lower().startswith("ลบ "):
            parts = text[4:].strip().split(" ", 1)
            try:
                date_obj = datetime.strptime(parts[0], "%d %b %Y")
                date_str = date_obj.strftime("%Y-%m-%d")
                item_filter = parts[1].strip() if len(parts) > 1 else None

                conn = sqlite3.connect("ingredients.db")
                cursor = conn.cursor()

                if item_filter:
                    cursor.execute("DELETE FROM ingredients WHERE date=? AND item=?", (date_str, item_filter))
                    msg = f"🗑️ ลบ '{item_filter}' ของวันที่ {date_obj.strftime('%d-%m-%Y')} แล้ว"
                else:
                    cursor.execute("DELETE FROM ingredients WHERE date=?", (date_str,))
                    msg = f"🗑️ ลบข้อมูลทั้งหมดของวันที่ {date_obj.strftime('%d-%m-%Y')} แล้ว"

                conn.commit()
                conn.close()
                reply_text(reply_token, msg)
            except:
                reply_text(reply_token, "❌ รูปแบบวันที่ไม่ถูกต้อง เช่น:\nลบ 26 Jul 2025\nลบ 26 Jul 2025 หมู")
            return "ok", 200

        # ✅ แยกวันที่ (ถ้ามี) จากบรรทัดแรก
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

        # ✅ แปลงเป็นรายการวัตถุดิบ
        records = []
        for line in lines:
            parts = line.strip().rsplit(" ", 2)
            if len(parts) == 3:
                item, qty, unit = parts
                records.append((item, f"{qty} {unit}", date_str, datetime.now().isoformat()))

        if not records:
            reply_text(reply_token, "❌ กรุณาพิมพ์: หมู 5 กก หรือ\n26 Jul 2025\nไข่ 30 ฟอง")
            return "invalid", 200

        # ✅ บันทึกข้อมูล
        conn = sqlite3.connect("ingredients.db")
        conn.executemany(
            "INSERT INTO ingredients (item, quantity, date, created_at) VALUES (?, ?, ?, ?)",
            records
        )
        conn.commit()

        # ✅ ดึงข้อมูลทั้งหมดของวันนั้น
        df = pd.read_sql_query(
            "SELECT item, quantity FROM ingredients WHERE date = ? ORDER BY created_at",
            conn,
            params=(date_str,)
        )
        conn.close()

        reply_lines = [f"📅 วัตถุดิบวันที่ {date_display}:"]
        for _, row in df.iterrows():
            reply_lines.append(f"- {row['item']} {row['quantity']}")
        reply_text(reply_token, "\n".join(reply_lines))

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
