import logging
import requests
import re
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ===== CONFIG =====
BOT_TOKEN = "8901092528:AAFQ23IMYD5oVL1cNEquLphWc5RYij0FJZw"
BASE_URL = ""
TARGET_CHANNEL_ID = -1003553669855

# ===== LOGGING =====
logging.basicConfig(level=logging.INFO, format="%(message)s")

print("\n🚀 SMS RELAY ACTIVE\n")

# ===== INPUT =====
TARGET_DEVICE = input("🔑 Device ID: ").strip()
SIM_CHOICE = input("📡 SIM (1/2): ").strip()

if SIM_CHOICE not in ["1", "2"]:
    print("❌ Invalid SIM")
    exit()

SIM_INDEX = 0 if SIM_CHOICE == "1" else 1

print("\n👀 Waiting for messages...\n")

# ===== START TIME =====
START_TIME = int(time.time())

# ===== DUPLICATE =====
last_sent = set()

# ===== PATTERNS =====
pattern_simple = re.compile(r"(\+?\d{10,15})\s*\|\s*(.*)")
pattern_rich = re.compile(r"To:\s*(\+?\d{10,15}).*?Message:\s*(.*)", re.DOTALL)

# ===== LISTENER =====
async def channel_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.effective_message

        if not msg or not msg.text:
            return

        # ignore old
        if msg.date.timestamp() < START_TIME:
            return

        # wrong channel
        if update.effective_chat.id != TARGET_CHANNEL_ID:
            return

        text = msg.text.strip()

        # ===== TRY BOTH FORMATS =====
        match = pattern_simple.search(text)

        if not match:
            match = pattern_rich.search(text)

        if not match:
            return

        to_number = match.group(1).replace(" ", "")
        sms_body = match.group(2).strip().replace("\n", " ")

        key = f"{to_number}-{sms_body}"
        if key in last_sent:
            return

        last_sent.add(key)

        print(f"📤 {to_number} → {sms_body[:40]}")

        url = f"{BASE_URL}/clients/{TARGET_DEVICE}/webhookEvent/sendSms.json"

        payload = {
            "from": SIM_INDEX,
            "to": to_number,
            "message": sms_body,
            "isSended": False
        }

        res = requests.patch(url, json=payload, timeout=5)

        if res.status_code == 200:
            print("✅ SENT\n")
        else:
            print("❌ FAIL\n")

    except Exception as e:
        print("❌ ERROR:", e)

# ===== RUN =====
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), channel_listener))

app.run_polling(drop_pending_updates=True)
