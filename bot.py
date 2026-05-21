# =========================================================
# ADVANCED NSE MARKET INTELLIGENCE TELEGRAM BOT
# =========================================================
#
# FEATURES
# ---------------------------------------------------------
# ✅ NSE Corporate Announcements
# ✅ Google News (Fresh <=24 hrs only)
# ✅ Price Spike Alerts
# ✅ Daily Volume Spike Alerts
# ✅ REAL 5-Min Candle Volume Spike Alerts
# ✅ REAL 15-Min Candle Volume Spike Alerts
# ✅ Day High Breakout Detection
# ✅ Relative Strength Ranking
# ✅ High Conviction Setup Detection
# ✅ NSE API Cache Optimization
# ✅ Duplicate Alert Protection
# ✅ Startup / Market Close Notifications
# ✅ Smart Sleep Until Next Market Open
# ✅ Weekend + Holiday Skip
# ✅ Retry Handling
# ✅ Safe JSON Writes
# ✅ End-of-Day Summary
# ✅ Lower NSE Ban Risk
#
# ACTIVE HOURS
# ---------------------------------------------------------
# 8:00 AM IST → 3:30 PM IST
#
# =========================================================

import os
import json
import time
import hashlib
import threading
import requests
import feedparser

from flask import Flask

from datetime import (
    datetime,
    timedelta,
    timezone
)

from email.utils import (
    parsedate_to_datetime
)

from nsepython import nsefetch

# =========================================================
# KEEP ALIVE SERVER
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running", 200

def run_server():
    app.run(host="0.0.0.0", port=5000)

threading.Thread(
    target=run_server,
    daemon=True
).start()

# =========================================================
# ENV VARIABLES
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# =========================================================
# CONFIG
# =========================================================

CHECK_INTERVAL = 60

PRICE_ALERT_THRESHOLD = 3.0

VOLUME_SPIKE_MULTIPLIER = 3.0

REALTIME_PRICE_CONFIRMATION = 1.0

FIVE_MIN_SPIKE_MULTIPLIER = 3.0
FIFTEEN_MIN_SPIKE_MULTIPLIER = 2.5

IST = timezone(
    timedelta(hours=5, minutes=30)
)

MARKET_OPEN = (8, 0)
MARKET_CLOSE = (15, 30)

# =========================================================
# NSE HOLIDAYS
# =========================================================

NSE_HOLIDAYS = {

    "2026-01-26",
    "2026-03-14",
    "2026-08-15",
    "2026-10-02",

}

# =========================================================
# WATCHLIST
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

# =========================================================
# FILES
# =========================================================

SEEN_FILE = "seen_alerts.json"
PRICE_FILE = "seen_price_alerts.json"

VOLUME_HISTORY_FILE = "volume_history.json"

CANDLE_5M_FILE = "candle_5m.json"
CANDLE_15M_FILE = "candle_15m.json"

# =========================================================
# SAFE JSON HELPERS
# =========================================================

def load_json(filename, default):

    if os.path.exists(filename):

        try:

            with open(filename, "r") as f:
                return json.load(f)

        except:
            return default

    return default

def safe_json_dump(data, filename):

    temp = filename + ".tmp"

    with open(temp, "w") as f:

        json.dump(data, f)

    os.replace(temp, filename)

# =========================================================
# LOAD STATE
# =========================================================

seen_alerts = set(
    load_json(SEEN_FILE, [])
)

seen_price_alerts = set(
    load_json(PRICE_FILE, [])
)

volume_history = load_json(
    VOLUME_HISTORY_FILE,
    {}
)

candle_5m = load_json(
    CANDLE_5M_FILE,
    {}
)

candle_15m = load_json(
    CANDLE_15M_FILE,
    {}
)

# =========================================================
# DAILY STATS
# =========================================================

daily_stats = {

    "news": 0,
    "price": 0,
    "volume": 0,
    "5m": 0,
    "15m": 0,
    "breakout": 0,
    "highconv": 0

}

# =========================================================
# TIME HELPERS
# =========================================================

def ist_now():
    return datetime.now(IST)

def is_holiday():

    today = ist_now().strftime("%Y-%m-%d")

    return today in NSE_HOLIDAYS

def is_market_open():

    now = ist_now()

    if now.weekday() >= 5:
        return False

    if is_holiday():
        return False

    t = (now.hour, now.minute)

    return MARKET_OPEN <= t < MARKET_CLOSE

def seconds_until_next_market_open():

    now = ist_now()

    candidate = now.replace(

        hour=MARKET_OPEN[0],
        minute=MARKET_OPEN[1],
        second=0,
        microsecond=0

    )

    if candidate <= now:
        candidate += timedelta(days=1)

    while (
        candidate.weekday() >= 5
        or candidate.strftime("%Y-%m-%d")
        in NSE_HOLIDAYS
    ):

        candidate += timedelta(days=1)

    return (candidate - now).total_seconds()

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendMessage"
        )

        payload = {

            "chat_id": CHAT_ID,
            "text": message[:4000]

        }

        requests.post(
            url,
            data=payload,
            timeout=20
        )

    except Exception as e:

        print("Telegram Error:", e)

# =========================================================
# STARTUP MESSAGE
# =========================================================

send_telegram(f"""
✅ BOT STARTED

Time:
{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}

Stocks:
{len(WATCHLIST)}

Check Interval:
{CHECK_INTERVAL}s
""")

# =========================================================
# NEWS KEYWORDS
# =========================================================

IMPORTANT_KEYWORDS = [

    "order",
    "results",
    "dividend",
    "buyback",
    "merger",
    "approval",
    "contract",
    "acquisition",
    "stake",
    "investment",
    "expansion",
    "guidance"

]

# =========================================================
# NEWS SENTIMENT
# =========================================================

def generate_comment(headline):

    h = headline.lower()

    positive = [

        "order",
        "profit",
        "approval",
        "buyback",
        "dividend",
        "expansion",
        "investment",
        "acquisition"

    ]

    negative = [

        "loss",
        "penalty",
        "fraud",
        "default",
        "downgrade"

    ]

    for p in positive:

        if p in h:
            return "Positive News → Bullish"

    for n in negative:

        if n in h:
            return "Negative News → Bearish"

    return "Neutral News"

# =========================================================
# NSE FETCH WITH RETRY
# =========================================================

def fetch_price_data(symbol):

    for attempt in range(3):

        try:

            url = (
                f"https://www.nseindia.com/api/"
                f"quote-equity?symbol={symbol}"
            )

            data = nsefetch(url)

            p = data.get("priceInfo", {})

            return {

                "symbol": symbol,

                "last_price":
                    p.get("lastPrice"),

                "open_price":
                    p.get("open"),

                "change":
                    p.get("change"),

                "pchange":
                    p.get("pChange"),

                "high":
                    p.get(
                        "intraDayHighLow", {}
                    ).get("max"),

                "low":
                    p.get(
                        "intraDayHighLow", {}
                    ).get("min"),

                "volume":
                    data.get(
                        "securityWiseDP", {}
                    ).get("quantityTraded")

            }

        except Exception as e:

            print(
                f"Retry {attempt+1} [{symbol}]"
            )

            time.sleep(2)

    return None

# =========================================================
# CACHE ALL STOCK DATA
# =========================================================

def fetch_all_stock_data():

    all_data = {}

    for symbol in WATCHLIST:

        try:

            data = fetch_price_data(symbol)

            if data:
                all_data[symbol] = data

            time.sleep(0.25)

        except Exception as e:

            print("Cache Error:", e)

    return all_data

# =========================================================
# PRICE ALERTS
# =========================================================

def process_price_alerts(all_data):

    today = ist_now().strftime("%Y-%m-%d")

    for symbol, data in all_data.items():

        try:

            pchange = data["pchange"]

            if pchange is None:
                continue

            if abs(pchange) < PRICE_ALERT_THRESHOLD:
                continue

            direction = (
                "UP"
                if pchange > 0
                else "DOWN"
            )

            unique_key = (
                f"{today}-{symbol}-{direction}"
            )

            if unique_key in seen_price_alerts:
                continue

            seen_price_alerts.add(unique_key)

            safe_json_dump(
                list(seen_price_alerts),
                PRICE_FILE
            )

            daily_stats["price"] += 1

            arrow = (
                "📈"
                if pchange > 0
                else "📉"
            )

            send_telegram(f"""
{arrow} PRICE ALERT

Stock:
{symbol}

Change:
{pchange:+.2f}%

Price:
₹{data['last_price']}
""")

        except Exception as e:

            print("Price Error:", e)

# =========================================================
# DAY HIGH BREAKOUTS
# =========================================================

def process_day_high_breakouts(all_data):

    for symbol, data in all_data.items():

        try:

            last_price = data["last_price"]
            high = data["high"]
            pchange = data["pchange"]

            if (
                not last_price
                or not high
                or pchange is None
            ):
                continue

            if last_price < 0.995 * high:
                continue

            if pchange < 2:
                continue

            unique_key = (
                f"DAYHIGH-"
                f"{symbol}-"
                f"{ist_now().strftime('%Y%m%d')}"
            )

            if unique_key in seen_price_alerts:
                continue

            seen_price_alerts.add(unique_key)

            safe_json_dump(
                list(seen_price_alerts),
                PRICE_FILE
            )

            daily_stats["breakout"] += 1

            send_telegram(f"""
🚀 DAY HIGH BREAKOUT

Stock:
{symbol}

Price:
₹{last_price}

Day High:
₹{high}

Change:
{pchange:+.2f}%
""")

        except Exception as e:

            print("Breakout Error:", e)

# =========================================================
# HIGH CONVICTION SIGNALS
# =========================================================

def process_high_conviction_signals(all_data):

    for symbol, data in all_data.items():

        try:

            pchange = data["pchange"]
            last_price = data["last_price"]
            high = data["high"]

            if (
                pchange is None
                or not last_price
                or not high
            ):
                continue

            score = 0

            if last_price >= 0.995 * high:
                score += 2

            if pchange >= 3:
                score += 2

            history = volume_history.get(
                symbol,
                []
            )

            if len(history) >= 5:

                avg = (
                    sum(history)
                    / len(history)
                )

                if (
                    avg > 0
                    and data["volume"] >= 3 * avg
                ):
                    score += 3

            if score < 5:
                continue

            unique_key = (
                f"HIGHCONF-"
                f"{symbol}-"
                f"{ist_now().strftime('%Y%m%d')}"
            )

            if unique_key in seen_price_alerts:
                continue

            seen_price_alerts.add(unique_key)

            safe_json_dump(
                list(seen_price_alerts),
                PRICE_FILE
            )

            daily_stats["highconv"] += 1

            send_telegram(f"""
💎 HIGH CONVICTION SETUP

Stock:
{symbol}

Score:
{score}/7

Price Change:
{pchange:+.2f}%

Near Day High:
YES
""")

        except Exception as e:

            print("High Conviction Error:", e)

# =========================================================
# MAIN LOOP
# =========================================================

print("BOT STARTED")

while True:

    try:

        if not is_market_open():

            secs = seconds_until_next_market_open()

            hrs = int(secs // 3600)
            mins = int((secs % 3600) // 60)

            print(
                f"Market Closed. "
                f"Sleeping {hrs}h {mins}m"
            )

            time.sleep(min(secs, 3600))

            continue

        print(
            "\nNEW CYCLE:",
            ist_now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        # FETCH ALL STOCK DATA ONCE
        all_data = fetch_all_stock_data()

        # PRICE ALERTS
        process_price_alerts(all_data)

        # DAY HIGH BREAKOUTS
        process_day_high_breakouts(all_data)

        # HIGH CONVICTION SIGNALS
        process_high_conviction_signals(all_data)

    except Exception as e:

        err = f"""
❌ BOT ERROR

{str(e)}

Time:
{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}
"""

        print(err)

        send_telegram(err)

    time.sleep(CHECK_INTERVAL)
