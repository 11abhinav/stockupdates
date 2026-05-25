# =========================================================
# FINAL PRODUCTION MOMENTUM + NSE NEWS BOT
# FULL DEBUG VERSION WITH DETAILED LOGS
# =========================================================

import os
import json
import time
import threading
import logging

import pandas as pd
import yfinance as yf
import requests
import feedparser

from flask import Flask
from zoneinfo import ZoneInfo
from datetime import datetime
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

    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)

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

        port=int(
            os.environ.get("PORT", 5000)
        )
    ),

    daemon=True

).start()

# =========================================================
# ENV
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

CHAT_ID = os.environ.get("CHAT_ID")

if not BOT_TOKEN:

    logger.error(
        "❌ BOT_TOKEN missing"
    )

if not CHAT_ID:

    logger.error(
        "❌ CHAT_ID missing"
    )

# =========================================================
# CONFIG
# =========================================================

CHECK_INTERVAL = 300

# LOWERED FOR MORE ALERTS
PRICE_MOVE_THRESHOLD = 0.8

# NSE NEWS EVERY 2 HOURS
NEWS_SCAN_INTERVAL = 7200

# KEEP LOW TO AVOID RATE LIMIT
MAX_WORKERS = 1

IST = ZoneInfo("Asia/Kolkata")

ALERT_START = (9, 15)

ALERT_END = (15, 30)

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

logger.info(
    f"📊 Total Watchlist Stocks: "
    f"{len(WATCHLIST)}"
)

# =========================================================
# FILES
# =========================================================

SEEN_FILE = "seen_alerts.json"

# =========================================================
# JSON HELPERS
# =========================================================

def save_json(data, filename):

    try:

        tmp = filename + ".tmp"

        with open(tmp, "w") as f:

            json.dump(
                data,
                f,
                ensure_ascii=False
            )

        os.replace(tmp, filename)

        logger.info(
            f"💾 Saved JSON: {filename}"
        )

    except Exception:

        logger.exception(
            "SAVE JSON ERROR"
        )

def load_json(filename, default):

    try:

        if not os.path.exists(filename):

            save_json(default, filename)

            return default

        with open(filename, "r") as f:

            content = f.read().strip()

            if not content:

                return default

            return json.loads(content)

    except Exception:

        logger.exception(
            "LOAD JSON ERROR"
        )

    return default

# =========================================================
# STATE
# =========================================================

seen_alerts = set(

    load_json(SEEN_FILE, [])
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
        f"⏰ IST Time Check: "
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

        if not BOT_TOKEN or not CHAT_ID:

            logger.error(
                "❌ BOT_TOKEN / CHAT_ID missing"
            )

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

                "disable_web_page_preview": True
            },

            timeout=20
        )

        logger.info(
            f"📨 Telegram Status="
            f"{r.status_code}"
        )

    except Exception:

        logger.exception(
            "TELEGRAM ERROR"
        )

# =========================================================
# FETCH STOCK
# =========================================================

def fetch_stock(symbol):

    try:

        logger.info(
            f"🔍 Fetching: {symbol}"
        )

        time.sleep(1)

        df = yf.download(

            f"{symbol}.NS",

            period="1d",

            interval="5m",

            progress=False,

            auto_adjust=True,

            threads=False
        )

        if df.empty:

            logger.warning(
                f"❌ No data: {symbol}"
            )

            return None

        # =================================================
        # FIX MULTI INDEX
        # =================================================

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

        required_cols = [

            "Open",
            "High",
            "Low",
            "Close",
            "Volume"
        ]

        for col_name in required_cols:

            if col_name not in df.columns:

                logger.warning(
                    f"❌ Missing {col_name}: "
                    f"{symbol}"
                )

                return None

            if isinstance(

                df[col_name],

                pd.DataFrame
            ):

                df[col_name] = (
                    df[col_name]
                    .iloc[:, 0]
                )

            df[col_name] = pd.Series(
                df[col_name]
            ).astype(float)

        df.dropna(inplace=True)

        if len(df) < 5:

            logger.warning(
                f"❌ Insufficient candles: "
                f"{symbol}"
            )

            return None

        latest = df.iloc[-1]

        prev_close = float(
            df["Close"].iloc[-2]
        )

        last_price = float(
            latest["Close"]
        )

        volume = int(
            latest["Volume"]
        )

        move = (

            (

                last_price - prev_close

            ) / prev_close

        ) * 100

        logger.info(
            f"✅ {symbol} fetched | "
            f"Price={round(last_price,2)} | "
            f"Move={move:+.2f}% | "
            f"Volume={volume}"
        )

        return {

            "symbol": symbol,

            "price": last_price,

            "price_pct": move,

            "volume": volume,

            "high": float(
                latest["High"]
            ),

            "low": float(
                latest["Low"]
            ),

            "open": float(
                latest["Open"]
            )
        }

    except Exception:

        logger.exception(
            f"{symbol} FETCH ERROR"
        )

    return None

# =========================================================
# FETCH ALL
# =========================================================

def fetch_all_data():

    result = {}

    logger.info(
        "📊 Fetching all stock data..."
    )

    with ThreadPoolExecutor(

        max_workers=MAX_WORKERS

    ) as executor:

        futures = {

            executor.submit(
                fetch_stock,
                s
            ): s

            for s in WATCHLIST
        }

        for future in as_completed(futures):

            try:

                data = future.result()

                if data:

                    result[data["symbol"]] = data

            except Exception:

                logger.exception(
                    "PARALLEL FETCH ERROR"
                )

    logger.info(
        f"✅ Total Stocks Fetched: "
        f"{len(result)}"
    )

    logger.info(
        f"📦 Valid Stocks: "
        f"{list(result.keys())[:10]}"
    )

    return result

# =========================================================
# PROCESS STOCK
# =========================================================

def process_stock(stock):

    try:

        symbol = stock["symbol"]

        move = stock["price_pct"]

        logger.info(
            f"📊 {symbol} | "
            f"Price={round(stock['price'],2)} | "
            f"Move={round(move,2)}% | "
            f"Volume={stock['volume']}"
        )

        # =================================================
        # PRICE FILTER
        # =================================================

        if move < PRICE_MOVE_THRESHOLD:

            logger.info(
                f"❌ Rejected Move: "
                f"{symbol} | "
                f"Move={move:+.2f}%"
            )

            return

        # =================================================
        # CANDLE ANALYSIS
        # =================================================

        candle_range = (

            stock["high"]

            - stock["low"]
        )

        candle_body = abs(

            stock["price"]

            - stock["open"]
        )

        if candle_range <= 0:

            logger.info(
                f"❌ Invalid candle: "
                f"{symbol}"
            )

            return

        body_ratio = (

            candle_body

            / candle_range
        )

        logger.info(
            f"🕯️ {symbol} | "
            f"BodyRatio={round(body_ratio,2)}"
        )

        if body_ratio < 0.4:

            logger.info(
                f"❌ Weak candle rejected: "
                f"{symbol}"
            )

            return

        # =================================================
        # DUPLICATE CHECK
        # =================================================

        key = (
            f"{symbol}-"
            f"{ist_now().strftime('%Y-%m-%d-%H-%M')}"
        )

        if key in seen_alerts:

            logger.info(
                f"⚠️ Duplicate skipped: "
                f"{symbol}"
            )

            return

        seen_alerts.add(key)

        logger.info(
            f"🚀 ALERT CONDITIONS PASSED: "
            f"{symbol}"
        )

        # =================================================
        # TELEGRAM MESSAGE
        # =================================================

        msg = f"""
🚀 MOMENTUM BREAKOUT

Stock:
{symbol}

Price:
₹{round(stock['price'], 2)}

Move:
{round(move, 2)}%

Volume:
{stock['volume']}

Body Ratio:
{round(body_ratio, 2)}

Time:
{ist_now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        send_telegram(msg)

        logger.info(
            f"✅ ALERT SENT: {symbol}"
        )

    except Exception:

        logger.exception(
            "PROCESS STOCK ERROR"
        )

# =========================================================
# FETCH NEWS
# =========================================================

def fetch_news():

    try:

        logger.info(
            "📰 Fetching NSE/Market news..."
        )

        feeds = [

            "https://www.nseindia.com/rss/corporate-announcements.xml",

            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",

            "https://www.moneycontrol.com/rss/business.xml"
        ]

        news_items = []

        now = ist_now()

        for feed_url in feeds:

            try:

                logger.info(
                    f"🌐 Parsing Feed: "
                    f"{feed_url}"
                )

                feed = feedparser.parse(
                    feed_url
                )

                logger.info(
                    f"📰 Total headlines: "
                    f"{len(feed.entries)}"
                )

                for entry in feed.entries[:10]:

                    title = entry.get(
                        "title",
                        ""
                    )

                    logger.info(
                        f"📰 Checking headline: "
                        f"{title[:100]}"
                    )

                    link = entry.get(
                        "link",
                        ""
                    )

                    published = entry.get(
                        "published",
                        ""
                    )

                    try:

                        published_dt = (
                            parsedate_to_datetime(
                                published
                            )
                        )

                        age_mins = (

                            now

                            - published_dt.astimezone(IST)

                        ).total_seconds() / 60

                        if age_mins > 240:

                            continue

                    except:

                        pass

                    for symbol in WATCHLIST:

                        if symbol in title.upper():

                            logger.info(
                                f"📰 MATCH FOUND: "
                                f"{symbol}"
                            )

                            news_items.append({

                                "symbol": symbol,

                                "title": title,

                                "link": link
                            })

            except Exception:

                logger.exception(
                    "RSS PARSE ERROR"
                )

        logger.info(
            f"📰 News found: "
            f"{len(news_items)}"
        )

        return news_items

    except Exception:

        logger.exception(
            "NEWS FETCH ERROR"
        )

    return []

# =========================================================
# STARTUP MESSAGE
# =========================================================

send_telegram(

    f"✅ MOMENTUM BOT STARTED\n\n"

    f"Stocks: {len(WATCHLIST)}\n"

    f"Time: "
    f"{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}"
)

# =========================================================
# MAIN LOOP
# =========================================================

logger.info("🚀 MAIN LOOP STARTED")

last_news_scan = 0

while True:

    try:

        logger.info("=" * 80)

        logger.info(
            f"🔄 NEW SCAN CYCLE | "
            f"IST={ist_now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # =================================================
        # NEWS SCAN
        # =================================================

        if time.time() - last_news_scan > NEWS_SCAN_INTERVAL:

            logger.info(
                "📰 Running NSE news scan..."
            )

            news_items = fetch_news()

            for news in news_items:

                key = (
                    f"NEWS-"
                    f"{news['symbol']}-"
                    f"{news['title']}"
                )

                if key in seen_alerts:

                    continue

                seen_alerts.add(key)

                msg = f"""
📰 NSE / MARKET NEWS

Stock:
{news['symbol']}

Headline:
{news['title']}

Link:
{news['link']}
"""

                send_telegram(msg)

                logger.info(
                    f"📰 NEWS ALERT: "
                    f"{news['symbol']}"
                )

            last_news_scan = time.time()

        # =================================================
        # MARKET SCAN
        # =================================================

        if is_alert_hours():

            all_data = fetch_all_data()

            logger.info(
                f"📈 Processing "
                f"{len(all_data)} stocks..."
            )

            for symbol, stock in all_data.items():

                logger.info(
                    f"🔍 Processing: {symbol}"
                )

                process_stock(stock)

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

    except Exception:

        logger.exception(
            "❌ MAIN LOOP ERROR"
        )

    logger.info(
        f"😴 Sleeping "
        f"{CHECK_INTERVAL} sec..."
    )

    time.sleep(CHECK_INTERVAL)
