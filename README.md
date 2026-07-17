# DYNAMO AutoToken Bot

Telegram par setup wala auto token / SMS relay bot — screenshot jaisa same flow.

## Features

- 👥 Group/Channel set (`/setgroup` ya **👥 Change**)
- 🔥 Firebase URL set (`/setfirebase` ya **🔥 Change Firebase**)
- 📱 Online devices Firebase se list
- 🔢 SIM 1 / SIM 2 select
- ▶️ Start Listen — channel messages sunna
- 📬 SMS Delivery Report — har SMS ka status

## Quick Start

```bash
pip install -r requirements.txt
python tgtoken.py
```

Telegram par bot kholo → `/start`

## Setup Flow (screenshot jaisa)

| Step | Kya karna hai |
|------|---------------|
| 1 | **👥 Change** → chat ID `-1003553669855` bhejo ya group se forward karo |
| 2 | **🔥 Change Firebase** → `https://base-e3797-default-rtdb.firebaseio.com` |
| 3 | **📱 Change Device** → online device select karo |
| 4 | **🔢 Select SIM** → SIM 1 ya 2 |
| 5 | **▶️ Start Listen** → listening ON |

## Firebase Structure

Apne Firebase Realtime Database mein ye banao:

```json
{
  "config": {
    "base_url": "https://apna-sms-api-url.com"
  },
  "clients": {
    "device-id-1": { "online": true },
    "device-id-2": { "online": true }
  }
}
```

- `config/base_url` — SMS gateway API URL
- `clients/` — online device IDs (Android app yahan register karti hai)

Example: `firebase-config.example.json`

## Bot Token & Chat ID

Already set in code:
- Bot Token: env `BOT_TOKEN` ya default in `tgtoken.py`
- Chat ID: bot ke through **👥 Change** se save hoti hai

## Important — Bot Privacy

@BotFather → `/setprivacy` → **Disable**

Ya bot ko channel/group ka **Admin** banao — warna messages nahi padh payega.

## Hosting (24/7)

Railway / Render / VPS:

```bash
export BOT_TOKEN="8901092528:AAFQ23IMYD5oVL1cNEquLphWc5RYij0FJZw"
export DEFAULT_BASE_URL="https://apna-sms-api-url.com"   # optional fallback
python tgtoken.py
```

User settings `user_data.json` mein save hoti hain (restart ke baad bhi rahengi).

## Message Format (channel mein)

```
+919876543210 | Your OTP is 123456
```

ya

```
To: +919876543210
Message: Your OTP is 123456
```

## Menu Buttons

| Button | Kaam |
|--------|------|
| ▶️ Start Listen | Listening shuru |
| 📱 Change Device | Device badlo |
| 🔥 Change Firebase | Firebase URL badlo |
| 📊 Status | Config dekho |
| 👥 Change | Group/Channel badlo |
| ❓ Help | Help |
