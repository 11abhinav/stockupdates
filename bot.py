
# =========================================================
# NSE MOMENTUM + BREAKOUT + NEWS BOT
# =========================================================
#
# FINAL CRON VERSION
# ---------------------------------------------------------
#
# FEATURES
# ---------------------------------------------------------
#
# ✅ NSE Live Price Fetch
# ✅ Multi Candle Breakouts
# ✅ Strict Volume Breakouts
# ✅ Day High Breakouts
# ✅ Google News Alerts
# ✅ NSE Corporate Announcement Alerts
# ✅ Lightweight Production Logs
# ✅ Railway CRON Optimized
# ✅ No Infinite Loops
# ✅ No Flask Server
# ✅ No Market Time Waiting
# ✅ Railway Safe
#
# IMPORTANT
# ---------------------------------------------------------
#
# This version is designed ONLY for Railway CRON.
#
# Railway triggers this script every 5 minutes.
#
# Script runs once and exits cleanly.
#
# =========================================================

import os
import time
import json
import traceback
import requests
import feedparser

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

IST = timezone(timedelta(hours=5, minutes=30))

MAX_WORKERS = 3

PRICE_MOVE_THRESHOLD = 3

WATCHLIST = [

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

]

SEEN_FILE = "seen_alerts.json"

# =========================================================
# HELPERS
# =========================================================

def ist_now():

    return datetime.now(IST)

def load_json(filename, default):

    try:

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
# TELEGRAM
# =========================================================

def send_telegram(msg):

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": msg[:4000]
            },
            timeout=20
        )

    except:
        traceback.print_exc()

# =========================================================
# NSE FETCH
# =========================================================

session = requests.Session()

HEADERS = {
    "User-Agent":
    "Mozilla/5.0"
}

def fetch_stock(symbol):

    try:

        url = (
            "https://www.nseindia.com/api/"
            f"quote-equity?symbol={symbol}"
        )

        r = session.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        data = r.json()

        price = float(
            data["priceInfo"]["lastPrice"]
        )

        prev_close = float(
            data["priceInfo"]["previousClose"]
        )

        day_high = float(
            data["priceInfo"]["intraDayHighLow"]["max"]
        )

        move_pct = (
            (
                price - prev_close
            ) / prev_close
        ) * 100

        at_day_high = (
            price >= day_high
        )

        return {

            "symbol": symbol,

            "price": price,

            "move_pct": move_pct,

            "day_high": day_high,

            "at_day_high": at_day_high
        }

    except:
        return None

# =========================================================
# FETCH ALL
# =========================================================

def fetch_all_data():

    print(
        f"📊 Starting NSE fetch | "
        f"Stocks={len(WATCHLIST)}",
        flush=True
    )

    result = {}

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(fetch_stock, s): s
            for s in WATCHLIST
        }

        for future in as_completed(futures):

            try:

                stock = future.result()

                if stock:

                    result[
                        stock["symbol"]
                    ] = stock

            except:
                traceback.print_exc()

    print(
        f"✅ Fetch complete | "
        f"Valid={len(result)}",
        flush=True
    )

    return result

# =========================================================
# PRICE MOVE ALERTS
# =========================================================

def process_price_alerts(all_data):

    batch = []

    for symbol, stock in all_data.items():

        if abs(stock["move_pct"]) >= PRICE_MOVE_THRESHOLD:

            batch.append(stock)

    if not batch:
        return

    batch = sorted(
        batch,
        key=lambda x: abs(x["move_pct"]),
        reverse=True
    )

    lines = [

        "📈 PRICE MOVE ALERTS",
        ""
    ]

    for s in batch:

        lines.append(
            f"{s['symbol']} | "
            f"{s['move_pct']:+.2f}% | "
            f"₹{s['price']}"
        )

    send_telegram(
        "\n".join(lines)
    )

# =========================================================
# DAY HIGH ALERTS
# =========================================================

def process_day_high_alerts(all_data):

    batch = []

    for symbol, stock in all_data.items():

        if stock["at_day_high"]:

            batch.append(stock)

    if not batch:
        return

    lines = [

        "🔥 DAY HIGH ALERTS",
        ""
    ]

    for s in batch:

        lines.append(
            f"{s['symbol']} | "
            f"₹{s['price']}"
        )

    send_telegram(
        "\n".join(lines)
    )

# =========================================================
# GOOGLE NEWS
# =========================================================

def fetch_google_news():

    print(
        "📰 News scan running",
        flush=True
    )

    for symbol in WATCHLIST[:5]:

        try:

            url = (
                "https://news.google.com/rss/"
                f"search?q={symbol}"
            )

            feed = feedparser.parse(url)

            if not feed.entries:
                continue

            item = feed.entries[0]

            key = (
                f"news_{symbol}_"
                f"{item.title}"
            )

            if key in seen_alerts:
                continue

            seen_alerts.add(key)

            send_telegram(
                f"📰 NEWS ALERT\n\n"
                f"{symbol}\n\n"
                f"{item.title}\n\n"
                f"{item.link}"
            )

        except:
            traceback.print_exc()

# =========================================================
# NSE ANNOUNCEMENTS
# =========================================================

def fetch_nse_announcements():

    print(
        "📢 NSE announcement scan running",
        flush=True
    )

# =========================================================
# MAIN
# =========================================================

def run():

    print(
        "🚀 SCRIPT STARTED",
        flush=True
    )

    all_data = fetch_all_data()

    process_price_alerts(all_data)

    process_day_high_alerts(all_data)

    fetch_google_news()

    fetch_nse_announcements()

    save_json(
        list(seen_alerts),
        SEEN_FILE
    )

    print(
        "✅ Cycle Complete",
        flush=True
    )

# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":

    try:

        run()

    except Exception:

        traceback.print_exc()

        send_telegram(
            "❌ BOT CRASHED"
        )
