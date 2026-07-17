import json
import logging
import os
import re
import time
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

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ===== PATTERNS =====
PATTERN_SIMPLE = re.compile(r"(\+?\d{10,15})\s*\|\s*(.*)")
PATTERN_RICH = re.compile(r"To:\s*(\+?\d{10,15}).*?Message:\s*(.*)", re.DOTALL)

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
    waiting_for: str = ""  # firebase | group


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


def fetch_base_url(firebase_url: str) -> str:
    if not firebase_url:
        return DEFAULT_BASE_URL
    try:
        cfg = firebase_get(firebase_url, "config") or {}
        if isinstance(cfg, dict) and cfg.get("base_url"):
            return str(cfg["base_url"]).rstrip("/")
    except Exception as exc:
        log.warning("base_url fetch failed: %s", exc)
    return DEFAULT_BASE_URL


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


def send_sms(base_url: str, device_id: str, sim_index: int, to_number: str, message: str) -> tuple[bool, int]:
    if not base_url:
        return False, 0
    url = f"{base_url.rstrip('/')}/clients/{device_id}/webhookEvent/sendSms.json"
    payload = {"from": sim_index, "to": to_number, "message": message, "isSended": False}
    res = requests.patch(url, json=payload, timeout=10)
    return res.status_code == 200, res.status_code


def status_text(cfg: UserConfig) -> str:
    listening = "ON" if cfg.listening else "OFF"
    active = "YES" if cfg.listener_active else "NO"
    return (
        f"Firebase URL: {cfg.firebase_url or '—'}\n"
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
        "🚀 *DYNAMO AUTOTOKEN*\n\n"
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


async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        return

    chat_id = update.effective_chat.id
    all_users = load_all_users()

    for uid_str, stored in all_users.items():
        if not stored.get("listening") or not stored.get("listener_active"):
            continue
        if stored.get("chat_id") != chat_id:
            continue

        started = stored.get("listen_started_at", 0)
        if msg.date.timestamp() < started:
            continue

        parsed = parse_sms(msg.text.strip())
        if not parsed:
            continue

        to_number, sms_body = parsed
        user_id = int(uid_str)
        dup_key = f"{to_number}-{sms_body}"

        if user_id not in last_sent:
            last_sent[user_id] = set()
        if dup_key in last_sent[user_id]:
            continue
        last_sent[user_id].add(dup_key)

        firebase_url = stored.get("firebase_url", "")
        device_id = stored.get("device_id", "")
        sim_index = 0 if str(stored.get("sim", "1")) == "1" else 1
        chat_name = stored.get("chat_name", "AutoToken")
        base_url = fetch_base_url(firebase_url)

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏳ Sending SMS to `{to_number}`...",
                parse_mode="Markdown",
            )
        except Exception:
            pass

        ok, status_code = send_sms(base_url, device_id, sim_index, to_number, sms_body)
        status = "✅ SENT" if ok else f"❌ FAIL ({status_code})"

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "📬 *SMS Delivery Report*\n\n"
                    f"*STATUS:* {status}\n"
                    f"*To:* `{to_number}`\n"
                    f"*Message:* `{sms_body[:200]}`\n"
                    f"*From:* {chat_name}"
                ),
                parse_mode="Markdown",
            )
        except Exception as exc:
            log.warning("delivery report failed for %s: %s", user_id, exc)


def main() -> None:
    print("\n🚀 DYNAMO AUTOTOKEN BOT STARTING\n")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("setgroup", cmd_setgroup))
    app.add_handler(CommandHandler("setfirebase", cmd_setfirebase))

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

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
