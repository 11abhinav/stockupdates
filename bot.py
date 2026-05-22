# =========================================================
# ADVANCED NSE MOMENTUM + VOLUME BREAKOUT TELEGRAM BOT
# FINAL STABLE VERSION
# =========================================================
#
# FEATURES
# ---------------------------------------------------------
#
# ✅ Google News Alerts (24x7)
# ✅ NSE Corporate Announcement Alerts (24x7)
# ✅ Real Rounded OHLC Candle Engine
# ✅ 5m / 10m / 15m Candle Tracking
# ✅ Multi Candle Breakout Detection
# ✅ Day High Breakout Detection
# ✅ ±3% Daily Move Alerts
# ✅ Volume Expansion Detection
# ✅ Duplicate Alert Prevention
# ✅ Railway Compatible
# ✅ Exception Reporting to Telegram
# ✅ Persistent Candle Storage
#
# =========================================================
# ALERT LOGIC
# =========================================================
#
# 🚀 MULTI CANDLE BREAKOUT
#
# Triggered when:
#
# Current price breaks:
#
# - previous 5m candle HIGH
# - previous 10m candle HIGH
# - previous 15m candle HIGH
#
# ---------------------------------------------------------
#
# 🔥 DAY HIGH BREAKOUT
#
# Triggered when:
#
# Current price >= official NSE day high
#
# One alert per 5m candle.
#
# ---------------------------------------------------------
#
# 📈 PRICE MOVE ALERT
#
# Triggered when:
#
# stock moves:
#
# +3%
# OR
# -3%
#
# from previous close.
#
# ---------------------------------------------------------
#
# 📊 VOLUME BREAKOUT
#
# Triggered when:
#
# current 5m candle volume >
# previous 5m candle volume
#
# AND
#
# current 10m candle volume >
# previous 10m candle volume
#
# AND
#
# current 15m candle volume >
# previous 15m candle volume
#
# ---------------------------------------------------------
#
# 📰 NEWS + NSE ANNOUNCEMENTS
#
# Runs 24x7
#
# ---------------------------------------------------------
#
# 📈 MARKET ALERTS
#
# Run ONLY during:
#
# 8:45 AM → 4:00 PM IST
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
# FLASK SERVER
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():
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
    "ADANIENT", "ADANIGREEN", "ADANIPORTS", "AKZOINDIA", "ATGL", "AFCONS", "ATL",
    "ANANTRAJ", "ANTHEM", "ARIHANTCAP", "ASIANPAINT", "BAJAJFINSV", "BEL",
    "BLUEDART", "BLS", "CASTROLIND", "CGPOWER", "CLEAN", "DBL", "EIDPARRY",
    "FILATEX", "FORTIS", "GILLETTE", "GLOBUSSPR", "GSFC", "HDFCBANK",
    "HINDCOPPER", "HINDUNILVR", "HYUNDAI", "ITBEES", "ICICIAMC", "ICICIBANK",
    "IDBI", "IFCI", "INDUSTOWER", "CCAVENUE", "INFY", "IRB", "IRCTC", "JIOFIN",
    "JPASSOCIAT", "JSWENERGY", "KWIL", "LATENTVIEW", "LGEINDIA", "LOTUSDEV",
    "LLOYDSENGG", "LT", "MARUTI", "MAZDOCK", "MENONPISTONS", "MIRZAINT",
    "NATCOPHARM", "ONGC", "ORIENTCEM", "PFC", "PIDILITIND", "POONAWALLA",
    "PVRINOX", "RTNPOWER", "RELIANCE", "RELINFRA", "RVNL", "SANGHIIND",
    "SBIN", "SRHHYPOLTD", "SUVIDHA", "SUPREMEIND", "SUZLON", "SWIGGY",
    "SYMPHONY", "TATATECH", "TITAN", "TRENT", "VBL"
])))

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

candles = load_json(CANDLES_FILE, {})

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
# TELEGRAM
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

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0"
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

            if r.status_code in [401, 403]:

                init_nse()
                continue

            r.raise_for_status()

            return r.json()

        except:

            time.sleep(2)

    return None

# =========================================================
# FETCH STOCK DATA
# =========================================================

def fetch_stock(symbol):

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

            "prev_close":
                safe_float(p.get("previousClose")),

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
            f"{symbol}\n{str(e)}"
        )

    return None

# =========================================================
# PARALLEL FETCH
# =========================================================

def fetch_all_data():

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

    return result

# =========================================================
# ROUNDED CANDLE TIME
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
# UPDATE OHLC CANDLES
# =========================================================

def update_candles(symbol, price, volume):

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

        # =====================================================
        # NEW CANDLE
        # =====================================================

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

        # =====================================================
        # UPDATE OHLC
        # =====================================================

        candle["high"] = max(
            candle["high"],
            price
        )

        candle["low"] = min(
            candle["low"],
            price
        )

        candle["close"] = price

        # =====================================================
        # UPDATE VOLUME
        # =====================================================

        delta = volume - candle.get(
            "last_total_volume",
            volume
        )

        if delta > 0:
            candle["volume"] += delta

        candle["last_total_volume"] = volume

        # =====================================================
        # KEEP LAST 50 CANDLES
        # =====================================================

        keys = sorted(data.keys())

        if len(keys) > 50:

            for k in keys[:-50]:
                del data[k]

# =========================================================
# GET PREVIOUS CLOSED CANDLE
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

        price = stock["price"]

        prev_close = stock["prev_close"]

        if prev_close <= 0:
            return

        pchange = (
            (price - prev_close)
            / prev_close
        ) * 100

        if abs(pchange) < PRICE_MOVE_THRESHOLD:
            return

        direction = "UP" if pchange > 0 else "DOWN"

        key = (
            f"PRICE-"
            f"{symbol}-"
            f"{direction}"
        )

        if key in seen_alerts:
            return

        seen_alerts.add(key)

        send_telegram(
            f"📈 <b>3% PRICE MOVE</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Move:</b> {pchange:+.2f}%\n"
            f"<b>Price:</b> ₹{price}"
        )

    except Exception as e:

        send_telegram(
            f"❌ PRICE ALERT ERROR\n\n"
            f"{symbol}\n\n"
            f"{str(e)}"
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

        current_5m = get_candle_time(
            ist_now(),
            5
        ).strftime("%Y-%m-%d %H:%M")

        key = (
            f"DAYHIGH-"
            f"{symbol}-"
            f"{current_5m}"
        )

        if key in seen_alerts:
            return

        seen_alerts.add(key)

        send_telegram(
            f"🔥 <b>DAY HIGH BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Price:</b> ₹{price}\n"
            f"<b>Day High:</b> ₹{day_high}"
        )

    except Exception as e:

        send_telegram(
            f"❌ DAY HIGH ERROR\n\n"
            f"{symbol}\n\n"
            f"{str(e)}"
        )

# =========================================================
# MULTI CANDLE BREAKOUT
# =========================================================

def process_breakout_alert(symbol, stock):

    try:

        prev_5m = get_previous_candle(symbol, 5)
        prev_10m = get_previous_candle(symbol, 10)
        prev_15m = get_previous_candle(symbol, 15)

        # =====================================================
        # WARMUP PROTECTION
        # =====================================================

        if not prev_5m:
            return

        if not prev_10m:
            return

        if not prev_15m:
            return

        # =====================================================
        # SAFETY CHECKS
        # =====================================================

        required = ["high"]

        for r in required:

            if r not in prev_5m:
                return

            if r not in prev_10m:
                return

            if r not in prev_15m:
                return

        price = safe_float(stock.get("price"))

        breakout = (

            price > safe_float(prev_5m.get("high"))

            and

            price > safe_float(prev_10m.get("high"))

            and

            price > safe_float(prev_15m.get("high"))

        )

        if not breakout:
            return

        key = (
            f"BREAKOUT-"
            f"{symbol}-"
            f"{get_candle_time(ist_now(), 5)}"
        )

        if key in seen_alerts:
            return

        seen_alerts.add(key)

        send_telegram(
            f"🚀 <b>MULTI CANDLE BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Price:</b> ₹{price}\n\n"
            f"Above Previous:\n"
            f"✅ 5m High\n"
            f"✅ 10m High\n"
            f"✅ 15m High"
        )

    except Exception as e:

        send_telegram(
            f"❌ BREAKOUT ERROR\n\n"
            f"{symbol}\n\n"
            f"{str(e)}"
        )

# =========================================================
# VOLUME BREAKOUT
# =========================================================

def process_volume_breakout(symbol):

    try:

        prev_5m = get_previous_candle(symbol, 5)
        prev_10m = get_previous_candle(symbol, 10)
        prev_15m = get_previous_candle(symbol, 15)

        if not prev_5m:
            return

        if not prev_10m:
            return

        if not prev_15m:
            return

        current_5m_all = candles.get(symbol, {}).get("5m", {})
        current_10m_all = candles.get(symbol, {}).get("10m", {})
        current_15m_all = candles.get(symbol, {}).get("15m", {})

        if not current_5m_all:
            return

        if not current_10m_all:
            return

        if not current_15m_all:
            return

        current_5m = current_5m_all[
            sorted(current_5m_all.keys())[-1]
        ]

        current_10m = current_10m_all[
            sorted(current_10m_all.keys())[-1]
        ]

        current_15m = current_15m_all[
            sorted(current_15m_all.keys())[-1]
        ]

        breakout = (

            safe_int(current_5m.get("volume"))
            >
            safe_int(prev_5m.get("volume"))

            and

            safe_int(current_10m.get("volume"))
            >
            safe_int(prev_10m.get("volume"))

            and

            safe_int(current_15m.get("volume"))
            >
            safe_int(prev_15m.get("volume"))

        )

        if not breakout:
            return

        key = (
            f"VOLUME-"
            f"{symbol}-"
            f"{get_candle_time(ist_now(), 5)}"
        )

        if key in seen_alerts:
            return

        seen_alerts.add(key)

        send_telegram(
            f"📊 <b>VOLUME BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n\n"
            f"✅ 5m Volume Rising\n"
            f"✅ 10m Volume Rising\n"
            f"✅ 15m Volume Rising"
        )

    except Exception as e:

        send_telegram(
            f"❌ VOLUME ERROR\n\n"
            f"{symbol}\n\n"
            f"{str(e)}"
        )

# =========================================================
# GOOGLE NEWS
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

                age_minutes = (
                    ist_now() - dt
                ).total_seconds() / 60

                if age_minutes > NEWS_MAX_AGE_MINUTES:
                    continue

                key = (
                    f"NEWS-"
                    f"{symbol}-"
                    f"{title[:40]}"
                )

                if key in seen_alerts:
                    continue

                seen_alerts.add(key)

                send_telegram(
                    f"📰 <b>NEWS ALERT</b>\n\n"
                    f"<b>Stock:</b> {symbol}\n"
                    f"<b>Headline:</b> {title}\n\n"
                    f"{link}"
                )

        except Exception as e:

            send_telegram(
                f"❌ NEWS ERROR\n\n"
                f"{str(e)}"
            )

# =========================================================
# NSE ANNOUNCEMENTS
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
    f"✅ <b>NSE MOMENTUM BOT STARTED</b>\n\n"
    f"<b>Stocks:</b> {len(WATCHLIST)}\n"
    f"<b>Time:</b> "
    f"{ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}"
)

# =========================================================
# MAIN LOOP
# =========================================================

last_news_scan = 0

while True:

    try:

        # =====================================================
        # NEWS + ANNOUNCEMENTS 24x7
        # =====================================================

        if time.time() - last_news_scan > 900:

            fetch_google_news()

            fetch_nse_announcements()

            last_news_scan = time.time()

        # =====================================================
        # MARKET ALERTS
        # =====================================================

        if is_alert_hours():

            all_data = fetch_all_data()

            for symbol, stock in all_data.items():

                if not stock:
                    continue

                update_candles(
                    symbol,
                    stock["price"],
                    stock["volume"]
                )

                process_price_move_alert(
                    symbol,
                    stock
                )

                process_day_high_breakout(
                    symbol,
                    stock
                )

                process_breakout_alert(
                    symbol,
                    stock
                )

                process_volume_breakout(
                    symbol
                )

            # =================================================
            # SAVE STATE
            # =================================================

            save_json(
                candles,
                CANDLES_FILE
            )

            save_json(
                list(seen_alerts),
                SEEN_FILE
            )

    except Exception as e:

        send_telegram(
            f"❌ MAIN LOOP ERROR\n\n"
            f"{str(e)}"
        )

    time.sleep(CHECK_INTERVAL)
