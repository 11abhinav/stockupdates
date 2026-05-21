# NSE Market Intelligence Telegram Bot

## Deploy on Railway

### 1. Environment Variables
Set these in Railway → Variables:

| Variable | Value |
|----------|-------|
| `BOT_TOKEN` | Your Telegram bot token (from @BotFather) |
| `CHAT_ID` | Your Telegram chat/channel ID |

### 2. Deploy
Push this folder to a GitHub repo, then connect it to Railway.
Railway auto-detects `Procfile` and `requirements.txt`.

---

## Features

| Feature | Details |
|---------|---------|
| 📰 Google News | Fresh news per stock (≤12 hrs), scanned every 10 mins |
| 📢 NSE Announcements | Corporate announcements from NSE API |
| 📈 Price Alerts | Triggers on >3% move (up or down) |
| 🚀 Day High Breakout | Price at/near intraday high with >1% gain |
| 📊 Daily Volume Spike | Today's volume vs 20-day rolling average (2.5x threshold) |
| ⚡ 5-Min Vol Breakout | Real candle volume 3x average |
| ⚡ 10-Min Vol Breakout | Real candle volume 3x average |
| ⚡ 15-Min Vol Breakout | Real candle volume 2.5x average |
| 🌙 Smart Sleep | Sleeps on weekends, holidays, and after market close |
| 📋 EOD Summary | End-of-day summary with top gainers/losers + alert counts |

## Active Hours
- **Pre-market (8:00–9:15 AM IST):** News & announcements only
- **Market hours (9:15 AM–3:30 PM IST):** All alerts active
- **After close / weekends / holidays:** Bot sleeps

## Thresholds (edit top of `bot.py`)
```python
PRICE_ALERT_THRESHOLD        = 3.0    # % for price alert
DAY_HIGH_BUFFER_PCT          = 0.10   # % within day high for breakout
VOLUME_SPIKE_MULTIPLIER      = 2.5    # daily volume spike vs avg
FIVE_MIN_SPIKE_MULTIPLIER    = 3.0
TEN_MIN_SPIKE_MULTIPLIER     = 3.0
FIFTEEN_MIN_SPIKE_MULTIPLIER = 2.5
NEWS_MAX_AGE_HOURS           = 12
```

## Notes
- `nsepython` removed — replaced with direct NSE API calls with proper session/cookie handling
- Symbols with spaces (`EID PARRY`, `MENON PISTON`, etc.) corrected to valid NSE codes
- All state persisted to JSON files (safe atomic writes)
- HTML parse mode used in Telegram for cleaner formatting
