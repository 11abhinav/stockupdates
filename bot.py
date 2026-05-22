# =========================================================
# ADVANCED NSE MARKET INTELLIGENCE TELEGRAM BOT
# FIXED + OPTIMIZED VERSION
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
# FLASK KEEPALIVE
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
# ENV
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID   = os.environ.get("CHAT_ID")

# =========================================================
# CONFIG
# =========================================================

CHECK_INTERVAL = 60

PRICE_ALERT_THRESHOLD = 1.5
DAY_HIGH_BUFFER_PCT = 0.30

DAILY_VOLUME_SPIKE = 1.8

FIVE_MIN_SPIKE = 1.8
TEN_MIN_SPIKE = 1.8
FIFTEEN_MIN_SPIKE = 1.6

NEWS_MAX_AGE_HOURS = 12

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)

PRE_MARKET_OPEN = (8, 0)

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
# FILES
# =========================================================

SEEN_FILE = "seen_alerts.json"
PRICE_FILE = "seen_price_alerts.json"

CANDLE_5M_FILE = "candle_5m.json"
CANDLE_10M_FILE = "candle_10m.json"
CANDLE_15M_FILE = "candle_15m.json"

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
# STATE
# =========================================================

seen_alerts = set(load_json(SEEN_FILE, []))
seen_price_alerts = set(load_json(PRICE_FILE, []))

candle_5m = load_json(CANDLE_5M_FILE, {})
candle_10m = load_json(CANDLE_10M_FILE, {})
candle_15m = load_json(CANDLE_15M_FILE, {})

# =========================================================
# DAILY STATS
# =========================================================

daily_stats = {
    "news": 0,
    "price": 0,
    "dayhigh": 0,
    "5m": 0,
    "10m": 0,
    "15m": 0
}

# =========================================================
# TIME HELPERS
# =========================================================

def ist_now():
    return datetime.now(IST)

def today():
    return ist_now().strftime("%Y-%m-%d")

def is_market_open():

    now = ist_now()

    if now.weekday() >= 5:
        return False

    t = (now.hour, now.minute)

    return MARKET_OPEN <= t < MARKET_CLOSE

def is_pre_market():

    now = ist_now()

    if now.weekday() >= 5:
        return False

    t = (now.hour, now.minute)

    return PRE_MARKET_OPEN <= t < MARKET_OPEN

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

    for i in range(3):

        try:

            r = session.get(url, timeout=15)

            if r.status_code in [401,403]:
                init_nse()
                continue

            r.raise_for_status()

            return r.json()

        except Exception as e:

            print("NSE ERROR:", e)

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
            "price": p.get("lastPrice"),
            "open": p.get("open"),
            "prev": p.get("previousClose"),
            "change": p.get("pChange"),
            "high": intra.get("max"),
            "low": intra.get("min"),
            "volume": dp.get(
                "quantityTraded",
                p.get("totalTradedVolume")
            )
        }

    except Exception as e:
        print(symbol, e)

    return None

# =========================================================
# PARALLEL FETCH
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
                print("FETCH ERROR:", e)

    return result

# =========================================================
# PRICE ALERTS
# =========================================================

def process_price_alerts(all_data):

    td = today()

    for symbol, d in all_data.items():

        pchange = d.get("change")

        if pchange is None:
            continue

        if abs(pchange) < PRICE_ALERT_THRESHOLD:
            continue

        direction = "UP" if pchange > 0 else "DOWN"

        key = f"{td}-PRICE-{symbol}-{direction}"

        if key in seen_price_alerts:
            continue

        seen_price_alerts.add(key)

        save_json(
            list(seen_price_alerts),
            PRICE_FILE
        )

        daily_stats["price"] += 1

        icon = "📈" if pchange > 0 else "📉"

        send_telegram(
            f"{icon} <b>PRICE ALERT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Move:</b> {pchange:+.2f}%\n"
            f"<b>Price:</b> ₹{d['price']}\n"
            f"<b>Volume:</b> {int(d['volume']):,}"
        )

# =========================================================
# DAY HIGH BREAKOUT
# =========================================================

def process_day_high(all_data):

    td = today()

    for symbol, d in all_data.items():

        price = d.get("price")
        high = d.get("high")
        pchange = d.get("change")

        if not price or not high:
            continue

        if pchange is None:
            continue

        if pchange < 1:
            continue

        gap = abs(high - price) / high * 100

        if gap > DAY_HIGH_BUFFER_PCT:
            continue

        key = f"{td}-HIGH-{symbol}"

        if key in seen_price_alerts:
            continue

        seen_price_alerts.add(key)

        save_json(
            list(seen_price_alerts),
            PRICE_FILE
        )

        daily_stats["dayhigh"] += 1

        send_telegram(
            f"🚀 <b>DAY HIGH BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Price:</b> ₹{price}\n"
            f"<b>Day High:</b> ₹{high}\n"
            f"<b>Move:</b> {pchange:+.2f}%"
        )

# =========================================================
# REAL CANDLE BREAKOUTS
# =========================================================

def process_candle_breakout(
    all_data,
    candle_store,
    filename,
    candle_minutes,
    multiplier,
    stat_key
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

        total_volume = d.get("volume")

        if not total_volume:
            continue

        if symbol not in candle_store:

            candle_store[symbol] = {
                "candles": {},
                "last_volume": total_volume
            }

        store = candle_store[symbol]

        candles = store["candles"]

        prev_total = store.get(
            "last_volume",
            total_volume
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

        if len(values) < 3:
            continue

        current = values[-1]

        previous = values[:-1]

        avg = sum(previous) / len(previous)

        if avg <= 0:
            continue

        spike = current / avg

        pchange = d.get("change", 0)

        print(
            f"{symbol} "
            f"| current={current} "
            f"| avg={avg:.0f} "
            f"| spike={spike:.2f}"
        )

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

        daily_stats[stat_key] += 1

        icon = "📈" if pchange >= 0 else "📉"

        send_telegram(
            f"{icon} "
            f"<b>{candle_minutes}M VOLUME BREAKOUT</b>\n\n"
            f"<b>Stock:</b> {symbol}\n"
            f"<b>Spike:</b> {spike:.2f}x\n"
            f"<b>Price Change:</b> {pchange:+.2f}%\n"
            f"<b>Price:</b> ₹{d['price']}\n"
            f"<b>Candle Vol:</b> {int(current):,}\n"
            f"<b>Avg Vol:</b> {int(avg):,}"
        )

    save_json(candle_store, filename)

# =========================================================
# GOOGLE NEWS
# =========================================================

def fetch_google_news():

    cutoff = (
        ist_now() -
        timedelta(hours=NEWS_MAX_AGE_HOURS)
    )

    for symbol in WATCHLIST:

        try:

            q = f"{symbol} NSE India"

            rss = (
                "https://news.google.com/rss/search?q="
                f"{requests.utils.quote(q)}"
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

                if dt < cutoff:
                    continue

                key = f"NEWS-{symbol}-{link[-50:]}"

                if key in seen_alerts:
                    continue

                seen_alerts.add(key)

                save_json(
                    list(seen_alerts),
                    SEEN_FILE
                )

                daily_stats["news"] += 1

                send_telegram(
                    f"📰 <b>NEWS ALERT</b>\n\n"
                    f"<b>Stock:</b> {symbol}\n"
                    f"<b>Headline:</b> {title}\n\n"
                    f"{link}"
                )

        except Exception as e:
            print("NEWS ERROR:", e)

# =========================================================
# STARTUP
# =========================================================

send_telegram(
    f"✅ <b>NSE BOT STARTED</b>\n\n"
    f"<b>Stocks:</b> {len(WATCHLIST)}\n"
    f"<b>Time:</b> "
    f"{ist_now().strftime('%Y-%m-%d %H:%M:%S')}"
)

# =========================================================
# MAIN LOOP
# =========================================================

print("BOT STARTED")

last_news_scan = 0

while True:

    try:

        now = ist_now()

        if not is_market_open() and not is_pre_market():

            print("MARKET CLOSED")

            time.sleep(300)

            continue

        print(
            "\nNEW CYCLE:",
            now.strftime("%H:%M:%S")
        )

        if time.time() - last_news_scan > 900:

            print("SCANNING NEWS")

            fetch_google_news()

            last_news_scan = time.time()

        if is_market_open():

            print("FETCHING STOCKS")

            all_data = fetch_all_data()

            print(
                f"FETCHED {len(all_data)} STOCKS"
            )

            if not all_data:

                send_telegram(
                    "⚠️ NSE API FAILED"
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
                FIVE_MIN_SPIKE,
                "5m"
            )

            process_candle_breakout(
                all_data,
                candle_10m,
                CANDLE_10M_FILE,
                10,
                TEN_MIN_SPIKE,
                "10m"
            )

            process_candle_breakout(
                all_data,
                candle_15m,
                CANDLE_15M_FILE,
                15,
                FIFTEEN_MIN_SPIKE,
                "15m"
            )

    except Exception as e:

        print("MAIN LOOP ERROR:", e)

        send_telegram(
            f"❌ BOT ERROR\n\n{str(e)}"
        )

    time.sleep(CHECK_INTERVAL)
