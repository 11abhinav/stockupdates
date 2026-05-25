# =========================================================
# ADVANCED NSE MOMENTUM + BREAKOUT TELEGRAM BOT
# =========================================================
#
# FINAL HYBRID VERSION
#
# PRICE DATA:
#   ✅ yfinance (NO 403)
#
# NSE NEWS:
#   ✅ NSE RSS FEEDS
#   ✅ Runs hourly
#
# FEATURES
# ---------------------------------------------------------
# ✅ 3% Price Move Alerts
# ✅ 5m / 10m / 15m Candle Tracking
# ✅ Volume Breakout Detection
# ✅ Multi Candle Breakout
# ✅ Day High Breakout
# ✅ NSE News Fetch
# ✅ Google News Fetch
# ✅ Railway Compatible
# ✅ Ultra Logging
# ✅ Continuous Running
# ✅ Persistent State
# ✅ Duplicate Alert Prevention
# ✅ Healthcheck Endpoint
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
import pandas as pd
import yfinance as yf

from flask import Flask
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)

# =========================================================
# LOGGER
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
# FLASK HEALTHCHECK
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():

    logger.info("🌐 Healthcheck hit")

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

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN missing")

if not CHAT_ID:
    logger.error("❌ CHAT_ID missing")

# =========================================================
# CONFIG
# =========================================================

CHECK_INTERVAL = 60

PRICE_MOVE_THRESHOLD = 3.0

NEWS_SCAN_INTERVAL = 3600

MAX_WORKERS = 1

IST = timezone(
    timedelta(hours=5, minutes=30)
)

ALERT_START = (8, 45)
ALERT_END = (16, 0)

# =========================================================
# WATCHLIST (UNCHANGED)
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
# FILES
# =========================================================

SEEN_FILE = "seen_alerts.json"

CANDLES_FILE = "candles.json"

# =========================================================
# HELPERS
# =========================================================

def safe_float(v):

    try:
        return float(v)
    except:
        return 0.0

def safe_int(v):

    try:
        return int(float(v))
    except:
        return 0

# =========================================================
# JSON HELPERS
# =========================================================

def save_json(data, filename):

    try:

        with open(filename, "w") as f:

            json.dump(data, f)

        logger.info(
            f"💾 Saved JSON: {filename}"
        )

    except Exception as e:

        logger.exception(
            f"SAVE JSON ERROR: {e}"
        )

def load_json(filename, default):

    try:

        if not os.path.exists(filename):

            return default

        with open(filename, "r") as f:

            return json.load(f)

    except:

        return default

# =========================================================
# LOAD STATE
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
# TIME
# =========================================================

def ist_now():

    return datetime.now(IST)

# =========================================================
# MARKET HOURS
# =========================================================

def is_alert_hours():

    now = ist_now()

    logger.info(
        f"⏰ Market Time Check: "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    if now.weekday() >= 5:

        logger.info(
            "❌ Weekend detected"
        )

        return False

    t = (now.hour, now.minute)

    is_open = ALERT_START <= t < ALERT_END

    logger.info(
        f"📈 Market Active: "
        f"{is_open}"
    )

    return is_open

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(msg):

    try:

        logger.info(
            "📨 Sending Telegram..."
        )

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
# FETCH STOCK DATA USING YFINANCE
# =========================================================

def fetch_stock(symbol):

    try:

        logger.info(
            f"🔍 Fetching: {symbol}"
        )

        df = yf.download(

            f"{symbol}.NS",

            period="2d",

            interval="5m",

            progress=False,

            auto_adjust=True,

            threads=False
        )

        logger.info(
            f"📦 Rows fetched: "
            f"{len(df)} | {symbol}"
        )

        if df.empty:

            logger.warning(
                f"❌ Empty yf data: "
                f"{symbol}"
            )

            return None

        # FIX MULTIINDEX
        if isinstance(
            df.columns,
            pd.MultiIndex
        ):

            df.columns = (
                df.columns
                .get_level_values(0)
            )

        df = df.loc[
            :,
            ~df.columns.duplicated()
        ]

        latest = df.iloc[-1]

        prev_close = float(
            df["Close"].iloc[0]
        )

        last_price = float(
            latest["Close"]
        )

        volume = int(
            latest["Volume"]
        )

        day_high = float(
            df["High"].max()
        )

        logger.info(
            f"✅ {symbol} fetched | "
            f"Price={last_price} | "
            f"Volume={volume}"
        )

        logger.info(
            f"📈 Price Move="
            f"{((last_price-prev_close)/prev_close)*100:.2f}%"
        )

        return {

            "symbol": symbol,

            "price": last_price,

            "prev_close": prev_close,

            "day_high": day_high,

            "volume": volume
        }

    except Exception as e:

        logger.exception(
            f"FETCH ERROR {symbol}: {e}"
        )

    return None

# =========================================================
# FETCH ALL DATA
# =========================================================

def fetch_all_data():

    result = {}

    logger.info(
        "📊 Starting parallel fetch..."
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

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
# GET PREVIOUS CANDLE
# =========================================================

def get_previous_candle(symbol, tf):

    tf_key = f"{tf}m"

    try:

        data = candles[symbol][tf_key]

        keys = sorted(data.keys())

        if len(keys) < 2:
            return None

        return data[keys[-2]]

    except:
        return None

# =========================================================
# PRICE MOVE ALERT
# =========================================================

def process_price_move_alert(symbol, stock):

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

        direction = (
            "UP"
            if pchange > 0
            else "DOWN"
        )

        key = (
            f"PRICE-{symbol}-{direction}"
        )

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
# VOLUME BREAKOUT
# =========================================================

def process_volume_breakout(symbol):

    try:

        logger.info(
            f"📊 Checking volume breakout: "
            f"{symbol}"
        )

        prev5 = get_previous_candle(symbol, 5)
        prev10 = get_previous_candle(symbol, 10)
        prev15 = get_previous_candle(symbol, 15)

        if not prev5 or not prev10 or not prev15:
            return

        curr5 = candles[symbol]["5m"]
        curr10 = candles[symbol]["10m"]
        curr15 = candles[symbol]["15m"]

        c5 = curr5[sorted(curr5.keys())[-1]]
        c10 = curr10[sorted(curr10.keys())[-1]]
        c15 = curr15[sorted(curr15.keys())[-1]]

        if (
            c5["volume"] > prev5["volume"]
            and
            c10["volume"] > prev10["volume"]
            and
            c15["volume"] > prev15["volume"]
        ):

            key = f"VOL-{symbol}"

            if key in seen_alerts:
                return

            seen_alerts.add(key)

            logger.info(
                f"🚀 VOLUME BREAKOUT: "
                f"{symbol}"
            )

            send_telegram(
                f"📊 <b>VOLUME BREAKOUT</b>\n\n"
                f"<b>Stock:</b> {symbol}"
            )

    except Exception as e:

        logger.exception(
            f"VOLUME BREAKOUT ERROR: {e}"
        )

# =========================================================
# MULTI CANDLE BREAKOUT
# =========================================================

def process_breakout_alert(symbol, stock):

    try:

        logger.info(
            f"🚀 Checking breakout: "
            f"{symbol}"
        )

        prev5 = get_previous_candle(symbol, 5)
        prev10 = get_previous_candle(symbol, 10)
        prev15 = get_previous_candle(symbol, 15)

        if not prev5 or not prev10 or not prev15:
            return

        price = stock["price"]

        if (
            price > prev5["high"]
            and
            price > prev10["high"]
            and
            price > prev15["high"]
        ):

            key = f"BO-{symbol}"

            if key in seen_alerts:
                return

            seen_alerts.add(key)

            logger.info(
                f"🔥 BREAKOUT DETECTED: "
                f"{symbol}"
            )

            send_telegram(
                f"🚀 <b>MULTI TF BREAKOUT</b>\n\n"
                f"<b>Stock:</b> {symbol}\n"
                f"<b>Price:</b> ₹{price}"
            )

    except Exception as e:

        logger.exception(
            f"BREAKOUT ERROR: {e}"
        )

# =========================================================
# DAY HIGH BREAKOUT
# =========================================================

def process_day_high_breakout(symbol, stock):

    try:

        price = stock["price"]
        day_high = stock["day_high"]

        if price < day_high:
            return

        key = f"DAYHIGH-{symbol}"

        if key in seen_alerts:
            return

        seen_alerts.add(key)

        logger.info(
            f"🚀 DAY HIGH BREAKOUT: "
            f"{symbol}"
        )

        send_telegram(
            f"📈 <b>DAY HIGH BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Price:</b> ₹{price}"
        )

    except Exception as e:

        logger.exception(
            f"DAY HIGH ERROR: {e}"
        )

# =========================================================
# NSE + GOOGLE NEWS
# =========================================================

def fetch_news():

    try:

        logger.info(
            "📰 Running news scan..."
        )

        feeds = [

            "https://www.nseindia.com/rss/corporate-announcements.xml",

            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",

            "https://news.google.com/rss/search?q=stock+market+india"
        ]

        now = ist_now()

        for feed_url in feeds:

            try:

                logger.info(
                    f"🌐 Parsing feed: "
                    f"{feed_url}"
                )

                feed = feedparser.parse(feed_url)

                for entry in feed.entries[:20]:

                    title = entry.get(
                        "title",
                        ""
                    )

                    link = entry.get(
                        "link",
                        ""
                    )

                    logger.info(
                        f"📰 Headline: "
                        f"{title[:80]}"
                    )

                    for symbol in WATCHLIST:

                        if symbol in title.upper():

                            key = (
                                f"NEWS-{symbol}-{title}"
                            )

                            if key in seen_alerts:
                                continue

                            seen_alerts.add(key)

                            logger.info(
                                f"📰 NEWS MATCH: "
                                f"{symbol}"
                            )

                            send_telegram(
                                f"📰 <b>MARKET NEWS</b>\n\n"
                                f"<b>Stock:</b> {symbol}\n\n"
                                f"{title}\n\n"
                                f"{link}"
                            )

            except Exception as e:

                logger.exception(
                    f"RSS ERROR: {e}"
                )

    except Exception as e:

        logger.exception(
            f"NEWS ERROR: {e}"
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
        # HOURLY NEWS SCAN
        # =================================================

        if (
            time.time() - last_news_scan
            > NEWS_SCAN_INTERVAL
        ):

            fetch_news()

            last_news_scan = time.time()

        # =================================================
        # MARKET HOURS CHECK
        # =================================================

        if is_alert_hours():

            logger.info(
                "📈 Market hours active"
            )

            all_data = fetch_all_data()

            logger.info(
                f"📦 Stocks received: "
                f"{len(all_data)}"
            )

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

                process_volume_breakout(
                    symbol
                )

                process_breakout_alert(
                    symbol,
                    stock
                )

                process_day_high_breakout(
                    symbol,
                    stock
                )

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
