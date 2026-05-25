# =========================================================
# ADVANCED NSE MOMENTUM + VOLUME BREAKOUT TELEGRAM BOT
# =========================================================
#
# FEATURES
# ---------------------------------------------------------
# ✅ 3% Price Move Alerts
# ✅ Continuous Running
# ✅ Detailed Logs
# ✅ Railway Compatible
# ✅ NSE Session Handling
# ✅ Duplicate Alert Protection
# ✅ Persistent Candle Storage
# ✅ 5m / 10m / 15m Candle Tracking
# ✅ Telegram Alerts
# ✅ NSE News Scan Support
# ✅ Healthcheck Endpoint
# ✅ Automatic Retry Logic
#
# =========================================================

print("🚀 SCRIPT STARTED", flush=True)

# =========================================================
# IMPORTS
# =========================================================

import os
import sys
import json
import time
import logging
import threading
import requests
import feedparser

from flask import Flask
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)

# =========================================================
# LOGGER CONFIGURATION
# =========================================================
#
# force=True
#   prevents Railway / gunicorn log suppression
#
# stream=sys.stdout
#   ensures Railway captures logs immediately
#
# =========================================================

logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s | %(levelname)s | %(message)s",

    datefmt="%Y-%m-%d %H:%M:%S",

    force=True,

    stream=sys.stdout
)

logger = logging.getLogger()

logger.setLevel(logging.INFO)

logger.info("=" * 80)
logger.info("🚀 SCRIPT STARTED")
logger.info("=" * 80)

# =========================================================
# FLASK HEALTHCHECK SERVER
# =========================================================
#
# Railway requires an HTTP service
#
# This endpoint prevents:
# - idle shutdowns
# - unhealthy deployment status
#
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():

    logger.info("🌐 Healthcheck hit")

    print(
        "🌐 Healthcheck hit",
        flush=True
    )

    return "BOT RUNNING ✅", 200

# =========================================================
# START FLASK SERVER IN BACKGROUND THREAD
# =========================================================

threading.Thread(

    target=lambda: app.run(

        host="0.0.0.0",

        port=int(os.environ.get("PORT", 5000))
    ),

    daemon=True

).start()

# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================
#
# BOT_TOKEN
#   Telegram Bot Token
#
# CHAT_ID
#   Telegram Group/User ID
#
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

CHAT_ID = os.environ.get("CHAT_ID")

if not BOT_TOKEN:

    logger.error("❌ BOT_TOKEN missing")

if not CHAT_ID:

    logger.error("❌ CHAT_ID missing")

# =========================================================
# CONFIGURATION
# =========================================================

# Main loop sleep interval
CHECK_INTERVAL = 60

# 3% move threshold
PRICE_MOVE_THRESHOLD = 3.0

# News age filter
NEWS_MAX_AGE_MINUTES = 60

# Indian timezone
IST = timezone(
    timedelta(hours=5, minutes=30)
)

# Market active hours
ALERT_START = (8, 45)
ALERT_END = (16, 0)

# =========================================================
# CUSTOM WATCHLIST
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

logger.info(
    f"📊 Total Watchlist Stocks: "
    f"{len(WATCHLIST)}"
)

# =========================================================
# FILE STORAGE
# =========================================================
#
# seen_alerts.json
#   prevents duplicate alerts
#
# candles.json
#   stores 5m / 10m / 15m candles
#
# =========================================================

SEEN_FILE = "seen_alerts.json"

CANDLES_FILE = "candles.json"

# =========================================================
# SAFE TYPE HELPERS
# =========================================================

def safe_float(v):

    """
    Safely convert value to float
    """

    try:

        if v in [None, "", "-", "None"]:
            return 0.0

        return float(v)

    except:
        return 0.0

def safe_int(v):

    """
    Safely convert value to integer
    """

    try:

        if v in [None, "", "-", "None"]:
            return 0

        return int(float(v))

    except:
        return 0

# =========================================================
# JSON STORAGE HELPERS
# =========================================================

def save_json(data, filename):

    """
    Atomic JSON save
    Prevents corruption
    """

    try:

        tmp = filename + ".tmp"

        with open(tmp, "w") as f:
            json.dump(data, f)

        os.replace(tmp, filename)

        logger.info(
            f"💾 Saved JSON: {filename}"
        )

    except Exception as e:

        logger.exception(
            f"SAVE JSON ERROR: {e}"
        )

def load_json(filename, default):

    """
    Load JSON safely
    """

    try:

        if not os.path.exists(filename):

            save_json(default, filename)

            return default

        with open(filename, "r") as f:

            content = f.read().strip()

            if not content:
                return default

            return json.loads(content)

    except Exception as e:

        logger.exception(
            f"LOAD JSON ERROR: {e}"
        )

    return default

# =========================================================
# LOAD PERSISTENT STATE
# =========================================================

seen_alerts = set(
    load_json(SEEN_FILE, [])
)

candles = load_json(
    CANDLES_FILE,
    {}
)

logger.info(
    f"✅ Seen alerts loaded: "
    f"{len(seen_alerts)}"
)

# =========================================================
# TIME HELPERS
# =========================================================

def ist_now():

    """
    Current IST time
    """

    return datetime.now(IST)

# =========================================================
# MARKET HOURS CHECK
# =========================================================

def is_alert_hours():

    """
    Check if market hours are active
    """

    now = ist_now()

    logger.info(
        f"⏰ Market Time Check: "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # Weekend
    if now.weekday() >= 5:

        logger.info(
            "❌ Weekend detected"
        )

        return False

    t = (now.hour, now.minute)

    is_open = ALERT_START <= t < ALERT_END

    logger.info(
        f"📈 Market Active: {is_open}"
    )

    return is_open

# =========================================================
# TELEGRAM ALERTS
# =========================================================

def send_telegram(msg):

    """
    Send Telegram alert
    """

    try:

        logger.info(
            "📨 Sending Telegram..."
        )

        if not BOT_TOKEN or not CHAT_ID:
            return

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendMessage"
        )

        r = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": msg[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=20
        )

        logger.info(
            f"📨 Telegram Status="
            f"{r.status_code}"
        )

    except Exception as e:

        logger.exception(
            f"TELEGRAM ERROR: {e}"
        )

# =========================================================
# NSE SESSION
# =========================================================
#
# Maintains persistent NSE session
# Helps reduce:
# - 401
# - 403
# - cookie expiry issues
#
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

def init_nse():

    """
    Initialize NSE cookies/session
    """

    try:

        logger.info(
            "🌐 Initializing NSE session..."
        )

        r = session.get(
            "https://www.nseindia.com",
            timeout=10
        )

        logger.info(
            f"📡 NSE Init Status="
            f"{r.status_code}"
        )

    except Exception as e:

        logger.exception(
            f"NSE INIT ERROR: {e}"
        )

# Initialize session once
init_nse()

# =========================================================
# NSE GET HELPER
# =========================================================

def nse_get(url):

    """
    NSE API helper with retries
    """

    for attempt in range(3):

        try:

            logger.info(
                f"🌐 NSE API Call | "
                f"Attempt={attempt+1}"
            )

            r = session.get(url, timeout=15)

            logger.info(
                f"📡 NSE Status="
                f"{r.status_code}"
            )

            if r.status_code in [401, 403]:

                logger.warning(
                    "⚠️ NSE blocked request"
                )

                init_nse()

                continue

            r.raise_for_status()

            logger.info(
                "✅ NSE API Success"
            )

            return r.json()

        except Exception as e:

            logger.exception(
                f"NSE GET ERROR: {e}"
            )

            time.sleep(2)

    return None

# =========================================================
# FETCH STOCK DATA
# =========================================================

def fetch_stock(symbol):

    """
    Fetch:
    - live price
    - previous close
    - day high
    - traded volume
    """

    try:

        logger.info(
            f"🔍 Fetching: {symbol}"
        )

        url = (
            "https://www.nseindia.com/api/"
            f"quote-equity?symbol={symbol}"
        )

        data = nse_get(url)

        if not data:

            logger.warning(
                f"❌ Empty NSE data: "
                f"{symbol}"
            )

            return None

        p = data.get("priceInfo", {})

        if not p:

            logger.warning(
                f"❌ Missing priceInfo: "
                f"{symbol}"
            )

            return None

        last_price = safe_float(
            p.get("lastPrice")
        )

        prev_close = safe_float(
            p.get("previousClose")
        )

        if last_price <= 0:

            logger.warning(
                f"❌ Invalid price: "
                f"{symbol}"
            )

            return None

        if prev_close <= 0:

            logger.warning(
                f"❌ Invalid prev close: "
                f"{symbol}"
            )

            return None

        dp = data.get("securityWiseDP", {})

        intra = p.get("intraDayHighLow", {})

        volume = safe_int(
            dp.get(
                "quantityTraded",
                p.get("totalTradedVolume")
            )
        )

        logger.info(
            f"✅ {symbol} fetched | "
            f"Price={last_price} | "
            f"Volume={volume}"
        )

        return {

            "symbol": symbol,

            "price": last_price,

            "prev_close": prev_close,

            "day_high":
                safe_float(intra.get("max")),

            "volume": volume
        }

    except Exception as e:

        logger.exception(
            f"FETCH ERROR {symbol}: {e}"
        )

    return None

# =========================================================
# PARALLEL FETCH
# =========================================================

def fetch_all_data():

    """
    Fetch all stocks in parallel
    """

    result = {}

    logger.info(
        "📊 Starting parallel fetch..."
    )

    with ThreadPoolExecutor(max_workers=1) as executor:

        futures = {
            executor.submit(fetch_stock, s): s
            for s in WATCHLIST
        }

        for future in as_completed(futures):

            try:

                data = future.result()

                if data:
                    result[data["symbol"]] = data

            except Exception as e:

                logger.exception(
                    f"PARALLEL FETCH ERROR: {e}"
                )

    logger.info(
        f"✅ Valid Stocks Fetched: "
        f"{len(result)}"
    )

    return result

# =========================================================
# CANDLE HELPERS
# =========================================================

def get_candle_time(now, minutes):

    """
    Round timestamp to candle timeframe
    """

    rounded = (
        now.minute // minutes
    ) * minutes

    return now.replace(
        minute=rounded,
        second=0,
        microsecond=0
    )

# =========================================================
# UPDATE CANDLES
# =========================================================

def update_candles(symbol, price, volume):

    """
    Maintain:
    - 5m candles
    - 10m candles
    - 15m candles
    """

    logger.info(
        f"🕯️ Updating candles: "
        f"{symbol}"
    )

    now = ist_now()

    for tf in [5, 10, 15]:

        candle_time = get_candle_time(now, tf)

        key = candle_time.strftime(
            "%Y-%m-%d %H:%M"
        )

        tf_key = f"{tf}m"

        if symbol not in candles:
            candles[symbol] = {}

        if tf_key not in candles[symbol]:
            candles[symbol][tf_key] = {}

        data = candles[symbol][tf_key]

        if key not in data:

            logger.info(
                f"🆕 New {tf_key} candle: "
                f"{symbol}"
            )

            data[key] = {

                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0,
                "last_total_volume": volume
            }

        candle = data[key]

        candle["high"] = max(
            candle["high"],
            price
        )

        candle["low"] = min(
            candle["low"],
            price
        )

        candle["close"] = price

        delta = volume - candle.get(
            "last_total_volume",
            volume
        )

        if delta > 0:
            candle["volume"] += delta

        candle["last_total_volume"] = volume

# =========================================================
# PRICE MOVE ALERT
# =========================================================

def process_price_move_alert(symbol, stock):

    """
    Trigger:
    abs(price change %) >= 3%
    """

    try:

        logger.info(
            f"📈 Checking 3% move: "
            f"{symbol}"
        )

        price = stock["price"]

        prev_close = stock["prev_close"]

        pchange = (
            (price - prev_close)
            / prev_close
        ) * 100

        logger.info(
            f"📊 {symbol} move="
            f"{pchange:+.2f}%"
        )

        if abs(pchange) < PRICE_MOVE_THRESHOLD:
            return

        direction = "UP" if pchange > 0 else "DOWN"

        key = f"PRICE-{symbol}-{direction}"

        if key in seen_alerts:
            return

        seen_alerts.add(key)

        logger.info(
            f"🚀 3% ALERT: {symbol}"
        )

        send_telegram(
            f"📈 <b>3% PRICE MOVE</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Move:</b> {pchange:+.2f}%\n"
            f"<b>Price:</b> ₹{price:,.2f}"
        )

    except Exception as e:

        logger.exception(
            f"PRICE ALERT ERROR: {e}"
        )

# =========================================================
# MAIN LOOP
# =========================================================

logger.info(
    "🚀 MAIN LOOP STARTED"
)

last_news_scan = 0

while True:

    try:

        logger.info("=" * 80)

        logger.info(
            f"🔄 LOOP HEARTBEAT | "
            f"{ist_now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # =================================================
        # NEWS SCAN
        # =================================================

        if time.time() - last_news_scan > 900:

            logger.info(
                "📰 Running news scans..."
            )

            last_news_scan = time.time()

        # =================================================
        # MARKET HOURS CHECK
        # =================================================

        if is_alert_hours():

            logger.info(
                "📈 Market hours active"
            )

            # =============================================
            # FETCH ALL STOCKS
            # =============================================

            all_data = fetch_all_data()

            logger.info(
                f"📦 Stocks received: "
                f"{len(all_data)}"
            )

            # =============================================
            # PROCESS STOCKS
            # =============================================

            for symbol, stock in all_data.items():

                if not stock:
                    continue

                logger.info(
                    f"🔍 Processing: {symbol}"
                )

                update_candles(
                    symbol,
                    stock["price"],
                    stock["volume"]
                )

                process_price_move_alert(
                    symbol,
                    stock
                )

            # =============================================
            # SAVE STATE
            # =============================================

            save_json(
                candles,
                CANDLES_FILE
            )

            save_json(
                list(seen_alerts),
                SEEN_FILE
            )

            logger.info(
                "✅ Scan cycle completed"
            )

        else:

            logger.info(
                "⏰ Outside market hours"
            )

    except Exception as e:

        logger.exception(
            f"MAIN LOOP ERROR: {e}"
        )

    logger.info(
        f"😴 Sleeping "
        f"{CHECK_INTERVAL} sec..."
    )

    time.sleep(CHECK_INTERVAL)
