# bot.py


# =========================================================
# NSE + INTERNET NEWS TELEGRAM BOT
# GITHUB + RENDER READY VERSION
# =========================================================

import requests
import time
import feedparser
import json
import os
import threading

from datetime import datetime, timedelta, timezone
from nsepython import nsefetch
from flask import Flask

# =========================================================
# KEEP-ALIVE SERVER (for UptimeRobot pings)
# =========================================================

keep_alive_app = Flask(__name__)

@keep_alive_app.route("/")
def home():
    return "Bot is running!", 200

def run_keep_alive():
    keep_alive_app.run(host="0.0.0.0", port=5000)

threading.Thread(target=run_keep_alive, daemon=True).start()

# =========================================================
# IST TIMEZONE & MARKET HOURS
# =========================================================

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_OPEN  = (8,  0)
MARKET_CLOSE = (15, 30)


def ist_now():
    return datetime.now(IST)


def is_market_open():
    now = ist_now()
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t < MARKET_CLOSE


def seconds_until_next_market_open():
    now = ist_now()
    candidate = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1],
                            second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()

# =========================================================
# TELEGRAM CONFIG (FROM ENV VARIABLES)
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# =========================================================
# CUSTOM WATCHLIST
# =========================================================

WATCHLIST = sorted(list(set([

    "ADANIENT",
    "ADANIGREEN",
    "ADANIPORTS",
    "AKZOINDIA",
    "ATGL",
    "AFCONS",
    "ATL",
    "ANANTRAJ",
    "ANTHEM",
    "ARIHANTCAP",
    "ASIANPAINT",
    "BAJAJFINSV",
    "BEL",
    "BLUEDART",
    "BLS",
    "CASTROLIND",
    "CGPOWER",
    "CLEAN",
    "DBL",
    "EID PARRY",
    "FILATEX",
    "FORTIS",
    "GILLETTE",
    "GLOBUSSPR",
    "GSFC",
    "HDFCBANK",
    "HINDCOPPER",
    "HINDUNILVR",
    "HYUNDAI",
    "ITBEES",
    "ICICIAMC",
    "ICICIBANK",
    "IDBI",
    "IFCI",
    "INDUSTOWER",
    "CCAVENUE",
    "INFY",
    "IRB",
    "IRCTC",
    "JIOFIN",
    "JPASSOCIAT",
    "JSWENERGY",
    "KWIL",
    "LATENTVIEW",
    "LGEINDIA",
    "LOTUSDEV",
    "LLOYDSENGG",
    "LT",
    "MARUTI",
    "MAZDOCK",
    "MIRZAINT",
    "MENON PISTON",
    "NATCOPHARM",
    "ONGC",
    "ORIENTCEM",
    "PIDILITIND",
    "POONAWALA",
    "PVRINOX",
    "RTNPOWER",
    "RELIANCE",
    "RELINFRA",
    "RVNL",
    "SANGHI IND",
    "SBIN",
    "SRHHYPOLTD",
    "SUVIDHAA INFO",
    "SUPREMEIND",
    "SUZLON",
    "SWIGGY",
    "SYMPHONY",
    "TATATECH",
    "TITAN",
    "TRENT",
    "VBL"

])))

print("======================================")
print("TOTAL UNIQUE STOCKS:", len(WATCHLIST))
print("======================================")

CHECK_INTERVAL = 120

PRICE_ALERT_THRESHOLD = 3.0

VOLUME_SPIKE_MULTIPLIER = 2.5
VOLUME_HISTORY_WINDOW = 10

CANDLE_SPIKE_MULTIPLIER = 3.0
CANDLE_WINDOW_SECONDS   = 300
CANDLE_HISTORY_KEEP     = 60

IMPORTANT_KEYWORDS = [

    "order",
    "acquisition",
    "results",
    "board meeting",
    "dividend",
    "fund raising",
    "buyback",
    "merger",
    "credit rating",
    "contract",
    "stake",
    "investment",
    "approval",
    "expansion",
    "guidance",
    "profit",
    "loss",
    "sebi",
    "penalty",
    "bankruptcy",
    "default",
    "allotment",
    "bonus",
    "split",
    "rights issue",
    "joint venture"

]

SEEN_FILE = "seen_alerts.json"
PRICE_SEEN_FILE = "seen_price_alerts.json"
VOLUME_HISTORY_FILE = "volume_history.json"
CANDLE_VOLUME_FILE = "candle_volume_history.json"

# =========================================================
# LOAD PREVIOUS ALERTS
# =========================================================

if os.path.exists(SEEN_FILE):

    with open(SEEN_FILE, "r") as f:

        seen_alerts = set(json.load(f))

else:

    seen_alerts = set()

if os.path.exists(PRICE_SEEN_FILE):

    with open(PRICE_SEEN_FILE, "r") as f:

        seen_price_alerts = set(json.load(f))

else:

    seen_price_alerts = set()

if os.path.exists(VOLUME_HISTORY_FILE):

    with open(VOLUME_HISTORY_FILE, "r") as f:

        volume_history = json.load(f)

else:

    volume_history = {}

if os.path.exists(CANDLE_VOLUME_FILE):

    with open(CANDLE_VOLUME_FILE, "r") as f:

        candle_volume_history = json.load(f)

else:

    candle_volume_history = {}

print("Previously stored alerts:", len(seen_alerts))
print("Previously stored price alerts:", len(seen_price_alerts))
print("Stocks with volume history:", len(volume_history))
print("Stocks with candle history:", len(candle_volume_history))

# =========================================================
# SAVE ALERTS
# =========================================================

def save_seen_alerts():

    with open(SEEN_FILE, "w") as f:

        json.dump(list(seen_alerts), f)

def save_seen_price_alerts():

    with open(PRICE_SEEN_FILE, "w") as f:

        json.dump(list(seen_price_alerts), f)

def save_volume_history():

    with open(VOLUME_HISTORY_FILE, "w") as f:

        json.dump(volume_history, f)

def save_candle_volume_history():

    with open(CANDLE_VOLUME_FILE, "w") as f:

        json.dump(candle_volume_history, f)

# =========================================================
# TELEGRAM FUNCTION
# =========================================================

def send_telegram(message):

    try:

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        payload = {

            "chat_id": CHAT_ID,
            "text": message

        }

        response = requests.post(url, data=payload)

        print("Telegram Status:", response.status_code)

    except Exception as e:

        print("Telegram Error:", e)

# =========================================================
# SIMPLE NEWS COMMENT ENGINE
# =========================================================

def generate_comment(headline):

    headline = headline.lower()

    positive_keywords = [

        "order",
        "contract",
        "profit",
        "acquisition",
        "approval",
        "growth",
        "expansion",
        "investment",
        "buyback",
        "dividend",
        "upgrade",
        "partnership",
        "deal"

    ]

    negative_keywords = [

        "loss",
        "penalty",
        "fraud",
        "default",
        "bankruptcy",
        "downgrade",
        "sebi action",
        "decline",
        "fall",
        "warning",
        "investigation"

    ]

    for word in positive_keywords:

        if word in headline:

            return "Positive News → Possible bullish impact"

    for word in negative_keywords:

        if word in headline:

            return "Negative News → Possible bearish impact"

    return "Neutral News → Monitor further developments"

# =========================================================
# STARTUP MESSAGE
# =========================================================

startup_message = f"""
✅ STOCK BOT STARTED

Time:
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Stocks Loaded:
{len(WATCHLIST)}

Stored Alerts:
{len(seen_alerts)}
"""

send_telegram(startup_message)

# =========================================================
# FETCH NSE ANNOUNCEMENTS
# =========================================================

def fetch_nse_announcements():

    try:

        url = "https://www.nseindia.com/api/corporate-announcements?index=equities"

        data = nsefetch(url)

        return data

    except Exception as e:

        print("NSE Fetch Error:", e)

        return []

# =========================================================
# PROCESS NSE ANNOUNCEMENTS
# =========================================================

def process_nse_announcements():

    print("\nChecking NSE announcements...")

    data = fetch_nse_announcements()

    print("Total NSE announcements:", len(data))

    for item in data:

        try:

            symbol = item.get("symbol", "").strip().upper()

            if symbol not in WATCHLIST:
                continue

            headline = item.get("subject", "").strip()

            if not headline:
                continue

            headline_lower = headline.lower()

            matched = any(
                keyword in headline_lower
                for keyword in IMPORTANT_KEYWORDS
            )

            if not matched:
                continue

            unique_key = f"NSE-{symbol}-{headline}"

            if unique_key in seen_alerts:
                continue

            seen_alerts.add(unique_key)

            save_seen_alerts()

            attachment = item.get("attchmntFile", "")

            nse_link = ""

            if attachment:
                nse_link = f"https://www.nseindia.com{attachment}"

            comment = generate_comment(headline)

            message = f"""
🚨 NSE ANNOUNCEMENT

Stock:
{symbol}

Headline:
{headline}

Comment:
{comment}

Source:
{nse_link}

Time:
{datetime.now().strftime('%H:%M:%S')}
"""

            print(message)

            send_telegram(message)

        except Exception as e:

            print("NSE Processing Error:", e)

# =========================================================
# FETCH GOOGLE NEWS
# =========================================================

def fetch_google_news(stock):

    try:

        query = stock.replace(" ", "+")

        rss_url = f"https://news.google.com/rss/search?q={query}+stock"

        feed = feedparser.parse(rss_url)

        return feed.entries

    except Exception as e:

        print("News Fetch Error:", e)

        return []

# =========================================================
# PROCESS INTERNET NEWS
# =========================================================

def process_internet_news():

    print("\nChecking Internet News...")

    for stock in WATCHLIST:

        try:

            entries = fetch_google_news(stock)

            for entry in entries[:3]:

                headline = entry.title.strip()

                if not headline:
                    continue

                headline_lower = headline.lower()

                matched = any(
                    keyword in headline_lower
                    for keyword in IMPORTANT_KEYWORDS
                )

                if not matched:
                    continue

                unique_key = f"NEWS-{stock}-{headline}"

                if unique_key in seen_alerts:
                    continue

                seen_alerts.add(unique_key)

                save_seen_alerts()

                news_link = entry.link

                comment = generate_comment(headline)

                message = f"""
📰 INTERNET NEWS

Stock:
{stock}

Headline:
{headline}

Comment:
{comment}

Source:
{news_link}

Time:
{datetime.now().strftime('%H:%M:%S')}
"""

                print(message)

                send_telegram(message)

        except Exception as e:

            print("Internet News Error:", e)

# =========================================================
# FETCH NSE PRICE DATA
# =========================================================

def fetch_price_data(symbol):

    try:

        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"

        data = nsefetch(url)

        price_info = data.get("priceInfo", {})

        last_price = price_info.get("lastPrice", None)
        open_price = price_info.get("open", None)
        change = price_info.get("change", None)
        pchange = price_info.get("pChange", None)
        high = price_info.get("intraDayHighLow", {}).get("max", None)
        low = price_info.get("intraDayHighLow", {}).get("min", None)

        volume = data.get("securityWiseDP", {}).get("quantityTraded", None)

        if last_price is None or pchange is None:
            return None

        return {
            "symbol": symbol,
            "last_price": last_price,
            "open_price": open_price,
            "change": change,
            "pchange": pchange,
            "high": high,
            "low": low,
            "volume": volume
        }

    except Exception as e:

        print(f"Price Fetch Error [{symbol}]:", e)

        return None

# =========================================================
# PROCESS PRICE MOVEMENT ALERTS
# =========================================================

def process_price_alerts():

    print("\nChecking Price Movements...")

    today = datetime.now().strftime("%Y-%m-%d")

    for symbol in WATCHLIST:

        try:

            data = fetch_price_data(symbol)

            if data is None:
                continue

            pchange = data["pchange"]

            abs_change = abs(pchange)

            if abs_change < PRICE_ALERT_THRESHOLD:
                continue

            direction = "UP" if pchange > 0 else "DOWN"

            unique_key = f"PRICE-{today}-{symbol}-{direction}"

            if unique_key in seen_price_alerts:
                continue

            seen_price_alerts.add(unique_key)

            save_seen_price_alerts()

            arrow = "📈" if direction == "UP" else "📉"

            message = f"""
{arrow} PRICE MOVEMENT ALERT

Stock:
{symbol}

Change:
{pchange:+.2f}%

Last Price:
₹{data['last_price']}

Open:
₹{data['open_price']}

High:
₹{data['high']}

Low:
₹{data['low']}

Threshold:
±{PRICE_ALERT_THRESHOLD}%

Time:
{datetime.now().strftime('%H:%M:%S')}
"""

            print(message)

            send_telegram(message)

            time.sleep(1)

        except Exception as e:

            print(f"Price Alert Error [{symbol}]:", e)

# =========================================================
# PROCESS VOLUME SPIKE ALERTS
# =========================================================

def process_volume_alerts():

    print("\nChecking Volume Spikes...")

    today = datetime.now().strftime("%Y-%m-%d")

    for symbol in WATCHLIST:

        try:

            data = fetch_price_data(symbol)

            if data is None:
                continue

            volume = data.get("volume", None)

            if volume is None or volume == 0:
                continue

            history = volume_history.get(symbol, [])

            if len(history) >= VOLUME_HISTORY_WINDOW:

                avg_volume = sum(history) / len(history)

                if avg_volume > 0 and volume >= VOLUME_SPIKE_MULTIPLIER * avg_volume:

                    unique_key = f"VOLUME-{today}-{symbol}"

                    if unique_key not in seen_price_alerts:

                        seen_price_alerts.add(unique_key)

                        save_seen_price_alerts()

                        message = f"""
🔊 VOLUME SPIKE ALERT

Stock:
{symbol}

Today Volume:
{int(volume):,}

Avg Volume ({VOLUME_HISTORY_WINDOW} readings):
{int(avg_volume):,}

Spike:
{volume / avg_volume:.1f}x average

Last Price:
₹{data['last_price']}

Change:
{data['pchange']:+.2f}%

Time:
{datetime.now().strftime('%H:%M:%S')}
"""

                        print(message)

                        send_telegram(message)

                        time.sleep(1)

            history.append(volume)

            volume_history[symbol] = history[-VOLUME_HISTORY_WINDOW:]

            save_volume_history()

        except Exception as e:

            print(f"Volume Alert Error [{symbol}]:", e)

# =========================================================
# PROCESS 5-MIN CANDLE VOLUME SPIKE ALERTS
# =========================================================

def process_candle_volume_spikes():

    print("\nChecking 5-Min Candle Volume Spikes...")

    now_ts = int(time.time())

    for symbol in WATCHLIST:

        try:

            data = fetch_price_data(symbol)

            if data is None:
                continue

            current_vol = data.get("volume", None)

            if current_vol is None or current_vol == 0:
                continue

            history = candle_volume_history.get(symbol, [])

            history.append({"ts": now_ts, "vol": current_vol})

            history = history[-CANDLE_HISTORY_KEEP:]

            candle_volume_history[symbol] = history

            save_candle_volume_history()

            target_ts = now_ts - CANDLE_WINDOW_SECONDS

            past_entry = None

            for entry in reversed(history[:-1]):

                if entry["ts"] <= target_ts:

                    past_entry = entry

                    break

            if past_entry is None:
                continue

            candle_vol = current_vol - past_entry["vol"]

            if candle_vol <= 0:
                continue

            all_candle_vols = []

            for i in range(1, len(history)):

                ref_ts = history[i]["ts"] - CANDLE_WINDOW_SECONDS

                base = None

                for j in range(i - 1, -1, -1):

                    if history[j]["ts"] <= ref_ts:

                        base = history[j]

                        break

                if base is not None:

                    cv = history[i]["vol"] - base["vol"]

                    if cv > 0:

                        all_candle_vols.append(cv)

            if len(all_candle_vols) < 3:
                continue

            avg_candle_vol = sum(all_candle_vols) / len(all_candle_vols)

            if avg_candle_vol <= 0:
                continue

            if candle_vol < CANDLE_SPIKE_MULTIPLIER * avg_candle_vol:
                continue

            now_ist = ist_now()

            minute_bucket = (now_ist.minute // 5) * 5

            unique_key = f"CANDLE-{now_ist.strftime('%Y%m%d-%H')}{minute_bucket:02d}-{symbol}"

            if unique_key in seen_price_alerts:
                continue

            seen_price_alerts.add(unique_key)

            save_seen_price_alerts()

            message = f"""
🕯 5-MIN CANDLE VOLUME SPIKE

Stock:
{symbol}

Candle Volume:
{int(candle_vol):,}

Avg Candle Volume:
{int(avg_candle_vol):,}

Spike:
{candle_vol / avg_candle_vol:.1f}x average

Last Price:
₹{data['last_price']}

Change:
{data['pchange']:+.2f}%

Time:
{now_ist.strftime('%H:%M:%S IST')}
"""

            print(message)

            send_telegram(message)

            time.sleep(1)

        except Exception as e:

            print(f"Candle Volume Error [{symbol}]:", e)

# =========================================================
# HEARTBEAT MESSAGE
# =========================================================

def send_heartbeat():

    message = f"""
🤖 BOT RUNNING

Time:
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Stocks:
{len(WATCHLIST)}

Stored Alerts:
{len(seen_alerts)}

Next Check:
{CHECK_INTERVAL} sec
"""

    send_telegram(message)

# =========================================================
# MAIN LOOP
# =========================================================

print("======================================")
print("BOT STARTED")
print("======================================")

while True:

    try:

        if not is_market_open():

            secs = seconds_until_next_market_open()
            hrs  = int(secs // 3600)
            mins = int((secs % 3600) // 60)
            now_ist = ist_now().strftime('%Y-%m-%d %H:%M:%S IST')

            print(f"\n⏸  Market closed at {now_ist}. Next open in {hrs}h {mins}m. Sleeping...")

            time.sleep(min(secs, 3600))

            continue

        print("\n======================================")
        print("NEW CYCLE")
        print(ist_now().strftime('%Y-%m-%d %H:%M:%S IST'))
        print("======================================")

        process_nse_announcements()

        process_internet_news()

        process_price_alerts()

        process_volume_alerts()

        process_candle_volume_spikes()

        send_heartbeat()

        print(f"\nSleeping {CHECK_INTERVAL} sec...\n")

    except Exception as e:

        error_message = f"""
❌ BOT ERROR

{str(e)}

Time:
{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}
"""

        print(error_message)

        send_telegram(error_message)

    time.sleep(CHECK_INTERVAL)
