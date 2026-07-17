# Auto Token Bot (SMS Relay)

Telegram channel se aane wale SMS/OTP messages ko automatically device API par forward karta hai.

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python tgtoken.py
```

Start par ye puchega:
1. **Device ID** — apna device ID daalo
2. **SIM (1/2)** — kaunsi SIM use karni hai

## Config (`tgtoken.py` mein)

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token |
| `BASE_URL` | SMS gateway API base URL (abhi empty hai — apna URL daalo) |
| `TARGET_CHANNEL_ID` | Jis Telegram channel se messages sunne hain |

## Supported Message Formats

**Simple:**
```
+919876543210 | Your OTP is 123456
```

**Rich:**
```
To: +919876543210
Message: Your OTP is 123456
```

## Kaise kaam karta hai

1. Bot Telegram channel par naye messages sunta hai
2. Phone number + message parse karta hai
3. `BASE_URL/clients/{DEVICE_ID}/webhookEvent/sendSms.json` par PATCH request bhejta hai
4. Duplicate messages ignore karta hai
