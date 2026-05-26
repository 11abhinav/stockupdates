
# =========================================================
# ADVANCED NSE MOMENTUM TELEGRAM BOT
# =========================================================
#
# FINAL CONSOLIDATED BREAKOUT VERSION
# ---------------------------------------------------------
#
# FEATURES
# ---------------------------------------------------------
#
# ✅ Uses ONLY completed 5m candles
#
# ✅ Removes currently forming candle automatically
#
# ✅ Consolidated category-wise Telegram alerts
#
# ✅ PRICE MOVE alerts grouped together
#
# ✅ DAY HIGH alerts grouped together
#
# ✅ MULTI TIMEFRAME BREAKOUT alerts grouped together
#
# ✅ Detects:
#
#    • 5m breakout
#    • 10m breakout
#    • 15m breakout
#    • 30m breakout
#
# ✅ Reduced Telegram spam
#
# ✅ Reduced Yahoo Finance rate limit issues
#
# ✅ Lightweight throttling added
#
# ✅ Handles yfinance MultiIndex issue
#
# ✅ Railway-safe execution
#
# ✅ Random lightweight logs
#
# ✅ Graceful failure handling
#
# IMPORTANT
# ---------------------------------------------------------
#
# Bot ALWAYS uses completed candles.
#
# Example:
#
# Current Time = 10:03
#
# Ignored Candle:
#    10:00 → 10:05
#
# Used Candle:
#    09:55 → 10:00
#
# This prevents fake intraday alerts.
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

        # =============================================
        # KEEP RECENT DATA ONLY
        # =============================================

        df = df.tail(50)

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
        # DAY HIGH DETECTION
        # =============================================

        day_high = float(
            df["High"].max()
        )

        at_day_high = (
            last_price >= day_high * 0.999
        )

        # =============================================
        # MULTI TIMEFRAME BREAKOUTS
        # =============================================

        breakout_5m = (
            last_price > float(
                df["High"].iloc[-2]
            )
        )

        breakout_10m = (
            last_price > float(
                df["High"].iloc[-3:-1].max()
            )
        )

        breakout_15m = (
            last_price > float(
                df["High"].iloc[-4:-1].max()
            )
        )

        breakout_30m = (
            last_price > float(
                df["High"].iloc[-7:-1].max()
            )
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

            "day_high": day_high,

            "at_day_high": at_day_high,

            "breakout_5m": breakout_5m,

            "breakout_10m": breakout_10m,

            "breakout_15m": breakout_15m,

            "breakout_30m": breakout_30m
        }

    except Exception:

        err = str(traceback.format_exc())

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
# CONSOLIDATED ALERT ENGINE
# =========================================================

def process_alerts(all_data):

    alert_count = 0

    price_batch = []

    day_high_batch = []

    breakout_batch = []

    for symbol, stock in all_data.items():

        try:

            move_pct = stock["move_pct"]

            price = stock["price"]

            # =================================================
            # PRICE MOVE ALERTS
            # =================================================

            if abs(move_pct) >= PRICE_MOVE_THRESHOLD:

                log(
                    f"🚨 PRICE ALERT | "
                    f"{symbol} | "
                    f"{move_pct:+.2f}%"
                )

                price_batch.append({

                    "symbol": symbol,

                    "move_pct": move_pct,

                    "price": price
                })

            # =================================================
            # DAY HIGH ALERTS
            # =================================================

            if stock["at_day_high"]:

                log(
                    f"🔥 DAY HIGH | "
                    f"{symbol}"
                )

                day_high_batch.append({

                    "symbol": symbol,

                    "move_pct": move_pct,

                    "price": price
                })

            # =================================================
            # MULTI TF BREAKOUTS
            # =================================================

            timeframes = []

            if stock["breakout_5m"]:
                timeframes.append("5m")

            if stock["breakout_10m"]:
                timeframes.append("10m")

            if stock["breakout_15m"]:
                timeframes.append("15m")

            if stock["breakout_30m"]:
                timeframes.append("30m")

            if timeframes:

                tf_text = "/".join(timeframes)

                log(
                    f"🚀 BREAKOUT | "
                    f"{symbol} | "
                    f"{tf_text}"
                )

                breakout_batch.append({

                    "symbol": symbol,

                    "move_pct": move_pct,

                    "price": price,

                    "timeframes": tf_text
                })

        except Exception:

            traceback.print_exc()

    # =====================================================
    # SEND PRICE ALERTS
    # =====================================================

    if price_batch:

        price_batch = sorted(
            price_batch,
            key=lambda x: abs(x["move_pct"]),
            reverse=True
        )

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            "📈 <b>PRICE MOVE ALERTS</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            ""
        ]

        for s in price_batch:

            lines.append(
                f"• <b>{s['symbol']}</b>  |  "
                f"{s['move_pct']:+.2f}%  |  "
                f"₹{s['price']:,.2f}"
            )

        lines += [
            "",
            f"📊 Stocks: {len(price_batch)}",
            f"🕐 {ist_now().strftime('%H:%M:%S')}"
        ]

        send_telegram("\n".join(lines))

        alert_count += 1

        time.sleep(0.5)

    # =====================================================
    # SEND DAY HIGH ALERTS
    # =====================================================

    if day_high_batch:

        day_high_batch = sorted(
            day_high_batch,
            key=lambda x: x["move_pct"],
            reverse=True
        )

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            "🔥 <b>DAY HIGH ALERTS</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            ""
        ]

        for s in day_high_batch:

            lines.append(
                f"• <b>{s['symbol']}</b>  |  "
                f"₹{s['price']:,.2f}  |  "
                f"{s['move_pct']:+.2f}%"
            )

        lines += [
            "",
            f"📊 Stocks: {len(day_high_batch)}",
            f"🕐 {ist_now().strftime('%H:%M:%S')}"
        ]

        send_telegram("\n".join(lines))

        alert_count += 1

        time.sleep(0.5)

    # =====================================================
    # SEND BREAKOUT ALERTS
    # =====================================================

    if breakout_batch:

        breakout_batch = sorted(
            breakout_batch,
            key=lambda x: x["move_pct"],
            reverse=True
        )

        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            "🚀 <b>MULTI TF BREAKOUTS</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            ""
        ]

        for s in breakout_batch:

            lines.append(
                f"• <b>{s['symbol']}</b>  |  "
                f"{s['timeframes']}  |  "
                f"{s['move_pct']:+.2f}%"
            )

        lines += [
            "",
            f"📊 Stocks: {len(breakout_batch)}",
            f"🕐 {ist_now().strftime('%H:%M:%S')}"
        ]

        send_telegram("\n".join(lines))

        alert_count += 1

        time.sleep(0.5)

    return alert_count

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

    alert_count = process_alerts(all_data)

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
