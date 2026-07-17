import logging
import os
import requests
import re
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# ===== FIREBASE =====
# Firebase Console → Realtime Database → URL copy karo
# Example: https://your-project-default-rtdb.firebaseio.com
FIREBASE_URL = os.getenv("FIREBASE_URL", "").rstrip("/")
FIREBASE_CONFIG_PATH = os.getenv("FIREBASE_CONFIG_PATH", "config")

# ===== FALLBACK CONFIG (Firebase na ho to ye use hoga) =====
FALLBACK = {
    "bot_token": "8901092528:AAFQ23IMYD5oVL1cNEquLphWc5RYij0FJZw",
    "channel_id": -1003553669855,
    "base_url": "",
    "device_id": "",
    "sim": "1",
}


def load_firebase_config():
    """Firebase Realtime Database se config load karo."""
    if not FIREBASE_URL:
        print("⚠️  FIREBASE_URL set nahi — fallback config use ho raha hai\n")
        return FALLBACK.copy()

    try:
        url = f"{FIREBASE_URL}/{FIREBASE_CONFIG_PATH}.json"
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()

        if not data or not isinstance(data, dict):
            print("⚠️  Firebase config empty — fallback use ho raha hai\n")
            return FALLBACK.copy()

        config = FALLBACK.copy()
        config.update({k: v for k, v in data.items() if v is not None and v != ""})
        print("✅ Config Firebase se load ho gaya\n")
        return config

    except Exception as e:
        print(f"⚠️  Firebase error ({e}) — fallback config use ho raha hai\n")
        return FALLBACK.copy()


CONFIG = load_firebase_config()

BOT_TOKEN = CONFIG["bot_token"]
BASE_URL = CONFIG.get("base_url", "")
TARGET_CHANNEL_ID = int(CONFIG["channel_id"])
TARGET_DEVICE = CONFIG.get("device_id", "").strip()
SIM_CHOICE = str(CONFIG.get("sim", "1")).strip()

# Firebase mein device/sim na ho to input lo
if not TARGET_DEVICE:
    TARGET_DEVICE = input("🔑 Device ID: ").strip()

if SIM_CHOICE not in ["1", "2"]:
    SIM_CHOICE = input("📡 SIM (1/2): ").strip()

if SIM_CHOICE not in ["1", "2"]:
    print("❌ Invalid SIM")
    exit()

SIM_INDEX = 0 if SIM_CHOICE == "1" else 1

# ===== LOGGING =====
logging.basicConfig(level=logging.INFO, format="%(message)s")

print("\n🚀 SMS RELAY ACTIVE\n")
print(f"📡 Channel: {TARGET_CHANNEL_ID}")
print(f"📱 Device:  {TARGET_DEVICE}")
print(f"📶 SIM:     {SIM_CHOICE}\n")
print("👀 Waiting for messages...\n")

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

        if msg.date.timestamp() < START_TIME:
            return

        if update.effective_chat.id != TARGET_CHANNEL_ID:
            return

        text = msg.text.strip()

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

        if not BASE_URL:
            print("❌ BASE_URL set nahi — Firebase mein base_url daalo\n")
            return

        url = f"{BASE_URL.rstrip('/')}/clients/{TARGET_DEVICE}/webhookEvent/sendSms.json"

        payload = {
            "from": SIM_INDEX,
            "to": to_number,
            "message": sms_body,
            "isSended": False,
        }

        res = requests.patch(url, json=payload, timeout=5)

        if res.status_code == 200:
            print("✅ SENT\n")
        else:
            print(f"❌ FAIL ({res.status_code})\n")

    except Exception as e:
        print("❌ ERROR:", e)


# ===== RUN =====
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), channel_listener))

app.run_polling(drop_pending_updates=True)
