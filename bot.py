# =========================================================
# ADVANCED NSE MARKET INTELLIGENCE TELEGRAM BOT
# FINAL PRODUCTION VERSION
# =========================================================
#
# FEATURES
# ---------------------------------------------------------
#
# ✅ Google News Alerts (24x7)
# ✅ NSE Corporate Announcement Alerts (24x7)
# ✅ Price Breakout Alerts
# ✅ Day High Breakout Alerts
# ✅ 5-Minute Volume Spike Alerts
# ✅ 10-Minute Volume Spike Alerts
# ✅ 15-Minute Volume Spike Alerts
# ✅ Railway Hosting Compatible
# ✅ Telegram Error Reporting
# ✅ Duplicate Alert Prevention
# ✅ Automatic NSE Cookie Refresh
# ✅ Parallel NSE Fetching
# ✅ Safe Handling of Invalid NSE Data
#
# ---------------------------------------------------------
# ALERT TIMINGS
# ---------------------------------------------------------
#
# 📰 NEWS + NSE ANNOUNCEMENTS:
#     RUNS 24x7
#
# 📈 PRICE + VOLUME ALERTS:
#     8:45 AM → 4:00 PM IST
#
# ---------------------------------------------------------
# HOW VOLUME BREAKOUT WORKS
# ---------------------------------------------------------
#
# NSE gives cumulative volume.
#
# Bot estimates candle volume using:
#
# current_total_volume - previous_total_volume
#
# Then compares:
#
# current candle volume
# VS
# average previous candles
#
# If spike ratio exceeds threshold:
#
# alert is triggered.
#
# ---------------------------------------------------------
# IMPORTANT NOTE
# ---------------------------------------------------------
#
# NSE API is unofficial.
#
# Sometimes:
# - volume may lag
# - Railway IP may get throttled
# - cached responses may occur
#
# So volume breakout alerts depend on NSE API quality.
#
# =========================================================

import os
import json
import time
import threading
import requests
import feedparser

from flask import Flask
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================================================
# FLASK KEEP ALIVE SERVER
# =========================================================
#
# Railway requires an active web service.
# This lightweight Flask server keeps the app alive.
#
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "NSE BOT RUNNING ✅", 200

threading.Thread(
    target=lambda: app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    ),
    daemon=True
).start()

# =========================================================
# TELEGRAM ENV VARIABLES
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# =========================================================
# CONFIGURATION
# =========================================================

CHECK_INTERVAL = 60

# Price alert threshold (%)
PRICE_ALERT_THRESHOLD = 1.0

# Near day high %
DAY_HIGH_BUFFER_PCT = 0.30

# Volume breakout multipliers
FIVE_MIN_SPIKE = 1.4
TEN_MIN_SPIKE = 1.4
FIFTEEN_MIN_SPIKE = 1.3

# Ignore news older than this
NEWS_MAX_AGE_MINUTES = 60

# =========================================================
# TIMEZONE
# =========================================================

IST = timezone(timedelta(hours=5, minutes=30))

# =========================================================
# MARKET ALERT TIMINGS
# =========================================================
#
# Price + volume alerts ONLY during these hours.
#
# =========================================================

ALERT_START = (8, 45)
ALERT_END = (16, 0)

# =========================================================
# WATCHLIST
# =========================================================

WATCHLIST = sorted(list(set([
    "ADANIENT","ADANIGREEN","ADANIPORTS","AKZOINDIA",
    "ATGL","AFCONS","ATL","ANANTRAJ","ANTHEM",
    "ARIHANTCAP","ASIANPAINT","BAJAJFINSV","BEL",
    "BLUEDART","BLS","CASTROLIND","CGPOWER","CLEAN",
    "DBL","EIDPARRY","FILATEX","FORTIS","GILLETTE",
    "GLOBUSSPR","GSFC","HDFCBANK","HINDCOPPER",
    "HINDUNILVR","HYUNDAI","ITBEES","ICICIAMC",
    "ICICIBANK","IDBI","IFCI","INDUSTOWER","CCAVENUE",
    "INFY","IRB","IRCTC","JIOFIN","JPASSOCIAT",
    "JSWENERGY","KWIL","LATENTVIEW","LGEINDIA",
    "LOTUSDEV","LLOYDSENGG","LT","MARUTI","MAZDOCK",
    "MIRZAINT","MENONPISTONS","NATCOPHARM","ONGC",
    "ORIENTCEM","PIDILITIND","POONAWALLA","PVRINOX",
    "RTNPOWER","RELIANCE","RELINFRA","RVNL",
    "SANGHIIND","SBIN","SRHHYPOLTD","SUVIDHA",
    "SUPREMEIND","SUZLON","SWIGGY","SYMPHONY",
    "TATATECH","TITAN","TRENT","VBL"
])))

# =========================================================
# STATE FILES
# =========================================================

SEEN_FILE = "seen_alerts.json"
PRICE_FILE = "seen_price_alerts.json"

CANDLE_5M_FILE = "candle_5m.json"
CANDLE_10M_FILE = "candle_10m.json"
CANDLE_15M_FILE = "candle_15m.json"

# =========================================================
# SAFE HELPERS
# =========================================================
#
# NSE sometimes returns:
#
# - None
# - ""
# - "-"
#
# These helpers safely handle invalid data.
#
# =========================================================

def safe_int(v):

    try:

        if v in [None, "", "-", "None"]:
            return 0

        return int(float(v))

    except:
        return 0

def safe_float(v):

    try:

        if v in [None, "", "-", "None"]:
            return 0.0

        return float(v)

    except:
        return 0.0

# =========================================================
# JSON HELPERS
# =========================================================

def load_json(filename, default):

    try:

        if os.path.exists(filename):

            with open(filename, "r") as f:
                return json.load(f)

    except:
        pass

    return default

def save_json(data, filename):

    tmp = filename + ".tmp"

    with open(tmp, "w") as f:
        json.dump(data, f)

    os.replace(tmp, filename)

# =========================================================
# LOAD STATE
# =========================================================

seen_alerts = set(load_json(SEEN_FILE, []))
seen_price_alerts = set(load_json(PRICE_FILE, []))

# Prevent huge JSON growth
if len(seen_alerts) > 5000:
    seen_alerts = set(list(seen_alerts)[-2000:])

candle_5m = load_json(CANDLE_5M_FILE, {})
candle_10m = load_json(CANDLE_10M_FILE, {})
candle_15m = load_json(CANDLE_15M_FILE, {})

# =========================================================
# TIME HELPERS
# =========================================================

def ist_now():
    return datetime.now(IST)

def is_alert_hours():

    now = ist_now()

    if now.weekday() >= 5:
        return False

    t = (now.hour, now.minute)

    return ALERT_START <= t < ALERT_END

# =========================================================
# TELEGRAM SENDER
# =========================================================

def send_telegram(msg):

    try:

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": msg[:4000],
                "parse_mode": "HTML"
            },
            timeout=20
        )

    except Exception as e:

        print("TELEGRAM ERROR:", e)

# =========================================================
# NSE SESSION
# =========================================================
#
# NSE blocks requests without cookies/user-agent.
#
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent":
    "Mozilla/5.0"
})

def init_nse():

    try:

        session.get(
            "https://www.nseindia.com",
            timeout=10
        )

    except:
        pass

init_nse()

def nse_get(url):

    for _ in range(3):

        try:

            r = session.get(url, timeout=15)

            # NSE cookie expired
            if r.status_code in [401, 403]:

                init_nse()
                continue

            r.raise_for_status()

            return r.json()

        except Exception:

            time.sleep(2)

    return None

# =========================================================
# FETCH STOCK DATA
# =========================================================

def fetch_price_data(symbol):

    try:

        url = (
            "https://www.nseindia.com/api/"
            f"quote-equity?symbol={symbol}"
        )

        data = nse_get(url)

        if not data:
            return None

        p = data.get("priceInfo", {})
        dp = data.get("securityWiseDP", {})
        intra = p.get("intraDayHighLow", {})

        return {

            "symbol": symbol,

            "price":
                safe_float(p.get("lastPrice")),

            "open":
                safe_float(p.get("open")),

            "prev":
                safe_float(p.get("previousClose")),

            "change":
                safe_float(p.get("pChange")),

            "high":
                safe_float(intra.get("max")),

            "low":
                safe_float(intra.get("min")),

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
# PARALLEL FETCHING
# =========================================================
#
# Speeds up NSE data collection.
#
# =========================================================

def fetch_all_data():

    result = {}

    with ThreadPoolExecutor(max_workers=10) as executor:

        futures = {
            executor.submit(fetch_price_data, s): s
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

    return result

# =========================================================
# PRICE ALERTS
# =========================================================

def process_price_alerts(all_data):

    today = ist_now().strftime("%Y-%m-%d")

    for symbol, d in all_data.items():

        pchange = safe_float(d.get("change"))

        if abs(pchange) < PRICE_ALERT_THRESHOLD:
            continue

        direction = "UP" if pchange > 0 else "DOWN"

        key = f"{today}-PRICE-{symbol}-{direction}"

        if key in seen_price_alerts:
            continue

        seen_price_alerts.add(key)

        save_json(
            list(seen_price_alerts),
            PRICE_FILE
        )

        icon = "📈" if pchange > 0 else "📉"

        send_telegram(
            f"{icon} <b>PRICE ALERT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Move:</b> {pchange:+.2f}%\n"
            f"<b>Price:</b> ₹{safe_float(d.get('price'))}\n"
            f"<b>Volume:</b> {safe_int(d.get('volume')):,}"
        )

# =========================================================
# DAY HIGH BREAKOUT ALERTS
# =========================================================

def process_day_high(all_data):

    today = ist_now().strftime("%Y-%m-%d")

    for symbol, d in all_data.items():

        price = safe_float(d.get("price"))
        high = safe_float(d.get("high"))
        pchange = safe_float(d.get("change"))

        if not price or not high:
            continue

        if pchange < 1:
            continue

        gap = abs(high - price) / high * 100

        if gap > DAY_HIGH_BUFFER_PCT:
            continue

        key = f"{today}-HIGH-{symbol}"

        if key in seen_price_alerts:
            continue

        seen_price_alerts.add(key)

        save_json(
            list(seen_price_alerts),
            PRICE_FILE
        )

        send_telegram(
            f"🚀 <b>DAY HIGH BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Price:</b> ₹{price}\n"
            f"<b>Day High:</b> ₹{high}\n"
            f"<b>Move:</b> {pchange:+.2f}%"
        )

# =========================================================
# VOLUME BREAKOUT ENGINE
# =========================================================

def process_candle_breakout(
    all_data,
    candle_store,
    filename,
    candle_minutes,
    multiplier
):

    now = ist_now()

    rounded = (
        now.minute // candle_minutes
    ) * candle_minutes

    candle_time = now.replace(
        minute=rounded,
        second=0,
        microsecond=0
    )

    candle_key = candle_time.strftime(
        "%Y-%m-%d %H:%M"
    )

    for symbol, d in all_data.items():

        total_volume = safe_int(d.get("volume"))

        if total_volume <= 0:
            continue

        if symbol not in candle_store:

            candle_store[symbol] = {
                "candles": {},
                "last_volume": total_volume
            }

        store = candle_store[symbol]

        candles = store["candles"]

        prev_total = safe_int(
            store.get("last_volume")
        )

        delta = total_volume - prev_total

        if delta < 0:
            delta = 0

        if candle_key not in candles:
            candles[candle_key] = delta
        else:
            candles[candle_key] += delta

        store["last_volume"] = total_volume

        keys = sorted(candles.keys())

        if len(keys) > 50:

            for k in keys[:-50]:
                del candles[k]

        values = list(candles.values())

        # Need warmup candles
        if len(values) < 3:
            continue

        current = safe_int(values[-1])

        previous = [
            safe_int(v)
            for v in values[:-1]
        ]

        avg = (
            sum(previous) / len(previous)
            if previous else 0
        )

        if avg <= 0:
            continue

        spike = current / avg

        if spike < multiplier:
            continue

        key = f"{candle_minutes}-{symbol}-{candle_key}"

        if key in seen_price_alerts:
            continue

        seen_price_alerts.add(key)

        save_json(
            list(seen_price_alerts),
            PRICE_FILE
        )

        pchange = safe_float(d.get("change"))

        icon = "📈" if pchange >= 0 else "📉"

        send_telegram(
            f"{icon} "
            f"<b>{candle_minutes}M VOLUME BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Spike:</b> {spike:.2f}x\n"
            f"<b>Price Change:</b> {pchange:+.2f}%\n"
            f"<b>Price:</b> ₹{safe_float(d.get('price'))}\n"
            f"<b>Candle Vol:</b> {safe_int(current):,}\n"
            f"<b>Avg Vol:</b> {safe_int(avg):,}"
        )

    save_json(candle_store, filename)

# =========================================================
# GOOGLE NEWS ALERTS
# =========================================================

def fetch_google_news():

    for symbol in WATCHLIST:

        try:

            query = f"{symbol} NSE India"

            rss = (
                "https://news.google.com/rss/search?q="
                f"{requests.utils.quote(query)}"
                "&hl=en-IN&gl=IN&ceid=IN:en"
            )

            feed = feedparser.parse(rss)

            for entry in feed.entries[:2]:

                title = entry.get("title", "")
                link = entry.get("link", "")
                pub = entry.get("published", "")

                try:

                    dt = parsedate_to_datetime(pub)
                    dt = dt.astimezone(IST)

                except:
                    continue

                # Ignore previous-day news
                if dt.date() != ist_now().date():
                    continue

                age_minutes = (
                    ist_now() - dt
                ).total_seconds() / 60

                # Ignore old news
                if age_minutes > NEWS_MAX_AGE_MINUTES:
                    continue

                key = (
                    f"NEWS-"
                    f"{symbol}-"
                    f"{dt.strftime('%Y%m%d%H')}-"
                    f"{title[:40]}"
                )

                if key in seen_alerts:
                    continue

                seen_alerts.add(key)

                save_json(
                    list(seen_alerts),
                    SEEN_FILE
                )

                send_telegram(
                    f"📰 <b>NEWS ALERT</b>\n\n"
                    f"<b>Stock:</b> {symbol}\n"
                    f"<b>Headline:</b> {title}\n\n"
                    f"{link}"
                )

        except Exception as e:

            send_telegram(
                f"❌ NEWS ERROR\n\n{str(e)}"
            )

# =========================================================
# NSE CORPORATE ANNOUNCEMENTS
# =========================================================

def fetch_nse_announcements():

    try:

        url = (
            "https://www.nseindia.com/api/"
            "corporate-announcements?index=equities"
        )

        data = nse_get(url)

        if not data:
            return

        for item in data:

            try:

                symbol = item.get("symbol", "")

                if symbol not in WATCHLIST:
                    continue

                subject = item.get(
                    "desc",
                    item.get("subject", "")
                )

                an_dt = item.get("an_dt", "")

                key = (
                    f"NSE-"
                    f"{symbol}-"
                    f"{an_dt}-"
                    f"{subject[:30]}"
                )

                if key in seen_alerts:
                    continue

                seen_alerts.add(key)

                save_json(
                    list(seen_alerts),
                    SEEN_FILE
                )

                send_telegram(
                    f"📢 <b>NSE ANNOUNCEMENT</b>\n\n"
                    f"<b>Stock:</b> {symbol}\n"
                    f"<b>Time:</b> {an_dt}\n"
                    f"<b>Subject:</b> {subject}"
                )

            except:
                pass

    except Exception as e:

        send_telegram(
            f"❌ NSE ANNOUNCEMENT ERROR\n\n"
            f"{str(e)}"
        )

# =========================================================
# STARTUP MESSAGE
# =========================================================

send_telegram(
    f"✅ <b>NSE BOT STARTED</b>\n\n"
    f"<b>Stocks:</b> {len(WATCHLIST)}\n"
    f"<b>Time:</b> "
    f"{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}"
)

# =========================================================
# MAIN LOOP
# =========================================================

print("BOT STARTED")

last_news_scan = 0

while True:

    try:

        # =====================================================
        # NEWS + ANNOUNCEMENTS RUN 24x7
        # =====================================================

        if time.time() - last_news_scan > 900:

            fetch_google_news()

            fetch_nse_announcements()

            last_news_scan = time.time()

        # =====================================================
        # MARKET ALERTS DURING MARKET HOURS ONLY
        # =====================================================

        if is_alert_hours():

            all_data = fetch_all_data()

            if not all_data:

                send_telegram(
                    "⚠️ <b>NSE API FAILED</b>"
                )

                time.sleep(120)

                continue

            process_price_alerts(all_data)

            process_day_high(all_data)

            process_candle_breakout(
                all_data,
                candle_5m,
                CANDLE_5M_FILE,
                5,
                FIVE_MIN_SPIKE
            )

            process_candle_breakout(
                all_data,
                candle_10m,
                CANDLE_10M_FILE,
                10,
                TEN_MIN_SPIKE
            )

            process_candle_breakout(
                all_data,
                candle_15m,
                CANDLE_15M_FILE,
                15,
                FIFTEEN_MIN_SPIKE
            )

    except Exception as e:

        send_telegram(
            f"❌ MAIN LOOP ERROR\n\n"
            f"{str(e)}"
        )

    time.sleep(CHECK_INTERVAL)
