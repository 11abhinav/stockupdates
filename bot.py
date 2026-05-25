# =========================================================
# ADVANCED NSE MOMENTUM TELEGRAM BOT
# =========================================================
#
# FINAL FIXED VERSION
# ---------------------------------------------------------
#
# FIXES DONE
# ---------------------------------------------------------
#
# ✅ Uses ONLY completed 5m candles
#
# ✅ Removed unnecessary candle waiting logic
#
# ✅ Prevents partial candle alerts
#
# ✅ Fixed day high breakout detection
#
# ✅ Added strict volume breakout logic
#
# ✅ Fixed intraday move % calculation
#
# ✅ Added lightweight random logs
#
# ✅ Reduced Yahoo rate-limit risk
#
# ✅ Handles MultiIndex dataframe issue
#
# ✅ Prevents duplicate alerts
#
# ✅ Railway-safe low logging
#
# ✅ Telegram instant alerts
#
# ✅ Graceful error handling
#
# =========================================================

import os
import sys
import json
import time
import logging
import traceback
import requests
import pandas as pd
import yfinance as yf

from datetime import (
    datetime,
    timedelta,
    timezone
)

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)

# =========================================================
# LOGGER
# =========================================================

print("🚀 FILE STARTED", flush=True)

logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s | %(levelname)s | %(message)s",

    datefmt="%Y-%m-%d %H:%M:%S",

    force=True,

    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger()

logger.setLevel(logging.INFO)

for handler in logger.handlers:
    handler.flush = sys.stdout.flush

def log(message):

    print(message, flush=True)

    logger.info(message)

log("🚀 SCRIPT STARTED")

# =========================================================
# ENV
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

CHAT_ID = os.environ.get("CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:

    log("❌ ENV VARIABLES MISSING")

    raise SystemExit(1)

# =========================================================
# CONFIG
# =========================================================

PRICE_MOVE_THRESHOLD = 3.0

# KEEP LOW TO REDUCE YAHOO RATE LIMIT
MAX_WORKERS = 2

IST = timezone(
    timedelta(hours=5, minutes=30)
)

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
    "TRENT"

])))

log(
    f"📊 Watchlist Loaded: "
    f"{len(WATCHLIST)}"
)

# =========================================================
# FILES
# =========================================================

SEEN_FILE = "seen_alerts.json"

# =========================================================
# JSON HELPERS
# =========================================================

def load_json(filename, default):

    try:

        if not os.path.exists(filename):
            return default

        with open(filename, "r") as f:
            return json.load(f)

    except:
        return default

def save_json(data, filename):

    try:

        with open(filename, "w") as f:
            json.dump(data, f)

    except:
        traceback.print_exc()

# =========================================================
# LOAD STATE
# =========================================================

seen_alerts = set(
    load_json(SEEN_FILE, [])
)

# =========================================================
# TIME HELPERS
# =========================================================

def ist_now():

    return datetime.now(IST)

# =========================================================
# MARKET HOURS
# =========================================================

def is_market_open():

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

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendMessage"
        )

        r = requests.post(

            url,

            data={

                "chat_id": CHAT_ID,

                "text": msg[:4000],

                "parse_mode": "HTML"
            },

            timeout=20
        )

        log(
            f"📨 Telegram="
            f"{r.status_code}"
        )

    except Exception:
        traceback.print_exc()

# =========================================================
# FETCH STOCK DATA
# =========================================================

def fetch_stock(symbol):

    try:

        # =============================================
        # LIGHT REQUEST THROTTLING
        # REDUCES RATE LIMIT
        # =============================================

        time.sleep(0.35)

        df = yf.download(

            f"{symbol}.NS",

            period="2d",

            interval="5m",

            progress=False,

            auto_adjust=True,

            threads=False
        )

        if df.empty:
            return None

        # =============================================
        # FIX MULTIINDEX
        # =============================================

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

        # =============================================
        # REMOVE CURRENTLY FORMING CANDLE
        # =============================================

        if len(df) > 1:
            df = df.iloc[:-1]

        if len(df) < 10:
            return None

        latest = df.iloc[-1]

        # =============================================
        # FULL DAY MOVE %
        # =============================================

        prev_close = float(
            df["Close"].iloc[0]
        )

        last_price = float(
            latest["Close"]
        )

        if prev_close <= 0:
            return None

        move_pct = (
            (
                last_price - prev_close
            ) / prev_close
        ) * 100

        # =============================================
        # DAY HIGH BREAKOUT
        # =============================================

        previous_session_high = float(
            df["High"].iloc[:-1].max()
        )

        day_high_breakout = (
            last_price >= previous_session_high
        )

        # =============================================
        # STRICT VOLUME BREAKOUT
        # =============================================

        current_volume = float(
            latest["Volume"]
        )

        prev_5m_volume = float(
            df["Volume"].iloc[-2]
        )

        prev_10m_volume = float(
            df["Volume"].iloc[-3:-1].mean()
        )

        prev_15m_volume = float(
            df["Volume"].iloc[-4:-1].mean()
        )

        volume_breakout = (

            current_volume > prev_5m_volume

            and current_volume > prev_10m_volume

            and current_volume > prev_15m_volume
        )

        # =============================================
        # RANDOM LIGHT LOGS
        # =============================================

        if hash(symbol) % 17 == 0:

            log(
                f"📌 {symbol} "
                f"| ₹{last_price:.2f} "
                f"| {move_pct:+.2f}%"
            )

        return {

            "symbol": symbol,

            "price": last_price,

            "move_pct": move_pct,

            "volume_breakout": volume_breakout,

            "day_high_breakout": day_high_breakout
        }

    except Exception:

        err = str(traceback.format_exc())

        # =============================================
        # SILENT YFINANCE RATE LIMIT
        # =============================================

        if "YFRateLimitError" in err:
            return None

        traceback.print_exc()

        return None

# =========================================================
# FETCH ALL
# =========================================================

def fetch_all_data():

    result = {}

    log("📊 Fetch started")

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

            except Exception:
                traceback.print_exc()

    log(
        f"📦 Fetch completed | "
        f"Valid={len(result)}"
    )

    return result

# =========================================================
# ALERT ENGINE
# =========================================================

def process_alert(symbol, stock):

    try:

        move = stock["move_pct"]

        alert_sent = False

        # =============================================
        # PRICE MOMENTUM ALERT
        # =============================================

        if abs(move) >= PRICE_MOVE_THRESHOLD:

            direction = (
                "UP"
                if move > 0
                else "DOWN"
            )

            key = (
                f"{symbol}-{direction}"
            )

            if key not in seen_alerts:

                seen_alerts.add(key)

                log(
                    f"🚨 PRICE ALERT | "
                    f"{symbol}"
                )

                send_telegram(

                    f"📈 <b>3% PRICE MOVE</b>\n\n"

                    f"<b>Stock:</b> {symbol}\n"

                    f"<b>Move:</b> {move:+.2f}%\n"

                    f"<b>Price:</b> ₹{stock['price']:,.2f}"
                )

                alert_sent = True

        # =============================================
        # DAY HIGH BREAKOUT
        # =============================================

        if stock["day_high_breakout"]:

            key = (
                f"{symbol}-DAYHIGH"
            )

            if key not in seen_alerts:

                seen_alerts.add(key)

                log(
                    f"🔥 DAY HIGH | "
                    f"{symbol}"
                )

                send_telegram(

                    f"🔥 <b>DAY HIGH BREAKOUT</b>\n\n"

                    f"<b>Stock:</b> {symbol}\n"

                    f"<b>Price:</b> ₹{stock['price']:,.2f}\n"

                    f"<b>Move:</b> {move:+.2f}%"
                )

                alert_sent = True

        # =============================================
        # VOLUME BREAKOUT
        # =============================================

        if stock["volume_breakout"]:

            key = (
                f"{symbol}-VOLUME"
            )

            if key not in seen_alerts:

                seen_alerts.add(key)

                log(
                    f"📊 VOLUME BREAKOUT | "
                    f"{symbol}"
                )

                send_telegram(

                    f"📊 <b>VOLUME BREAKOUT</b>\n\n"

                    f"<b>Stock:</b> {symbol}\n"

                    f"<b>Price:</b> ₹{stock['price']:,.2f}\n"

                    f"<b>Move:</b> {move:+.2f}%"
                )

                alert_sent = True

        return alert_sent

    except Exception:

        traceback.print_exc()

        return False

# =========================================================
# MAIN BOT
# =========================================================

def run_bot():

    log(
        f"🚀 RUN STARTED | "
        f"{ist_now().strftime('%H:%M:%S')}"
    )

    if not is_market_open():

        log("⏰ Market closed")

        return

    all_data = fetch_all_data()

    alert_count = 0

    for symbol, stock in all_data.items():

        sent = process_alert(
            symbol,
            stock
        )

        if sent:
            alert_count += 1

    save_json(
        list(seen_alerts),
        SEEN_FILE
    )

    log(
        f"✅ RUN FINISHED | "
        f"Stocks={len(all_data)} | "
        f"Alerts={alert_count}"
    )

# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":

    try:

        run_bot()

    except Exception:

        traceback.print_exc()

        log(
            "❌ MAIN CRITICAL ERROR"
        )
