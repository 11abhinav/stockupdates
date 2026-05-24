# =========================================================
# ADVANCED NSE MOMENTUM + VOLUME BREAKOUT TELEGRAM BOT
# FINAL FULL STABLE VERSION
# =========================================================
#
# FEATURES
# ---------------------------------------------------------
#
# ✅ Google News Alerts (24x7)
# ✅ NSE Corporate Announcement Alerts (24x7)
# ✅ NSE Notice PDF Links
# ✅ Rounded OHLC Candle Engine
# ✅ 5m / 10m / 15m Candle Tracking
# ✅ Multi Candle Breakout Detection
# ✅ Day High Breakout Detection
# ✅ ±3% Daily Move Alerts
# ✅ Volume Expansion Detection
# ✅ Duplicate Alert Prevention
# ✅ Railway Compatible
# ✅ Exception Reporting to Telegram
# ✅ Persistent Candle Storage
# ✅ Invalid NSE Data Protection
#
# =========================================================

print("SCRIPT STARTED")

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

if not BOT_TOKEN:
    print("BOT_TOKEN missing")

if not CHAT_ID:
    print("CHAT_ID missing")

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

    except Exception as e:

        print("SAVE JSON ERROR:", e)

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

    except Exception as e:

        print("LOAD JSON ERROR:", e)

    return default

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
# PREVIOUS CANDLE
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

        pchange = (
            (price - prev_close)
            / prev_close
        ) * 100

        if abs(pchange) < PRICE_MOVE_THRESHOLD:
            return

        direction = "UP" if pchange > 0 else "DOWN"

        key = f"PRICE-{symbol}-{direction}"

        if key in seen_alerts:
            return

        seen_alerts.add(key)

        send_telegram(
            f"📈 <b>3% PRICE MOVE</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Move:</b> {pchange:+.2f}%\n"
            f"<b>Price:</b> ₹{price:,.2f}"
        )

    except Exception as e:

        send_telegram(
            f"❌ PRICE ALERT ERROR\n\n"
            f"{symbol}\n\n{str(e)}"
        )

# =========================================================
# DAY HIGH ALERT
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

        key = f"DAYHIGH-{symbol}-{current_5m}"

        if key in seen_alerts:
            return

        seen_alerts.add(key)

        send_telegram(
            f"🔥 <b>DAY HIGH BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Price:</b> ₹{price:,.2f}\n"
            f"<b>Day High:</b> ₹{day_high:,.2f}"
        )

    except Exception as e:

        send_telegram(
            f"❌ DAY HIGH ERROR\n\n"
            f"{symbol}\n\n{str(e)}"
        )

# =========================================================
# BREAKOUT ALERT
# =========================================================

def process_breakout_alert(symbol, stock):

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

        # =====================================================
        # CURRENT CANDLES
        # =====================================================

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

        # =====================================================
        # PREVIOUS HIGHS
        # =====================================================

        prev_5m_high = safe_float(
            prev_5m.get("high")
        )

        prev_10m_high = safe_float(
            prev_10m.get("high")
        )

        prev_15m_high = safe_float(
            prev_15m.get("high")
        )

        # =====================================================
        # CURRENT CLOSES
        # =====================================================

        current_5m_close = safe_float(
            current_5m.get("close")
        )

        current_10m_close = safe_float(
            current_10m.get("close")
        )

        current_15m_close = safe_float(
            current_15m.get("close")
        )

        # =====================================================
        # STRICT BREAKOUT LOGIC
        # =====================================================

        breakout = (

            current_5m_close > prev_5m_high

            and

            current_10m_close > prev_10m_high

            and

            current_15m_close > prev_15m_high

        )

        if not breakout:
            return

        # =====================================================
        # MINIMUM BREAKOUT %
        # =====================================================

        breakout_pct = (
            (
                current_5m_close
                - prev_5m_high
            )
            / prev_5m_high
        ) * 100

        # minimum 0.40% breakout
        if breakout_pct < 0.40:
            return

        # =====================================================
        # VOLUME CONFIRMATION
        # =====================================================

        current_5m_vol = safe_int(
            current_5m.get("volume")
        )

        prev_5m_vol = safe_int(
            prev_5m.get("volume")
        )

        if current_5m_vol <= prev_5m_vol:
            return

        # =====================================================
        # ONE ALERT PER 5M CANDLE
        # =====================================================

        key = (
            f"BREAKOUT-"
            f"{symbol}-"
            f"{get_candle_time(ist_now(), 5)}"
        )

        if key in seen_alerts:
            return

        seen_alerts.add(key)

        send_telegram(
            f"🚀 <b>STRONG BREAKOUT</b>\n\n"

            f"<b>Stock:</b> {symbol}\n"

            f"<b>Breakout:</b> "
            f"{breakout_pct:.2f}%\n\n"

            f"<b>Current Close:</b>\n"
            f"5m: ₹{current_5m_close:,.2f}\n"
            f"10m: ₹{current_10m_close:,.2f}\n"
            f"15m: ₹{current_15m_close:,.2f}\n\n"

            f"<b>Previous Highs:</b>\n"
            f"5m: ₹{prev_5m_high:,.2f}\n"
            f"10m: ₹{prev_10m_high:,.2f}\n"
            f"15m: ₹{prev_15m_high:,.2f}\n\n"

            f"✅ Volume Confirmed\n"
            f"✅ Multi-timeframe Confirmed"
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

        current_5m_vol = safe_int(
            current_5m.get("volume")
        )

        prev_5m_vol = safe_int(
            prev_5m.get("volume")
        )

        current_10m_vol = safe_int(
            current_10m.get("volume")
        )

        prev_10m_vol = safe_int(
            prev_10m.get("volume")
        )

        current_15m_vol = safe_int(
            current_15m.get("volume")
        )

        prev_15m_vol = safe_int(
            prev_15m.get("volume")
        )

        breakout = (

            current_5m_vol > prev_5m_vol

            and

            current_10m_vol > prev_10m_vol

            and

            current_15m_vol > prev_15m_vol

        )

        if not breakout:
            return

        # =====================================================
        # STRICT MOMENTUM FILTER
        # =====================================================

        if current_5m_vol < (prev_5m_vol * 1.20):
            return

        if current_10m_vol < (prev_10m_vol * 1.15):
            return

        if current_15m_vol < (prev_15m_vol * 1.10):
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
            f"📊 <b>STRICT VOLUME BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n\n"

            f"<b>5m:</b> "
            f"{current_5m_vol:,} vs {prev_5m_vol:,}\n"

            f"<b>10m:</b> "
            f"{current_10m_vol:,} vs {prev_10m_vol:,}\n"

            f"<b>15m:</b> "
            f"{current_15m_vol:,} vs {prev_15m_vol:,}\n\n"

            f"✅ Strong multi-timeframe volume expansion"
        )

    except Exception as e:

        send_telegram(
            f"❌ VOLUME ERROR\n\n"
            f"{symbol}\n\n"
            f"{str(e)}"
        )

        # =====================================================
        # TELEGRAM MESSAGE
        # =====================================================

        send_telegram(

            f"🔥 <b>BULLISH SETUP</b>\n\n"

            f"<b>Stock:</b> {symbol}\n"
            f"<b>Price:</b> ₹{price:,.2f}\n"
            f"<b>Price Change:</b> "
            f"{price_pct:+.2f}%\n\n"

            f"<b>Signals:</b>\n"

            f"{signal_icon(price_strength)} "
            f"Price Strength\n"

            f"{signal_icon(oi_strength)} "
            f"OI Strength\n"

            f"{signal_icon(put_writing)} "
            f"Put Writing\n"

            f"{signal_icon(volume_expansion)} "
            f"Volume Expansion\n"

            f"{signal_icon(trend_confirmation)} "
            f"Trend Confirmation\n\n"

            f"<b>Volume Details:</b>\n"

            f"Current 5m: "
            f"{current_5m_vol:,}\n"

            f"Previous 5m: "
            f"{prev_5m_vol:,}\n"

            f"Expansion: "
            f"{volume_ratio:.2f}x\n\n"

            f"<b>Trend Details:</b>\n"

            f"Current Price: "
            f"₹{price:,.2f}\n"

            f"Previous High: "
            f"₹{prev_high:,.2f}\n\n"

            f"<b>Confidence Score:</b> "
            f"{score}/100 "
            f"(3 active signals)\n\n"

            f"🚀 Strong Bullish Momentum Detected"
        )

    except Exception as e:

        send_telegram(
            f"❌ BULLISH SETUP ERROR\n\n"
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

                if dt.date() != ist_now().date():
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

        # NSE sometimes returns invalid response
        if not data or not isinstance(data, list):
            return

        for item in data:

            try:

                # Sometimes NSE sends invalid rows
                if not isinstance(item, dict):
                    continue

                symbol = item.get("symbol", "")

                if symbol not in WATCHLIST:
                    continue

                subject = item.get(
                    "desc",
                    item.get("subject", "")
                )

                details = item.get(
                    "attchmntText",
                    ""
                )

                an_dt = item.get("an_dt", "")

                attachment = item.get(
                    "attchmntFile",
                    ""
                )

                notice_link = ""

                if attachment:

                    notice_link = (
                        "https://nsearchives.nseindia.com"
                        + attachment
                    )

                key = (
                    f"NSE-"
                    f"{symbol}-"
                    f"{an_dt}-"
                    f"{subject[:30]}"
                )

                if key in seen_alerts:
                    continue

                seen_alerts.add(key)

                msg = (
                    f"📢 <b>NSE ANNOUNCEMENT</b>\n\n"
                    f"<b>Stock:</b> {symbol}\n"
                    f"<b>Time:</b> {an_dt}\n\n"
                    f"<b>Subject:</b>\n"
                    f"{subject}"
                )

                if details:

                    msg += (
                        f"\n\n"
                        f"<b>Details:</b>\n"
                        f"{details}"
                    )

                if notice_link:

                    msg += (
                        f"\n\n"
                        f"<b>Notice PDF:</b>\n"
                        f"{notice_link}"
                    )

                send_telegram(msg)

            except Exception as e:

                send_telegram(
                    f"❌ NSE ITEM ERROR\n\n"
                    f"{str(e)}"
                )

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

print("MAIN LOOP STARTED")

last_news_scan = 0

while True:

    try:

        # =====================================================
        # NEWS + NSE ANNOUNCEMENTS
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
