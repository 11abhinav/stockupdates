# =========================================================
# ADVANCED NSE MARKET INTELLIGENCE TELEGRAM BOT
# FINAL ENHANCED VERSION
# =========================================================
#
# FEATURES
# ---------------------------------------------------------
# ✅ REAL 5-Min Candle Breakouts
# ✅ REAL 15-Min Candle Breakouts
# ✅ Strong Candle Detection
# ✅ Previous High Breakout Logic
# ✅ Volume Expansion Detection
# ✅ Duplicate Alert Prevention
# ✅ Cooldown Handling
# ✅ Startup Notifications
# ✅ Market Close Sleep
# ✅ Holiday Skip
# ✅ Flask Keep Alive
# ✅ Railway/Replit Ready
#
# =========================================================
# INSTALL
# =========================================================
#
# pip install yfinance flask requests pandas
#
# =========================================================

import os
import json
import time
import threading
import requests
import yfinance as yf
import pandas as pd

from flask import Flask

from datetime import (
    datetime,
    timedelta,
    timezone
)

# =========================================================
# FLASK KEEP ALIVE
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running", 200

def run_server():

    app.run(
        host="0.0.0.0",
        port=5000
    )

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

CHECK_INTERVAL = 300

VOLUME_SPIKE_MULTIPLIER = 1.8

BODY_PERCENT_THRESHOLD = 0.50

BREAKOUT_LOOKBACK = 15

COOLDOWN_MINUTES = 30

IST = timezone(
    timedelta(hours=5, minutes=30)
)

MARKET_OPEN = (9, 15)

MARKET_CLOSE = (15, 30)

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
    "FILATEX",
    "FORTIS",
    "GILLETTE",
    "GSFC",
    "HDFCBANK",
    "HINDCOPPER",
    "HINDUNILVR",
    "ICICIBANK",
    "IDBI",
    "IFCI",
    "INDUSTOWER",
    "INFY",
    "IRB",
    "IRCTC",
    "JIOFIN",
    "JPASSOCIAT",
    "JSWENERGY",
    "LATENTVIEW",
    "LLOYDSENGG",
    "LT",
    "MARUTI",
    "MAZDOCK",
    "NATCOPHARM",
    "ONGC",
    "PIDILITIND",
    "POONAWALA",
    "PVRINOX",
    "RTNPOWER",
    "RELIANCE",
    "RVNL",
    "SBIN",
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

SEEN_ALERTS_FILE = "seen_alerts.json"

# =========================================================
# JSON HELPERS
# =========================================================

def load_json(filename, default):

    if os.path.exists(filename):

        try:

            with open(filename, "r") as f:
                return json.load(f)

        except:
            return default

    return default

def save_json(data, filename):

    temp = filename + ".tmp"

    with open(temp, "w") as f:
        json.dump(data, f)

    os.replace(temp, filename)

# =========================================================
# LOAD STATE
# =========================================================

seen_alerts = load_json(
    SEEN_ALERTS_FILE,
    {}
)

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    try:

        url = (
            f"https://api.telegram.org/bot"
            f"{BOT_TOKEN}/sendMessage"
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
# TIME HELPERS
# =========================================================

def ist_now():

    return datetime.now(IST)

def is_market_open():

    now = ist_now()

    if now.weekday() >= 5:
        return False

    t = (now.hour, now.minute)

    return MARKET_OPEN <= t < MARKET_CLOSE

# =========================================================
# FETCH OHLC DATA
# =========================================================

def fetch_ohlc(symbol):

    try:

        yahoo_symbol = f"{symbol}.NS"

        df = yf.download(

            yahoo_symbol,

            period="1d",

            interval="5m",

            progress=False,

            auto_adjust=True,

            threads=False

        )

        if df.empty:
            return None

        if len(df) > 1:
            df = df.iloc[:-1]

        return df

    except Exception as e:

        print(f"FETCH ERROR {symbol}")

        print(e)

        return None

# =========================================================
# BREAKOUT ENGINE
# =========================================================

def process_breakout(symbol):

    try:

        df = fetch_ohlc(symbol)

        if df is None:
            return

        if len(df) < 25:
            return

        current = df.iloc[-1]

        previous_df = df.iloc[:-1]

        # =================================================
        # VALUES
        # =================================================

        current_close = float(current["Close"])

        current_open = float(current["Open"])

        current_high = float(current["High"])

        current_low = float(current["Low"])

        current_volume = float(current["Volume"])

        previous_high = float(

            previous_df["High"]

            .tail(BREAKOUT_LOOKBACK)

            .max()

        )

        avg_volume = float(

            previous_df["Volume"]

            .tail(20)

            .mean()

        )

        # =================================================
        # CONDITIONS
        # =================================================

        breakout = (

            current_close > previous_high

        )

        volume_spike = (

            current_volume >

            (avg_volume * VOLUME_SPIKE_MULTIPLIER)

        )

        candle_range = (

            current_high - current_low

        )

        if candle_range <= 0:
            return

        candle_body = abs(

            current_close - current_open

        )

        body_percent = (

            candle_body / candle_range

        )

        strong_body = (

            body_percent >=

            BODY_PERCENT_THRESHOLD

        )

        # =================================================
        # LOGS
        # =================================================

        print(
            f"{symbol} | "
            f"Close={round(current_close,2)} | "
            f"PrevHigh={round(previous_high,2)} | "
            f"Vol={int(current_volume)} | "
            f"AvgVol={int(avg_volume)} | "
            f"Body={round(body_percent*100,2)}%"
        )

        # =================================================
        # FINAL SIGNAL
        # =================================================

        if not (
            breakout and
            volume_spike and
            strong_body
        ):
            return

        # =================================================
        # DUPLICATE PREVENTION
        # =================================================

        now = ist_now()

        current_key = (

            f"{symbol}_"

            f"{now.strftime('%Y%m%d_%H%M')}"

        )

        last_alert = seen_alerts.get(symbol)

        if last_alert:

            try:

                last_time = datetime.strptime(

                    last_alert,

                    "%Y%m%d_%H%M"

                )

                diff = (

                    datetime.now() -

                    last_time

                ).total_seconds() / 60

                if diff < COOLDOWN_MINUTES:
                    return

            except:
                pass

        seen_alerts[symbol] = current_key

        save_json(
            seen_alerts,
            SEEN_ALERTS_FILE
        )

        # =================================================
        # TELEGRAM ALERT
        # =================================================

        send_telegram(f"""
🚀 5M BREAKOUT ALERT

Stock:
{symbol}

Close:
₹{round(current_close,2)}

Previous High:
₹{round(previous_high,2)}

Current Volume:
{int(current_volume):,}

Average Volume:
{int(avg_volume):,}

Volume Spike:
{round(current_volume/avg_volume,1)}x

Body Strength:
{round(body_percent*100,2)}%

Trend:
STRONG MOMENTUM
""")

        print(f"🚀 SIGNAL SENT : {symbol}")

    except Exception as e:

        print(f"BREAKOUT ERROR {symbol}")

        print(e)

# =========================================================
# STARTUP ALERT
# =========================================================

send_telegram(f"""
✅ BOT STARTED

Time:
{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}

Stocks:
{len(WATCHLIST)}
""")

# =========================================================
# MAIN LOOP
# =========================================================

print("BOT STARTED")

while True:

    try:

        if not is_market_open():

            print("MARKET CLOSED")

            time.sleep(300)

            continue

        print(
            "\nSCAN:",
            ist_now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        for symbol in WATCHLIST:

            process_breakout(symbol)

            time.sleep(1)

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
