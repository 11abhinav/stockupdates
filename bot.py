# =========================================================
# ADVANCED NSE MOMENTUM + VOLUME BREAKOUT TELEGRAM BOT
# FINAL FULL STABLE VERSION WITH LOGGING
# =========================================================

import os
import json
import time
import threading
import requests
import feedparser
import logging

from flask import Flask
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================================================
# LOGGER
# =========================================================

logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s | %(levelname)s | %(message)s",

    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)

logger.info("🚀 SCRIPT STARTED")

# =========================================================
# FLASK SERVER
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
    logger.error("BOT_TOKEN missing")

if not CHAT_ID:
    logger.error("CHAT_ID missing")

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

def save_json(data, filename):

    try:

        tmp = filename + ".tmp"

        with open(tmp, "w") as f:
            json.dump(data, f)

        os.replace(tmp, filename)

    except Exception:

        logger.exception("SAVE JSON ERROR")

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

        logger.exception("LOAD JSON ERROR")

    return default

# =========================================================
# LOAD STATE
# =========================================================

seen_alerts = set(load_json(SEEN_FILE, []))

candles = load_json(CANDLES_FILE, {})

logger.info(
    f"✅ Seen alerts loaded: "
    f"{len(seen_alerts)}"
)

# =========================================================
# TIME HELPERS
# =========================================================

def ist_now():
    return datetime.now(IST)

def is_alert_hours():

    now = ist_now()

    logger.info(
        f"⏰ IST Time Check: "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    if now.weekday() >= 5:
        return False

    t = (now.hour, now.minute)

    status = ALERT_START <= t < ALERT_END

    logger.info(
        f"📈 Alert Hours Active: "
        f"{status}"
    )

    return status

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(msg):

    try:

        if not BOT_TOKEN or not CHAT_ID:
            return

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

        logger.info("📨 Telegram message sent")

    except Exception:

        logger.exception("TELEGRAM ERROR")

# =========================================================
# NSE SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

def init_nse():

    try:

        logger.info("🌐 Initializing NSE session...")

        session.get(
            "https://www.nseindia.com",
            timeout=10
        )

        logger.info("✅ NSE session initialized")

    except:
        pass

init_nse()

def nse_get(url):

    for _ in range(3):

        try:

            logger.info("🌐 NSE API Call")

            r = session.get(url, timeout=15)

            logger.info(
                f"📡 NSE Status={r.status_code}"
            )

            if r.status_code in [401, 403]:

                init_nse()
                continue

            r.raise_for_status()

            logger.info("✅ NSE API Success")

            return r.json()

        except:

            time.sleep(2)

    return None

# =========================================================
# FETCH STOCK DATA
# =========================================================

def fetch_stock(symbol):

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
            return None

        p = data.get("priceInfo", {})

        if not p:
            return None

        last_price = safe_float(
            p.get("lastPrice")
        )

        prev_close = safe_float(
            p.get("previousClose")
        )

        if last_price <= 0:
            return None

        if prev_close <= 0:
            return None

        dp = data.get("securityWiseDP", {})
        intra = p.get("intraDayHighLow", {})

        logger.info(
            f"✅ {symbol} fetched successfully"
        )

        return {

            "symbol": symbol,

            "price": last_price,

            "prev_close": prev_close,

            "day_high":
                safe_float(intra.get("max")),

            "volume":
                safe_int(
                    dp.get(
                        "quantityTraded",
                        p.get("totalTradedVolume")
                    )
                )
        }

    except Exception as e:

        send_telegram(
            f"❌ FETCH ERROR\n\n"
            f"{symbol}\n\n{str(e)}"
        )

    return None

# =========================================================
# PARALLEL FETCH
# =========================================================

def fetch_all_data():

    logger.info("📊 Fetching all stock data...")

    result = {}

    with ThreadPoolExecutor(max_workers=10) as executor:

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

                send_telegram(
                    f"❌ PARALLEL FETCH ERROR\n\n"
                    f"{str(e)}"
                )

    logger.info(
        f"✅ Total Stocks Fetched: "
        f"{len(result)}"
    )

    return result

# =========================================================
# CANDLE TIME
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

        keys = sorted(data.keys())

        if len(keys) > 50:

            for k in keys[:-50]:
                del data[k]

# =========================================================
# STARTUP MESSAGE
# =========================================================

send_telegram(
    f"✅ <b>NSE MOMENTUM BOT STARTED</b>\n\n"
    f"<b>Stocks:</b> {len(WATCHLIST)}\n"
    f"<b>Time:</b> "
    f"{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}"
)

# =========================================================
# MAIN LOOP
# =========================================================

logger.info("🚀 MAIN LOOP STARTED")

while True:

    try:

        logger.info("=" * 80)

        logger.info(
            f"🔄 New Scan Cycle | "
            f"IST={ist_now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if is_alert_hours():

            logger.info(
                "📊 Running market scan..."
            )

            all_data = fetch_all_data()

            for symbol, stock in all_data.items():

                logger.info(
                    f"🔍 Processing: {symbol}"
                )

                if not stock:
                    continue

                update_candles(
                    symbol,
                    stock["price"],
                    stock["volume"]
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
            f"😴 Sleeping "
            f"{CHECK_INTERVAL} sec..."
        )

    except Exception as e:

        send_telegram(
            f"❌ MAIN LOOP ERROR\n\n"
            f"{str(e)}"
        )

        logger.exception("MAIN LOOP ERROR")

    time.sleep(CHECK_INTERVAL)
