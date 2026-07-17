# Auto Token Bot (SMS Relay)

Telegram channel se SMS/OTP sun kar device API par auto-forward karta hai.  
Config **Firebase Realtime Database** se load hoti hai.

## Firebase Setup (Step by Step)

### 1. Firebase Project banao

1. [Firebase Console](https://console.firebase.google.com/) kholo
2. **Add project** → naam do → Create
3. Left menu → **Build** → **Realtime Database**
4. **Create Database** → region choose karo → **Start in test mode** (baad mein rules tight kar sakte ho)

### 2. Database URL copy karo

Realtime Database page par top par URL dikhega:

```
https://YOUR-PROJECT-default-rtdb.firebaseio.com
```

Ye `FIREBASE_URL` hai.

### 3. Config node banao

Database mein **+** dabao aur ye structure banao (`config` naam ka node):

```json
{
  "config": {
    "bot_token": "8901092528:AAFQ23IMYD5oVL1cNEquLphWc5RYij0FJZw",
    "channel_id": -1003553669855,
    "base_url": "https://apna-sms-api-url.com",
    "device_id": "apna-device-id",
    "sim": "1"
  }
}
```

| Field | Kya hai |
|-------|---------|
| `bot_token` | @BotFather se mila token |
| `channel_id` | Telegram channel ID (minus wali) |
| `base_url` | SMS gateway API ka base URL |
| `device_id` | Device panel se mila ID |
| `sim` | `1` ya `2` |

> Example file: `firebase-config.example.json`

### 4. Firebase Rules (test ke liye)

```json
{
  "rules": {
    ".read": true,
    ".write": true
  }
}
```

> Production mein sirf apne server ko read access do.

---

## Bot chalana

```bash
pip install -r requirements.txt
```

**Firebase URL set karke run karo:**

```bash
export FIREBASE_URL="https://YOUR-PROJECT-default-rtdb.firebaseio.com"
python tgtoken.py
```

Windows:

```cmd
set FIREBASE_URL=https://YOUR-PROJECT-default-rtdb.firebaseio.com
python tgtoken.py
```

Agar `FIREBASE_URL` set nahi kiya to bot code ke andar wali fallback values use karega.

---

## Hosting (24/7 chalane ke liye)

### Railway / Render / VPS

Environment variables set karo:

| Variable | Value |
|----------|-------|
| `FIREBASE_URL` | `https://YOUR-PROJECT-default-rtdb.firebaseio.com` |
| `FIREBASE_CONFIG_PATH` | `config` (optional, default) |

Start command:

```bash
python tgtoken.py
```

Firebase mein config change karoge to bot restart ke baad nayi values load hongi.

---

## Telegram Setup

1. Bot ko channel mein **Admin** banao
2. Channel mein test message bhejo:

```
+919876543210 | Test OTP 123456
```

Terminal mein `📤` aur `✅ SENT` dikhna chahiye.

---

## Supported Message Formats

```
+919876543210 | Your OTP is 123456
```

```
To: +919876543210
Message: Your OTP is 123456
```
