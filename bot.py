# =========================================================
# ADVANCED NSE MOMENTUM + VOLUME BREAKOUT TELEGRAM BOT
# FINAL STABLE VERSION
# =========================================================
#
# FEATURES
# ---------------------------------------------------------
#
# ✅ Google News Alerts (24x7)
# ✅ NSE Corporate Announcement Alerts (24x7)
# ✅ NSE Notice PDF Links
# ✅ Rounded OHLC Candle Engine
# ✅ 5m / 10m / 15m Candle Tracking
# ✅ Multi Candle Breakout Detection
# ✅ Day High Breakout Detection
# ✅ ±3% Daily Move Alerts
# ✅ Volume Expansion Detection
# ✅ Duplicate Alert Prevention
# ✅ Railway Compatible
# ✅ Exception Reporting to Telegram
# ✅ Persistent Candle Storage
# ✅ Invalid NSE Data Protection
#
# =========================================================
# ALERT LOGIC
# =========================================================
#
# 🚀 MULTI CANDLE BREAKOUT
#
# Triggered when:
#
# Current price breaks:
#
# - previous 5m candle HIGH
# - previous 10m candle HIGH
# - previous 15m candle HIGH
#
# ---------------------------------------------------------
#
# 🔥 DAY HIGH BREAKOUT
#
# Triggered when:
#
# Current price >= official NSE day high
#
# One alert per 5m candle.
#
# ---------------------------------------------------------
#
# 📈 PRICE MOVE ALERT
#
# Triggered when:
#
# stock moves:
#
# +3%
# OR
# -3%
#
# from previous close.
#
# ---------------------------------------------------------
#
# 📊 VOLUME BREAKOUT
#
# Triggered when:
#
# current 5m candle volume >
# previous 5m candle volume
#
# AND
#
# current 10m candle volume >
# previous 10m candle volume
#
# AND
#
# current 15m candle volume >
# previous 15m candle volume
#
# ---------------------------------------------------------
#
# 📰 NEWS + NSE ANNOUNCEMENTS
#
# Runs 24x7
#
# ---------------------------------------------------------
#
# 📈 MARKET ALERTS
#
# Run ONLY during:
#
# 8:45 AM → 4:00 PM IST
#
# =========================================================

import os
import json
import time
import threading
import requests
import feedparser

from flask import Flask
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================================================
# FLASK SERVER
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "BOT RUNNING ✅", 200

threading.Thread(
    target=lambda: app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    ),
    daemon=True
).start()

# =========================================================
# ENV
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# =========================================================
# CONFIG
# =========================================================

CHECK_INTERVAL = 60

PRICE_MOVE_THRESHOLD = 3.0

NEWS_MAX_AGE_MINUTES = 60

IST = timezone(timedelta(hours=5, minutes=30))

ALERT_START = (8, 45)
ALERT_END = (16, 0)

# =========================================================
# WATCHLIST
# =========================================================

WATCHLIST = sorted(list(set([

    "ADANIENT",
    "ADANIGREEN",
    "ADANIPORTS",
    "AKZOINDIA",
    "AFCONS",
    "ANANTRAJ",
    "ANTHEM",
    "ARIHANTCAP",
    "ASIANPAINT",
    "ATGL",
    "ATL",
    "BAJAJFINSV",
    "BEL",
    "BLS",
    "BLUEDART",
    "CASTROLIND",
    "CCAVENUE",
    "CGPOWER",
    "CLEAN",
    "DBL",
    "EIDPARRY",
    "FILATEX",
    "FORTIS",
    "GILLETTE",
    "GLOBUSSPR",
    "GSFC",
    "HDFCBANK",
    "HINDCOPPER",
    "HINDUNILVR",
    "HYUNDAI",
    "ICICIAMC",
    "ICICIBANK",
    "IDBI",
    "IFCI",
    "INDUSTOWER",
    "INFY",
    "IRB",
    "IRCTC",
    "ITBEES",
    "JIOFIN",
    "JPASSOCIAT",
    "JSWENERGY",
    "KWIL",
    "LATENTVIEW",
    "LGEINDIA",
    "LLOYDSENGG",
    "LOTUSDEV",
    "LT",
    "MARUTI",
    "MAZDOCK",
    "MENNPIS",
    "MIRZAINT",
    "NATCOPHARM",
    "ONGC",
    "ORIENTCEM",
    "PFC",
    "PIDILITIND",
    "POONAWALLA",
    "PVRINOX",
    "RELIANCE",
    "RELINFRA",
    "RTNPOWER",
    "RVNL",
    "SANGHIIND",
    "SBIN",
    "SRHHYPOLTD",
    "SUPREMEIND",
    "SUVIDHAA",
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
CANDLES_FILE = "candles.json"

# =========================================================
# SAFE HELPERS
# =========================================================

def safe_float(v):

    try:

        if v in [None, "", "-", "None"]:
            return 0.0

        return float(v)

    except:
        return 0.0

def safe_int(v):

    try:

        if v in [None, "", "-", "None"]:
            return 0

        return int(float(v))

    except:
        return 0

# =========================================================
# JSON HELPERS
# =========================================================

def load_json(filename, default):

    try:

        if os.path.exists(filename):

            with open(filename, "r") as f:
                return json.load(f)

    except:
        pass

    return default

def save_json(data, filename):

    tmp = filename + ".tmp"

    with open(tmp, "w") as f:
        json.dump(data, f)

    os.replace(tmp, filename)

# =========================================================
# LOAD STATE
# =========================================================

seen_alerts = set(load_json(SEEN_FILE, []))

candles = load_json(CANDLES_FILE, {})

# =========================================================
# TIME HELPERS
# =========================================================

def ist_now():
    return datetime.now(IST)

def is_alert_hours():

    now = ist_now()

    if now.weekday() >= 5:
        return False

    t = (now.hour, now.minute)

    return ALERT_START <= t < ALERT_END

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(msg):

    try:

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": msg[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=20
        )

    except Exception as e:

        print("TELEGRAM ERROR:", e)

# =========================================================
# NSE SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

def init_nse():

    try:
        session.get(
            "https://www.nseindia.com",
            timeout=10
        )
    except:
        pass

init_nse()

def nse_get(url):

    for _ in range(3):

        try:

            r = session.get(url, timeout=15)

            if r.status_code in [401, 403]:

                init_nse()
                continue

            r.raise_for_status()

            return r.json()

        except:

            time.sleep(2)

    return None
