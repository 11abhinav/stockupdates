# =========================================================
# NSE MOMENTUM + BREAKOUT + NEWS BOT  (FIXED)
# =========================================================
#
# FIXES APPLIED
# ---------------------------------------------------------
# FIX 1: NSE session priming  — hit nseindia.com homepage
#         first to get cookies; without this every API call
#         returns a 403 / HTML error silently caught as None
#         and all_data stays empty → no price alerts ever.
#
# FIX 2: Day-high dedup  — alerts now stored in seen_alerts
#         with a date stamp so the same stock only fires once
#         per day, not on every 5-min cron run.
#
# FIX 3: BSE announcements  — replaces the empty NSE stub
#         with a working BSE corporate filings RSS feed.
#         BSE is public, no login required, never 403s.
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
CHAT_ID   = os.environ.get("CHAT_ID")

IST = timezone(timedelta(hours=5, minutes=30))

MAX_WORKERS = 3

PRICE_MOVE_THRESHOLD = 3   # percent

WATCHLIST = [
    "ADANIENT", "ADANIGREEN", "ADANIPORTS", "AKZOINDIA", "AFCONS",
    "ANANTRAJ", "ANTHEM", "ARIHANTCAP", "ASIANPAINT", "ATGL",
    "ATL", "BAJAJFINSV", "BEL", "BLS", "BLUEDART", "CASTROLIND",
    "CCAVENUE", "CGPOWER", "CLEAN", "DBL", "EIDPARRY", "FILATEX",
    "FORTIS", "GILLETTE", "GLOBUSSPR", "GSFC", "HDFCBANK",
    "HINDCOPPER", "HINDUNILVR", "HYUNDAI", "ICICIAMC", "ICICIBANK",
    "IDBI", "IFCI", "INDUSTOWER", "INFY", "IRB", "IRCTC", "ITBEES",
    "JIOFIN", "JPASSOCIAT", "JSWENERGY", "KWIL", "LATENTVIEW",
    "LGEINDIA", "LLOYDSENGG", "LOTUSDEV", "LT", "MARUTI", "MAZDOCK",
    "MENNPIS", "MIRZAINT", "NATCOPHARM", "ONGC", "ORIENTCEM",
    "PFC", "PIDILITIND", "POONAWALLA", "PVRINOX", "RELIANCE",
    "RELINFRA", "RTNPOWER", "RVNL", "SANGHIIND", "SBIN",
    "SRHHYPOLTD", "SUPREMEIND", "SUVIDHAA", "SUZLON", "SWIGGY",
    "SYMPHONY", "TATATECH", "TITAN", "TRENT",
]

SEEN_FILE = "seen_alerts.json"

# =========================================================
# HELPERS
# =========================================================

def ist_now():
    return datetime.now(IST)

def today_str():
    return ist_now().strftime("%Y-%m-%d")

def load_json(filename, default):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(data, filename):
    try:
        with open(filename, "w") as f:
            json.dump(data, f)
    except Exception:
        traceback.print_exc()

seen_alerts = set(load_json(SEEN_FILE, []))

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": msg[:4000]},
            timeout=20,
        )
    except Exception:
        traceback.print_exc()

# =========================================================
# NSE SESSION
# FIX 1: prime session by hitting the homepage first.
# NSE requires a valid cookie from the homepage before it
# will respond to /api/ endpoints. Without this every call
# returns HTML or a 401/403, gets caught silently, and
# fetch_stock returns None — so all_data is always empty.
# =========================================================

session = requests.Session()

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
}

def prime_nse_session():
    """
    Hit the NSE homepage to get cookies.
    Must be called once before any API requests.
    """
    try:
        session.get(
            "https://www.nseindia.com",
            headers=NSE_HEADERS,
            timeout=15,
        )
        time.sleep(1)   # brief pause so cookies settle
        print("✅ NSE session primed", flush=True)
    except Exception:
        print("⚠️  NSE session prime failed", flush=True)
        traceback.print_exc()

# =========================================================
# NSE FETCH (single stock)
# =========================================================

def fetch_stock(symbol):
    try:
        url = (
            "https://www.nseindia.com/api/"
            f"quote-equity?symbol={symbol}"
        )
        r = session.get(url, headers=NSE_HEADERS, timeout=15)
        data = r.json()

        price      = float(data["priceInfo"]["lastPrice"])
        prev_close = float(data["priceInfo"]["previousClose"])
        day_high   = float(data["priceInfo"]["intraDayHighLow"]["max"])

        move_pct   = ((price - prev_close) / prev_close) * 100
        at_day_high = price >= day_high

        return {
            "symbol":      symbol,
            "price":       price,
            "move_pct":    move_pct,
            "day_high":    day_high,
            "at_day_high": at_day_high,
        }

    except Exception:
        # Log the symbol so you can see which ones fail
        print(f"⚠️  fetch_stock failed: {symbol}", flush=True)
        return None

# =========================================================
# FETCH ALL
# =========================================================

def fetch_all_data():
    print(
        f"📊 Starting NSE fetch | Stocks={len(WATCHLIST)}",
        flush=True,
    )

    result = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_stock, s): s
            for s in WATCHLIST
        }
        for future in as_completed(futures):
            try:
                stock = future.result()
                if stock:
                    result[stock["symbol"]] = stock
            except Exception:
                traceback.print_exc()

    print(
        f"✅ Fetch complete | Valid={len(result)}/{len(WATCHLIST)}",
        flush=True,
    )
    return result

# =========================================================
# PRICE MOVE ALERTS
# =========================================================

def process_price_alerts(all_data):
    batch = [
        s for s in all_data.values()
        if abs(s["move_pct"]) >= PRICE_MOVE_THRESHOLD
    ]

    if not batch:
        print("ℹ️  No price alerts this cycle", flush=True)
        return

    batch.sort(key=lambda x: abs(x["move_pct"]), reverse=True)

    lines = ["📈 PRICE MOVE ALERTS", ""]
    for s in batch:
        lines.append(
            f"{s['symbol']} | {s['move_pct']:+.2f}% | ₹{s['price']}"
        )

    send_telegram("\n".join(lines))

# =========================================================
# DAY HIGH ALERTS
# FIX 2: deduplicate using seen_alerts with a date key so
# the same stock only fires once per calendar day.
# =========================================================

def process_day_high_alerts(all_data):
    batch = []
    today = today_str()

    for symbol, stock in all_data.items():
        if not stock["at_day_high"]:
            continue
        key = f"dayhigh_{symbol}_{today}"
        if key in seen_alerts:
            continue
        seen_alerts.add(key)
        batch.append(stock)

    if not batch:
        print("ℹ️  No new day-high alerts this cycle", flush=True)
        return

    lines = ["🔥 DAY HIGH ALERTS", ""]
    for s in batch:
        lines.append(f"{s['symbol']} | ₹{s['price']}")

    send_telegram("\n".join(lines))

# =========================================================
# GOOGLE NEWS
# =========================================================

def fetch_google_news():
    print("📰 News scan running", flush=True)

    for symbol in WATCHLIST[:5]:
        try:
            url  = f"https://news.google.com/rss/search?q={symbol}"
            feed = feedparser.parse(url)

            if not feed.entries:
                continue

            item = feed.entries[0]
            key  = f"news_{symbol}_{item.title}"

            if key in seen_alerts:
                continue

            seen_alerts.add(key)

            send_telegram(
                f"📰 NEWS ALERT\n\n"
                f"{symbol}\n\n"
                f"{item.title}\n\n"
                f"{item.link}"
            )

        except Exception:
            traceback.print_exc()

# =========================================================
# BSE ANNOUNCEMENTS
# FIX 3: replaces the empty NSE stub.
#
# BSE publishes a public RSS feed of corporate filings at:
#   https://www.bseindia.com/BSEDATA/ann/rss.aspx
# No login. No cookies. No 403s.
#
# We filter to only send alerts for symbols in our watchlist
# by checking if the company name contains the symbol string
# (BSE titles look like "RELIANCE IND LTD - Outcome of Board
# Meeting").  This is fuzzy but catches most cases.
# For tighter matching you can build a BSE scrip-code map.
# =========================================================

BSE_RSS_URL = "https://www.bseindia.com/BSEDATA/ann/rss.aspx"

def fetch_bse_announcements():
    print("📢 BSE announcement scan running", flush=True)

    try:
        feed = feedparser.parse(BSE_RSS_URL)

        if not feed.entries:
            print("⚠️  BSE RSS returned no entries", flush=True)
            return

        watchlist_upper = {s.upper() for s in WATCHLIST}

        for item in feed.entries[:30]:   # check latest 30
            title = item.get("title", "")
            link  = item.get("link", "")
            title_upper = title.upper()

            # Check if any watchlist symbol appears in the title
            matched = [
                sym for sym in watchlist_upper
                if sym in title_upper
            ]

            if not matched:
                continue

            key = f"bse_ann_{title}"
            if key in seen_alerts:
                continue

            seen_alerts.add(key)

            symbol_label = ", ".join(matched)

            send_telegram(
                f"📢 BSE ANNOUNCEMENT\n\n"
                f"Stock: {symbol_label}\n\n"
                f"{title}\n\n"
                f"{link}"
            )

    except Exception:
        print("⚠️  BSE announcement fetch failed", flush=True)
        traceback.print_exc()

# =========================================================
# MAIN
# =========================================================

def run():
    print("🚀 SCRIPT STARTED", flush=True)

    # FIX 1: prime NSE session BEFORE fetching any stocks
    prime_nse_session()

    all_data = fetch_all_data()

    if not all_data:
        send_telegram(
            "⚠️  WARNING: NSE fetch returned 0 stocks. "
            "Session priming may have failed."
        )

    process_price_alerts(all_data)
    process_day_high_alerts(all_data)
    fetch_google_news()

    # FIX 3: BSE replaces the empty NSE stub
    fetch_bse_announcements()

    save_json(list(seen_alerts), SEEN_FILE)

    print("✅ Cycle Complete", flush=True)

# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":
    try:
        run()
    except Exception:
        traceback.print_exc()
        send_telegram("❌ BOT CRASHED")
