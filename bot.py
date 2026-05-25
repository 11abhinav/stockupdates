# =========================================================
# ADVANCED NSE MOMENTUM + BREAKOUT TELEGRAM BOT
# LOW LOG VERSION (RAILWAY SAFE)
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

from datetime import datetime, timedelta, timezone
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

log("=" * 80)
log("🚀 SCRIPT STARTED")
log("=" * 80)

# =========================================================
# ENV
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

CHAT_ID = os.environ.get("CHAT_ID")

log(
    f"BOT_TOKEN EXISTS="
    f"{bool(BOT_TOKEN)}"
)

log(
    f"CHAT_ID EXISTS="
    f"{bool(CHAT_ID)}"
)

# =========================================================
# CONFIG
# =========================================================

PRICE_MOVE_THRESHOLD = 3.0

MAX_WORKERS = 1

IST = timezone(
    timedelta(hours=5, minutes=30)
)

ALERT_START = (8, 45)

ALERT_END = (16, 0)

# =========================================================
# WATCHLIST
# =========================================================

WATCHLIST = sorted(list(set([

    "ADANIENT",
    "ADANIGREEN",
    "ADANIPORTS",
    "BEL",
    "CGPOWER",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "IRB",
    "JIOFIN",
    "LT",
    "MARUTI",
    "ONGC",
    "PFC",
    "RELIANCE",
    "RVNL",
    "SBIN",
    "SUZLON",
    "TATATECH",
    "TITAN",
    "TRENT",
    "VBL"

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
# LOAD STATE
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

seen_alerts = set(
    load_json(SEEN_FILE, [])
)

# =========================================================
# TIME
# =========================================================

def ist_now():

    return datetime.now(IST)

# =========================================================
# MARKET HOURS
# =========================================================

def is_market_open():

    now = ist_now()

    if now.weekday() >= 5:

        log("❌ Weekend detected")

        return False

    t = (now.hour, now.minute)

    is_open = ALERT_START <= t < ALERT_END

    log(
        f"📈 Market Active: "
        f"{is_open}"
    )

    return is_open

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
            f"📨 Telegram Status="
            f"{r.status_code}"
        )

    except Exception:

        traceback.print_exc()

# =========================================================
# FETCH STOCK
# =========================================================

def fetch_stock(symbol):

    try:

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

        move_pct = (
            (
                last_price - prev_close
            ) / prev_close
        ) * 100

        return {

            "symbol": symbol,

            "price": last_price,

            "move_pct": move_pct
        }

    except Exception:

        traceback.print_exc()

        return None

# =========================================================
# FETCH ALL
# =========================================================

def fetch_all_data():

    result = {}

    log("📊 STARTING FETCH CYCLE")

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
        f"✅ Valid Stocks Fetched: "
        f"{len(result)}"
    )

    return result

# =========================================================
# PROCESS ALERT
# =========================================================

def process_alert(symbol, stock):

    try:

        move = stock["move_pct"]

        if abs(move) < PRICE_MOVE_THRESHOLD:

            return

        direction = (
            "UP"
            if move > 0
            else "DOWN"
        )

        key = (
            f"{symbol}-{direction}"
        )

        if key in seen_alerts:

            return

        seen_alerts.add(key)

        log(
            f"🚀 ALERT: "
            f"{symbol} | "
            f"{move:+.2f}%"
        )

        send_telegram(

            f"📈 <b>3% PRICE MOVE</b>\n\n"

            f"<b>Stock:</b> {symbol}\n"

            f"<b>Move:</b> {move:+.2f}%\n"

            f"<b>Price:</b> ₹{stock['price']:,.2f}"
        )

    except Exception:

        traceback.print_exc()

# =========================================================
# MAIN BOT
# =========================================================

def run_bot():

    log("=" * 80)

    log(
        f"🔄 CRON RUN STARTED | "
        f"{ist_now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    if not is_market_open():

        log("⏰ Market closed")

        return

    all_data = fetch_all_data()

    for symbol, stock in all_data.items():

        process_alert(
            symbol,
            stock
        )

    save_json(
        list(seen_alerts),
        SEEN_FILE
    )

    log("✅ Scan cycle completed")

# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":

    try:

        if not BOT_TOKEN or not CHAT_ID:

            log(
                "❌ ENV VARIABLES MISSING"
            )

            raise SystemExit(1)

        run_bot()

    except Exception:

        traceback.print_exc()

        log(
            "❌ MAIN CRITICAL ERROR"
        )
