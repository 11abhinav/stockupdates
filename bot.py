# =========================================================
# ADVANCED NSE MARKET INTELLIGENCE TELEGRAM BOT
# =========================================================
#
# FEATURES
# ---------------------------------------------------------
# ✅ NSE Corporate Announcements
# ✅ Google News (Fresh <=24 hrs only)
# ✅ Price Spike Alerts
# ✅ Daily Volume Spike Alerts
# ✅ REAL 5-Min Candle Volume Spike Alerts
# ✅ REAL 15-Min Candle Volume Spike Alerts
# ✅ NSE API Cache Optimization
# ✅ Duplicate Alert Protection
# ✅ Startup / Market Close Notifications
# ✅ Smart Sleep Until Next Market Open
# ✅ Weekend + Holiday Skip
# ✅ Retry Handling
# ✅ Safe JSON Writes
# ✅ End-of-Day Summary
# ✅ Lower NSE Ban Risk
#
# MARKET TIMINGS
# ---------------------------------------------------------
# BOT ACTIVE:
# 8:00 AM IST → 3:30 PM IST
#
# =========================================================

import os
import json
import time
import hashlib
import threading
import requests
import feedparser

from flask import Flask

from datetime import (
    datetime,
    timedelta,
    timezone
)

from email.utils import (
    parsedate_to_datetime
)

from nsepython import nsefetch

# =========================================================
# KEEP ALIVE SERVER
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running", 200

def run_server():
    app.run(host="0.0.0.0", port=5000)

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

CHECK_INTERVAL = 60

PRICE_ALERT_THRESHOLD = 3.0

VOLUME_SPIKE_MULTIPLIER = 3.0

REALTIME_PRICE_CONFIRMATION = 1.0

FIVE_MIN_SPIKE_MULTIPLIER = 3.0
FIFTEEN_MIN_SPIKE_MULTIPLIER = 2.5

IST = timezone(
    timedelta(hours=5, minutes=30)
)

MARKET_OPEN = (8, 0)
MARKET_CLOSE = (15, 30)

# =========================================================
# NSE HOLIDAYS (ADD MORE YEARLY)
# =========================================================

NSE_HOLIDAYS = {

    "2026-01-26",
    "2026-03-14",
    "2026-08-15",
    "2026-10-02",

}

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
    "ANTHEM",
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
    "EID PARRY",
    "FILATEX",
    "FORTIS",
    "GILLETTE",
    "GLOBUSSPR",
    "GSFC",
    "HDFCBANK",
    "HINDCOPPER",
    "HINDUNILVR",
    "HYUNDAI",
    "ITBEES",
    "ICICIAMC",
    "ICICIBANK",
    "IDBI",
    "IFCI",
    "INDUSTOWER",
    "CCAVENUE",
    "INFY",
    "IRB",
    "IRCTC",
    "JIOFIN",
    "JPASSOCIAT",
    "JSWENERGY",
    "KWIL",
    "LATENTVIEW",
    "LGEINDIA",
    "LOTUSDEV",
    "LLOYDSENGG",
    "LT",
    "MARUTI",
    "MAZDOCK",
    "MIRZAINT",
    "MENON PISTON",
    "NATCOPHARM",
    "ONGC",
    "ORIENTCEM",
    "PIDILITIND",
    "POONAWALA",
    "PVRINOX",
    "RTNPOWER",
    "RELIANCE",
    "RELINFRA",
    "RVNL",
    "SANGHI IND",
    "SBIN",
    "SRHHYPOLTD",
    "SUVIDHAA INFO",
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

SEEN_FILE = "seen_alerts.json"
PRICE_FILE = "seen_price_alerts.json"

VOLUME_HISTORY_FILE = "volume_history.json"

CANDLE_5M_FILE = "candle_5m.json"
CANDLE_15M_FILE = "candle_15m.json"

# =========================================================
# SAFE JSON HELPERS
# =========================================================

def load_json(filename, default):

    if os.path.exists(filename):

        try:

            with open(filename, "r") as f:
                return json.load(f)

        except:
            return default

    return default

def safe_json_dump(data, filename):

    temp = filename + ".tmp"

    with open(temp, "w") as f:

        json.dump(data, f)

    os.replace(temp, filename)

# =========================================================
# LOAD STATE
# =========================================================

seen_alerts = set(
    load_json(SEEN_FILE, [])
)

seen_price_alerts = set(
    load_json(PRICE_FILE, [])
)

volume_history = load_json(
    VOLUME_HISTORY_FILE,
    {}
)

candle_5m = load_json(
    CANDLE_5M_FILE,
    {}
)

candle_15m = load_json(
    CANDLE_15M_FILE,
    {}
)

# =========================================================
# DAILY COUNTERS
# =========================================================

daily_stats = {

    "news": 0,
    "price": 0,
    "volume": 0,
    "5m": 0,
    "15m": 0

}

# =========================================================
# TIME HELPERS
# =========================================================

def ist_now():
    return datetime.now(IST)

def is_holiday():

    today = ist_now().strftime("%Y-%m-%d")

    return today in NSE_HOLIDAYS

def is_market_open():

    now = ist_now()

    if now.weekday() >= 5:
        return False

    if is_holiday():
        return False

    t = (now.hour, now.minute)

    return MARKET_OPEN <= t < MARKET_CLOSE

def seconds_until_next_market_open():

    now = ist_now()

    candidate = now.replace(

        hour=MARKET_OPEN[0],
        minute=MARKET_OPEN[1],
        second=0,
        microsecond=0

    )

    if candidate <= now:
        candidate += timedelta(days=1)

    while (
        candidate.weekday() >= 5
        or candidate.strftime("%Y-%m-%d")
        in NSE_HOLIDAYS
    ):

        candidate += timedelta(days=1)

    return (candidate - now).total_seconds()

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendMessage"
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
# STARTUP MESSAGE
# =========================================================

send_telegram(f"""
✅ BOT STARTED

Time:
{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}

Stocks:
{len(WATCHLIST)}

Check Interval:
{CHECK_INTERVAL}s
""")

# =========================================================
# NEWS KEYWORDS
# =========================================================

IMPORTANT_KEYWORDS = [

    "order",
    "results",
    "dividend",
    "buyback",
    "merger",
    "approval",
    "contract",
    "acquisition",
    "stake",
    "investment",
    "expansion",
    "guidance"

]

# =========================================================
# NEWS SENTIMENT
# =========================================================

def generate_comment(headline):

    h = headline.lower()

    positive = [

        "order",
        "profit",
        "approval",
        "buyback",
        "dividend",
        "expansion",
        "investment",
        "acquisition"

    ]

    negative = [

        "loss",
        "penalty",
        "fraud",
        "default",
        "downgrade"

    ]

    for p in positive:

        if p in h:
            return "Positive News → Bullish"

    for n in negative:

        if n in h:
            return "Negative News → Bearish"

    return "Neutral News"

# =========================================================
# NSE FETCH WITH RETRY
# =========================================================

def fetch_price_data(symbol):

    for attempt in range(3):

        try:

            url = (
                f"https://www.nseindia.com/api/"
                f"quote-equity?symbol={symbol}"
            )

            data = nsefetch(url)

            p = data.get("priceInfo", {})

            return {

                "symbol":
                    symbol,

                "last_price":
                    p.get("lastPrice"),

                "open_price":
                    p.get("open"),

                "change":
                    p.get("change"),

                "pchange":
                    p.get("pChange"),

                "high":
                    p.get(
                        "intraDayHighLow", {}
                    ).get("max"),

                "low":
                    p.get(
                        "intraDayHighLow", {}
                    ).get("min"),

                "volume":
                    data.get(
                        "securityWiseDP", {}
                    ).get("quantityTraded")

            }

        except Exception as e:

            print(
                f"Retry {attempt+1} [{symbol}]"
            )

            time.sleep(2)

    return None

# =========================================================
# CACHE ALL STOCK DATA
# =========================================================

def fetch_all_stock_data():

    all_data = {}

    for symbol in WATCHLIST:

        try:

            data = fetch_price_data(symbol)

            if data:
                all_data[symbol] = data

            time.sleep(0.25)

        except Exception as e:

            print("Cache Error:", e)

    return all_data

# =========================================================
# NSE ANNOUNCEMENTS
# =========================================================

def process_nse_announcements():

    try:

        url = (
            "https://www.nseindia.com/api/"
            "corporate-announcements"
            "?index=equities"
        )

        data = nsefetch(url)

    except Exception as e:

        print("NSE News Error:", e)
        return

    for item in data:

        try:

            symbol = item.get(
                "symbol", ""
            ).strip().upper()

            if symbol not in WATCHLIST:
                continue

            headline = item.get(
                "subject", ""
            ).strip()

            if not headline:
                continue

            hl = headline.lower()

            if not any(
                k in hl
                for k in IMPORTANT_KEYWORDS
            ):
                continue

            unique_key = hashlib.md5(

                f"NSE-{symbol}-{headline}".encode()

            ).hexdigest()

            if unique_key in seen_alerts:
                continue

            seen_alerts.add(unique_key)

            safe_json_dump(

                list(seen_alerts),
                SEEN_FILE

            )

            daily_stats["news"] += 1

            send_telegram(f"""
🚨 NSE ANNOUNCEMENT

Stock:
{symbol}

Headline:
{headline}

Comment:
{generate_comment(headline)}

Time:
{ist_now().strftime('%H:%M:%S IST')}
""")

        except Exception as e:

            print("NSE Parse Error:", e)

# =========================================================
# GOOGLE NEWS
# =========================================================

def fetch_google_news(stock):

    try:

        query = stock.replace(" ", "+")

        rss = (
            "https://news.google.com/rss/search?"
            f"q={query}+NSE+India+stock"
        )

        return feedparser.parse(rss).entries

    except:
        return []

# =========================================================
# INTERNET NEWS
# =========================================================

def process_internet_news():

    for stock in WATCHLIST:

        try:

            entries = fetch_google_news(stock)

            for entry in entries[:5]:

                try:

                    if hasattr(entry, "published"):

                        published = (
                            parsedate_to_datetime(
                                entry.published
                            )
                        )

                        if published.tzinfo is None:

                            published = (
                                published.replace(
                                    tzinfo=timezone.utc
                                )
                            )

                        age = (
                            datetime.now(
                                timezone.utc
                            )
                            - published
                        )

                        if age.total_seconds() > 86400:
                            continue

                    headline = (
                        entry.title
                        .lower()
                        .strip()
                        .replace(
                            " - google news",
                            ""
                        )
                    )

                    if not any(
                        k in headline
                        for k in IMPORTANT_KEYWORDS
                    ):
                        continue

                    unique_key = hashlib.md5(

                        f"{stock}-{headline}".encode()

                    ).hexdigest()

                    if unique_key in seen_alerts:
                        continue

                    seen_alerts.add(unique_key)

                    safe_json_dump(

                        list(seen_alerts),
                        SEEN_FILE

                    )

                    daily_stats["news"] += 1

                    send_telegram(f"""
📰 INTERNET NEWS

Stock:
{stock}

Headline:
{headline}

Comment:
{generate_comment(headline)}

Time:
{ist_now().strftime('%H:%M:%S IST')}
""")

                except Exception as e:

                    print("News Parse Error:", e)

        except Exception as e:

            print("Internet News Error:", e)

# =========================================================
# PRICE ALERTS
# =========================================================

def process_price_alerts(all_data):

    today = ist_now().strftime("%Y-%m-%d")

    for symbol, data in all_data.items():

        try:

            pchange = data["pchange"]

            if pchange is None:
                continue

            if abs(pchange) < PRICE_ALERT_THRESHOLD:
                continue

            direction = (
                "UP"
                if pchange > 0
                else "DOWN"
            )

            unique_key = (
                f"{today}-{symbol}-{direction}"
            )

            if unique_key in seen_price_alerts:
                continue

            seen_price_alerts.add(unique_key)

            safe_json_dump(

                list(seen_price_alerts),
                PRICE_FILE

            )

            daily_stats["price"] += 1

            arrow = (
                "📈"
                if pchange > 0
                else "📉"
            )

            send_telegram(f"""
{arrow} PRICE ALERT

Stock:
{symbol}

Change:
{pchange:+.2f}%

Price:
₹{data['last_price']}

High:
₹{data['high']}

Low:
₹{data['low']}
""")

        except Exception as e:

            print("Price Error:", e)

# =========================================================
# VOLUME SPIKE ALERTS
# =========================================================

def process_volume_alerts(all_data):

    for symbol, data in all_data.items():

        try:

            volume = data["volume"]

            if not volume:
                continue

            history = volume_history.get(
                symbol,
                []
            )

            if len(history) >= 10:

                avg = sum(history) / len(history)

                if (
                    volume
                    >= avg * VOLUME_SPIKE_MULTIPLIER
                ):

                    unique_key = (
                        f"VOL-{symbol}-"
                        f"{ist_now().strftime('%Y%m%d')}"
                    )

                    if unique_key not in seen_price_alerts:

                        seen_price_alerts.add(
                            unique_key
                        )

                        safe_json_dump(

                            list(seen_price_alerts),
                            PRICE_FILE

                        )

                        daily_stats["volume"] += 1

                        send_telegram(f"""
🔊 VOLUME SPIKE

Stock:
{symbol}

Current Volume:
{volume:,}

Average:
{int(avg):,}

Spike:
{volume/avg:.1f}x

Price Change:
{data['pchange']:+.2f}%
""")

            history.append(volume)

            volume_history[symbol] = history[-10:]

            safe_json_dump(

                volume_history,
                VOLUME_HISTORY_FILE

            )

        except Exception as e:

            print("Volume Error:", e)

# =========================================================
# REAL CANDLE HELPERS
# =========================================================

def get_candle_key(minutes):

    now = ist_now()

    rounded = (
        now.minute // minutes
    ) * minutes

    candle = now.replace(

        minute=rounded,
        second=0,
        microsecond=0

    )

    return candle.strftime(
        "%Y-%m-%d %H:%M"
    )

# =========================================================
# REAL CANDLE ENGINE
# =========================================================

def process_real_candle_spikes(

    all_data,
    candle_store,
    filename,
    candle_minutes,
    multiplier,
    stats_key

):

    candle_key = get_candle_key(
        candle_minutes
    )

    for symbol, data in all_data.items():

        try:

            volume = data["volume"]

            if not volume:
                continue

            if symbol not in candle_store:

                candle_store[symbol] = {}

            candle_store[symbol][
                candle_key
            ] = volume

            candles = sorted(

                candle_store[symbol].items()

            )

            candles = candles[-30:]

            candle_store[symbol] = dict(
                candles
            )

            safe_json_dump(
                candle_store,
                filename
            )

            if len(candles) < 5:
                continue

            candle_volumes = []

            for i in range(1, len(candles)):

                prev_vol = candles[i-1][1]
                curr_vol = candles[i][1]

                cv = curr_vol - prev_vol

                if cv > 0:
                    candle_volumes.append(cv)

            if len(candle_volumes) < 5:
                continue

            current_cv = candle_volumes[-1]

            recent_avg = (

                sum(candle_volumes[-10:])
                / min(
                    10,
                    len(candle_volumes)
                )

            )

            if recent_avg <= 0:
                continue

            spike_ratio = (
                current_cv / recent_avg
            )

            if spike_ratio < multiplier:
                continue

            if (
                abs(data["pchange"])
                < REALTIME_PRICE_CONFIRMATION
            ):
                continue

            unique_key = (
                f"{candle_minutes}M-"
                f"{symbol}-"
                f"{candle_key}"
            )

            if unique_key in seen_price_alerts:
                continue

            seen_price_alerts.add(
                unique_key
            )

            safe_json_dump(

                list(seen_price_alerts),
                PRICE_FILE

            )

            daily_stats[stats_key] += 1

            direction = (
                "📈"
                if data["pchange"] > 0
                else "📉"
            )

            send_telegram(f"""
{direction} REAL {candle_minutes}-MIN SPIKE

Stock:
{symbol}

Candle Volume:
{current_cv:,}

Average:
{int(recent_avg):,}

Spike:
{spike_ratio:.1f}x

Price Change:
{data['pchange']:+.2f}%

Price:
₹{data['last_price']}

Candle:
{candle_key}
""")

        except Exception as e:

            print(
                f"{candle_minutes}m Error:",
                e
            )

# =========================================================
# DAILY SUMMARY
# =========================================================

def send_daily_summary():

    send_telegram(f"""
📊 DAILY SUMMARY

News Alerts:
{daily_stats['news']}

Price Alerts:
{daily_stats['price']}

Volume Spikes:
{daily_stats['volume']}

5-Min Spikes:
{daily_stats['5m']}

15-Min Spikes:
{daily_stats['15m']}

Time:
{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}
""")

# =========================================================
# MAIN LOOP
# =========================================================

print("BOT STARTED")

market_close_sent = False

while True:

    try:

        if not is_market_open():

            now = ist_now()

            if (
                now.hour >= MARKET_CLOSE[0]
                and not market_close_sent
            ):

                send_daily_summary()

                send_telegram(f"""
📴 MARKET CLOSED

Time:
{now.strftime('%Y-%m-%d %H:%M:%S IST')}
""")

                market_close_sent = True

            secs = seconds_until_next_market_open()

            hrs = int(secs // 3600)
            mins = int(
                (secs % 3600) // 60
            )

            print(
                f"Market Closed. "
                f"Sleeping {hrs}h {mins}m"
            )

            time.sleep(
                min(secs, 3600)
            )

            continue

        market_close_sent = False

        print(
            "\nNEW CYCLE:",
            ist_now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        # FETCH ONCE
        all_data = fetch_all_stock_data()

        # NEWS
        process_nse_announcements()

        process_internet_news()

        # PRICE
        process_price_alerts(
            all_data
        )

        # DAILY VOLUME
        process_volume_alerts(
            all_data
        )

        # REAL 5-MIN
        process_real_candle_spikes(

            all_data=all_data,

            candle_store=candle_5m,

            filename=CANDLE_5M_FILE,

            candle_minutes=5,

            multiplier=FIVE_MIN_SPIKE_MULTIPLIER,

            stats_key="5m"

        )

        # REAL 15-MIN
        process_real_candle_spikes(

            all_data=all_data,

            candle_store=candle_15m,

            filename=CANDLE_15M_FILE,

            candle_minutes=15,

            multiplier=FIFTEEN_MIN_SPIKE_MULTIPLIER,

            stats_key="15m"

        )

    except Exception as e:

        err = f"""
❌ BOT ERROR

{str(e)}

Time:
{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}
"""

        print(err)

        send_telegram(err)

    time.sleep(CHECK_INTERVAL)
