# =========================================================
# ADVANCED NSE MARKET INTELLIGENCE TELEGRAM BOT
# =========================================================
#
# FEATURES
# ---------------------------------------------------------
# ✅ NSE Corporate Announcements (via NSE API)
# ✅ Google News (RSS, fresh <=12 hrs only)
# ✅ Price Spike Alerts (>3% move)
# ✅ Day High Breakout Detection
# ✅ REAL 5-Min Candle Volume Breakouts
# ✅ REAL 10-Min Candle Volume Breakouts
# ✅ REAL 15-Min Candle Volume Breakouts
# ✅ Daily Volume Spike Alerts (vs 20-day avg)
# ✅ Duplicate Alert Prevention
# ✅ Startup / Market Close Notifications
# ✅ Smart Sleep Until Market Open
# ✅ Weekend + Holiday Skip
# ✅ Safe JSON Writes
# ✅ Retry Handling
# ✅ End-of-Day Summary
# ✅ Keep-Alive Flask Server
#
# ACTIVE HOURS: 8:00 AM IST → 3:30 PM IST
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

# =========================================================
# KEEP-ALIVE FLASK SERVER (required for Railway)
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "NSE Bot Running ✅", 200

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000))), daemon=True).start()

# =========================================================
# ENV VARIABLES
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]

# =========================================================
# CONFIG
# =========================================================

CHECK_INTERVAL            = 60       # seconds between cycles
PRICE_ALERT_THRESHOLD     = 3.0      # % move to trigger price alert
DAY_HIGH_BUFFER_PCT       = 0.10     # within 0.10% of day high = breakout
VOLUME_SPIKE_MULTIPLIER   = 2.5      # daily volume vs 20-day avg
FIVE_MIN_SPIKE_MULTIPLIER = 3.0
TEN_MIN_SPIKE_MULTIPLIER  = 3.0
FIFTEEN_MIN_SPIKE_MULTIPLIER = 2.5
NEWS_MAX_AGE_HOURS        = 12       # ignore news older than this

IST          = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN  = (9, 15)
MARKET_CLOSE = (15, 30)

# Pre-market news scan window (8 AM onwards)
PRE_MARKET_OPEN = (8, 0)

# =========================================================
# NSE HOLIDAYS 2025-2026
# =========================================================

NSE_HOLIDAYS = {
    "2025-01-26", "2025-02-26", "2025-03-14",
    "2025-03-31", "2025-04-10", "2025-04-14",
    "2025-04-18", "2025-05-01", "2025-08-15",
    "2025-08-27", "2025-10-02", "2025-10-02",
    "2025-10-24", "2025-11-05", "2025-11-15",
    "2025-12-25",
    "2026-01-26", "2026-03-14", "2026-08-15",
    "2026-10-02",
}

# =========================================================
# WATCHLIST  (NSE symbols — no spaces allowed)
# =========================================================

WATCHLIST = sorted(list(set([
    "ADANIENT", "ADANIGREEN", "ADANIPORTS",
    "AKZOINDIA", "ATGL", "AFCONS", "ATL",
    "ANANTRAJ", "ANTHEM", "ARIHANTCAP",
    "ASIANPAINT", "BAJAJFINSV", "BEL",
    "BLUEDART", "BLS", "CASTROLIND",
    "CGPOWER", "CLEAN", "DBL",
    "EIDPARRY",          # was "EID PARRY"
    "FILATEX", "FORTIS", "GILLETTE",
    "GLOBUSSPR", "GSFC", "HDFCBANK",
    "HINDCOPPER", "HINDUNILVR", "HYUNDAI",
    "ITBEES", "ICICIAMC", "ICICIBANK",
    "IDBI", "IFCI", "INDUSTOWER",
    "CCAVENUE", "INFY", "IRB",
    "IRCTC", "JIOFIN", "JPASSOCIAT",
    "JSWENERGY", "KWIL", "LATENTVIEW",
    "LGEINDIA", "LOTUSDEV", "LLOYDSENGG",
    "LT", "MARUTI", "MAZDOCK",
    "MIRZAINT",
    "MENONPISTONS",      # was "MENON PISTON"
    "NATCOPHARM", "ONGC", "ORIENTCEM",
    "PIDILITIND", "POONAWALLA", "PVRINOX",
    "RTNPOWER", "RELIANCE", "RELINFRA",
    "RVNL",
    "SANGHIIND",         # was "SANGHI IND"
    "SBIN", "SRHHYPOLTD",
    "SUVIDHA",           # was "SUVIDHAA INFO"
    "SUPREMEIND", "SUZLON", "SWIGGY",
    "SYMPHONY", "TATATECH", "TITAN",
    "TRENT", "VBL",
])))

# =========================================================
# STATE FILES
# =========================================================

SEEN_FILE          = "seen_alerts.json"
PRICE_FILE         = "seen_price_alerts.json"
VOLUME_HISTORY_FILE= "volume_history.json"
CANDLE_5M_FILE     = "candle_5m.json"
CANDLE_10M_FILE    = "candle_10m.json"
CANDLE_15M_FILE    = "candle_15m.json"
DAY_HIGH_FILE      = "day_high_alerts.json"

# =========================================================
# SAFE JSON HELPERS
# =========================================================

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception:
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

seen_alerts       = set(load_json(SEEN_FILE, []))
seen_price_alerts = set(load_json(PRICE_FILE, []))
volume_history    = load_json(VOLUME_HISTORY_FILE, {})
candle_5m         = load_json(CANDLE_5M_FILE, {})
candle_10m        = load_json(CANDLE_10M_FILE, {})
candle_15m        = load_json(CANDLE_15M_FILE, {})
day_high_alerts   = set(load_json(DAY_HIGH_FILE, []))

# =========================================================
# DAILY STATS
# =========================================================

daily_stats = {
    "news": 0, "announcements": 0,
    "price": 0, "day_high": 0,
    "volume": 0, "5m": 0, "10m": 0, "15m": 0
}

# =========================================================
# TIME HELPERS
# =========================================================

def ist_now():
    return datetime.now(IST)

def is_holiday():
    return ist_now().strftime("%Y-%m-%d") in NSE_HOLIDAYS

def is_market_open():
    now = ist_now()
    if now.weekday() >= 5:
        return False
    if is_holiday():
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t < MARKET_CLOSE

def is_pre_market():
    """8:00 AM to 9:15 AM — scan news/announcements only"""
    now = ist_now()
    if now.weekday() >= 5:
        return False
    if is_holiday():
        return False
    t = (now.hour, now.minute)
    return PRE_MARKET_OPEN <= t < MARKET_OPEN

def seconds_until_next_market_open():
    now = ist_now()
    candidate = now.replace(
        hour=PRE_MARKET_OPEN[0],
        minute=PRE_MARKET_OPEN[1],
        second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5 or candidate.strftime("%Y-%m-%d") in NSE_HOLIDAYS:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()

def today_str():
    return ist_now().strftime("%Y-%m-%d")

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": message[:4000],
            "parse_mode": "HTML"
        }, timeout=20)
    except Exception as e:
        print("Telegram Error:", e)

# =========================================================
# NSE SESSION  (proper headers to avoid 401/403)
# =========================================================

NSE_SESSION = requests.Session()
NSE_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Origin": "https://www.nseindia.com",
})

def _nse_init_cookies():
    """Hit NSE homepage to get cookies before API calls."""
    try:
        NSE_SESSION.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
    except Exception as e:
        print("NSE cookie init failed:", e)

_nse_init_cookies()   # called once at startup

def nse_get(url, retries=3):
    for attempt in range(retries):
        try:
            resp = NSE_SESSION.get(url, timeout=15)
            if resp.status_code == 401:
                _nse_init_cookies()
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"NSE GET attempt {attempt+1} failed: {e}")
            time.sleep(2 * (attempt + 1))
    return None

# =========================================================
# FETCH PRICE DATA
# =========================================================

def fetch_price_data(symbol):
    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
    data = nse_get(url)
    if not data:
        return None
    try:
        p  = data.get("priceInfo", {})
        dp = data.get("securityWiseDP", {})
        intra = p.get("intraDayHighLow", {})
        wk52  = p.get("weekHighLow", {})
        return {
            "symbol":      symbol,
            "last_price":  p.get("lastPrice"),
            "open_price":  p.get("open"),
            "prev_close":  p.get("previousClose"),
            "change":      p.get("change"),
            "pchange":     p.get("pChange"),
            "day_high":    intra.get("max"),
            "day_low":     intra.get("min"),
            "wk52_high":   wk52.get("max"),
            "volume":      dp.get("quantityTraded"),
            "delivery_qty":dp.get("deliveryQuantity"),
            "delivery_pct":dp.get("deliveryToTradedQuantity"),
        }
    except Exception as e:
        print(f"Parse error [{symbol}]: {e}")
        return None

def fetch_all_stock_data():
    all_data = {}
    for symbol in WATCHLIST:
        try:
            d = fetch_price_data(symbol)
            if d:
                all_data[symbol] = d
            time.sleep(0.3)      # polite delay
        except Exception as e:
            print(f"Fetch Error [{symbol}]:", e)
    return all_data

# =========================================================
# NSE CORPORATE ANNOUNCEMENTS
# =========================================================

def fetch_nse_announcements():
    """Fetch recent corporate announcements for watchlist stocks."""
    url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
    data = nse_get(url)
    if not data or not isinstance(data, list):
        return

    cutoff = ist_now() - timedelta(hours=NEWS_MAX_AGE_HOURS)

    for item in data:
        try:
            symbol = item.get("symbol", "")
            if symbol not in WATCHLIST:
                continue

            subject = item.get("desc", item.get("subject", ""))
            an_dt_str = item.get("an_dt", "")

            # Parse announcement datetime
            try:
                an_dt = datetime.strptime(an_dt_str[:16], "%d-%b-%Y %H:%M")
                an_dt = an_dt.replace(tzinfo=IST)
            except Exception:
                continue

            if an_dt < cutoff:
                continue

            unique_key = f"ANN-{symbol}-{an_dt_str}-{subject[:40]}"
            if unique_key in seen_alerts:
                continue

            seen_alerts.add(unique_key)
            safe_json_dump(list(seen_alerts), SEEN_FILE)

            daily_stats["announcements"] += 1

            send_telegram(
                f"📢 <b>NSE ANNOUNCEMENT</b>\n\n"
                f"<b>Stock:</b> {symbol}\n"
                f"<b>Time:</b> {an_dt_str}\n"
                f"<b>Subject:</b> {subject}"
            )

        except Exception as e:
            print("Announcement Error:", e)

# =========================================================
# GOOGLE NEWS RSS
# =========================================================

def fetch_google_news():
    """Scan Google News RSS for each watchlist stock."""
    cutoff = ist_now() - timedelta(hours=NEWS_MAX_AGE_HOURS)

    for symbol in WATCHLIST:
        try:
            query = f"{symbol} NSE stock India"
            rss_url = (
                f"https://news.google.com/rss/search?"
                f"q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:5]:
                title = entry.get("title", "")
                link  = entry.get("link", "")
                pub   = entry.get("published", "")

                try:
                    pub_dt = parsedate_to_datetime(pub)
                    pub_dt = pub_dt.astimezone(IST)
                except Exception:
                    continue

                if pub_dt < cutoff:
                    continue

                unique_key = f"NEWS-{symbol}-{link[-60:]}"
                if unique_key in seen_alerts:
                    continue

                seen_alerts.add(unique_key)
                safe_json_dump(list(seen_alerts), SEEN_FILE)

                daily_stats["news"] += 1

                age_mins = int((ist_now() - pub_dt).total_seconds() / 60)

                send_telegram(
                    f"📰 <b>NEWS ALERT</b>\n\n"
                    f"<b>Stock:</b> {symbol}\n"
                    f"<b>Headline:</b> {title}\n"
                    f"<b>Age:</b> {age_mins} mins ago\n"
                    f"<b>Link:</b> {link}"
                )

            time.sleep(0.5)

        except Exception as e:
            print(f"News Error [{symbol}]:", e)

# =========================================================
# PRICE ALERTS  (>3% move)
# =========================================================

def process_price_alerts(all_data):
    today = today_str()
    for symbol, data in all_data.items():
        try:
            pchange = data.get("pchange")
            if pchange is None:
                continue
            if abs(pchange) < PRICE_ALERT_THRESHOLD:
                continue

            direction = "UP" if pchange > 0 else "DOWN"
            unique_key = f"{today}-PRICE-{symbol}-{direction}"
            if unique_key in seen_price_alerts:
                continue

            seen_price_alerts.add(unique_key)
            safe_json_dump(list(seen_price_alerts), PRICE_FILE)
            daily_stats["price"] += 1

            arrow = "📈" if pchange > 0 else "📉"
            send_telegram(
                f"{arrow} <b>PRICE ALERT</b>\n\n"
                f"<b>Stock:</b> {symbol}\n"
                f"<b>Change:</b> {pchange:+.2f}%\n"
                f"<b>Price:</b> ₹{data['last_price']}\n"
                f"<b>Open:</b> ₹{data['open_price']}\n"
                f"<b>Day High:</b> ₹{data['day_high']}\n"
                f"<b>Day Low:</b> ₹{data['day_low']}"
            )
        except Exception as e:
            print("Price Alert Error:", e)

# =========================================================
# DAY HIGH BREAKOUT
# =========================================================

def process_day_high_breakouts(all_data):
    """Alert when price is at or very close to intraday high (momentum breakout)."""
    today = today_str()
    for symbol, data in all_data.items():
        try:
            price    = data.get("last_price")
            day_high = data.get("day_high")
            pchange  = data.get("pchange")

            if not price or not day_high or not pchange:
                continue
            if pchange < 1.0:
                continue  # Only bullish breakouts

            # Price within DAY_HIGH_BUFFER_PCT% of day high
            gap_pct = abs(day_high - price) / day_high * 100
            if gap_pct > DAY_HIGH_BUFFER_PCT:
                continue

            unique_key = f"{today}-DAYHIGH-{symbol}-{int(day_high)}"
            if unique_key in day_high_alerts:
                continue

            day_high_alerts.add(unique_key)
            safe_json_dump(list(day_high_alerts), DAY_HIGH_FILE)
            daily_stats["day_high"] += 1

            # Check 52-week high too
            wk52 = data.get("wk52_high")
            wk52_note = ""
            if wk52 and price >= wk52 * 0.99:
                wk52_note = f"\n🏆 <b>Near 52-Week High:</b> ₹{wk52}"

            send_telegram(
                f"🚀 <b>DAY HIGH BREAKOUT</b>\n\n"
                f"<b>Stock:</b> {symbol}\n"
                f"<b>Price:</b> ₹{price}\n"
                f"<b>Day High:</b> ₹{day_high}\n"
                f"<b>Change:</b> {pchange:+.2f}%"
                f"{wk52_note}\n"
                f"<b>Time:</b> {ist_now().strftime('%H:%M:%S')}"
            )
        except Exception as e:
            print("Day High Error:", e)

# =========================================================
# DAILY VOLUME SPIKE (vs historical avg)
# =========================================================

def process_daily_volume_spikes(all_data):
    """Compare today's traded volume to the stored 20-day average."""
    today = today_str()
    for symbol, data in all_data.items():
        try:
            vol = data.get("volume")
            if not vol:
                continue

            history = volume_history.get(symbol, [])

            if len(history) >= 5:
                avg_vol = sum(history) / len(history)
                if avg_vol > 0:
                    ratio = vol / avg_vol
                    if ratio >= VOLUME_SPIKE_MULTIPLIER:
                        unique_key = f"{today}-DVOL-{symbol}"
                        if unique_key not in seen_price_alerts:
                            seen_price_alerts.add(unique_key)
                            safe_json_dump(list(seen_price_alerts), PRICE_FILE)
                            daily_stats["volume"] += 1
                            pchange = data.get("pchange", 0) or 0
                            send_telegram(
                                f"📊 <b>DAILY VOLUME SPIKE</b>\n\n"
                                f"<b>Stock:</b> {symbol}\n"
                                f"<b>Today Volume:</b> {int(vol):,}\n"
                                f"<b>Avg Volume:</b> {int(avg_vol):,}\n"
                                f"<b>Spike:</b> {ratio:.1f}x\n"
                                f"<b>Price Change:</b> {pchange:+.2f}%\n"
                                f"<b>Price:</b> ₹{data['last_price']}"
                            )

        except Exception as e:
            print("Daily Volume Error:", e)

def update_volume_history(all_data):
    """Save EOD volume to rolling 20-day history."""
    for symbol, data in all_data.items():
        vol = data.get("volume")
        if not vol:
            continue
        hist = volume_history.get(symbol, [])
        hist.append(vol)
        volume_history[symbol] = hist[-20:]   # keep last 20 days
    safe_json_dump(volume_history, VOLUME_HISTORY_FILE)

# =========================================================
# REAL CANDLE VOLUME BREAKOUT ENGINE
# =========================================================

def process_real_candle_volume_breakout(
    all_data, candle_store, filename,
    candle_minutes, spike_multiplier, stats_key
):
    now = ist_now()
    rounded_minute = (now.minute // candle_minutes) * candle_minutes
    current_candle = now.replace(minute=rounded_minute, second=0, microsecond=0)
    candle_key = current_candle.strftime("%Y-%m-%d %H:%M")

    for symbol, data in all_data.items():
        try:
            total_volume = data.get("volume")
            if not total_volume:
                continue

            if symbol not in candle_store:
                candle_store[symbol] = {
                    "candles": {},
                    "last_total_volume": total_volume
                }

            stock_data = candle_store[symbol]
            candles    = stock_data["candles"]

            if candle_key not in candles:
                previous_total = stock_data.get("last_total_volume", total_volume)
                candle_volume  = max(total_volume - previous_total, 0)
                candles[candle_key] = candle_volume
                stock_data["last_total_volume"] = total_volume
            else:
                previous_total = stock_data.get("last_total_volume", total_volume)
                incremental    = total_volume - previous_total
                if incremental > 0:
                    candles[candle_key] += incremental
                stock_data["last_total_volume"] = total_volume

            # Prune to last 50 candles
            sorted_keys = sorted(candles.keys())
            for old_key in sorted_keys[:-50]:
                del candles[old_key]

            candle_values = list(candles.values())
            if len(candle_values) < 6:
                continue

            current_candle_volume = candle_values[-1]
            previous_candles      = candle_values[:-1]
            avg_volume            = sum(previous_candles) / len(previous_candles)

            if avg_volume <= 0:
                continue

            spike_ratio = current_candle_volume / avg_volume
            if spike_ratio < spike_multiplier:
                continue

            pchange = data.get("pchange", 0) or 0
            if abs(pchange) < 0.5:
                continue   # skip noise — require at least small price move

            unique_key = f"{candle_minutes}M-{symbol}-{candle_key}"
            if unique_key in seen_price_alerts:
                continue

            seen_price_alerts.add(unique_key)
            safe_json_dump(list(seen_price_alerts), PRICE_FILE)
            daily_stats[stats_key] += 1

            direction = "📈" if pchange > 0 else "📉"
            send_telegram(
                f"{direction} <b>REAL {candle_minutes}-MIN VOLUME BREAKOUT</b>\n\n"
                f"<b>Stock:</b> {symbol}\n"
                f"<b>Candle Volume:</b> {int(current_candle_volume):,}\n"
                f"<b>Avg Candle Vol:</b> {int(avg_volume):,}\n"
                f"<b>Spike:</b> {spike_ratio:.1f}x\n"
                f"<b>Price Change:</b> {pchange:+.2f}%\n"
                f"<b>Price:</b> ₹{data['last_price']}\n"
                f"<b>Candle:</b> {candle_key}"
            )

        except Exception as e:
            print(f"{candle_minutes}m Candle Error:", e)

    safe_json_dump(candle_store, filename)

# =========================================================
# END-OF-DAY SUMMARY
# =========================================================

eod_sent = False

def maybe_send_eod_summary(all_data):
    global eod_sent
    now = ist_now()

    if eod_sent:
        return
    if not (now.hour == 15 and now.minute >= 30):
        return

    eod_sent = True

    # Top movers
    movers = sorted(
        [(s, d["pchange"]) for s, d in all_data.items()
         if d.get("pchange") is not None],
        key=lambda x: x[1], reverse=True
    )

    top_gainers = movers[:5]
    top_losers  = movers[-5:][::-1]

    gainers_txt = "\n".join(
        [f"  {s}: {p:+.2f}%" for s, p in top_gainers]
    ) or "None"
    losers_txt  = "\n".join(
        [f"  {s}: {p:+.2f}%" for s, p in top_losers]
    ) or "None"

    send_telegram(
        f"📋 <b>END-OF-DAY SUMMARY</b>\n"
        f"<b>Date:</b> {today_str()}\n\n"
        f"<b>Alerts Sent Today:</b>\n"
        f"  📰 News: {daily_stats['news']}\n"
        f"  📢 Announcements: {daily_stats['announcements']}\n"
        f"  📈 Price (&gt;3%): {daily_stats['price']}\n"
        f"  🚀 Day High Breakout: {daily_stats['day_high']}\n"
        f"  📊 Daily Volume Spike: {daily_stats['volume']}\n"
        f"  ⚡ 5-Min Vol Breakout: {daily_stats['5m']}\n"
        f"  ⚡ 10-Min Vol Breakout: {daily_stats['10m']}\n"
        f"  ⚡ 15-Min Vol Breakout: {daily_stats['15m']}\n\n"
        f"<b>Top Gainers:</b>\n{gainers_txt}\n\n"
        f"<b>Top Losers:</b>\n{losers_txt}"
    )

    # Save volume for tomorrow's daily spike detection
    update_volume_history(all_data)

    # Reset daily stats
    for k in daily_stats:
        daily_stats[k] = 0

    print("EOD Summary sent.")

# =========================================================
# STARTUP MESSAGE
# =========================================================

send_telegram(
    f"✅ <b>NSE BOT STARTED</b>\n\n"
    f"<b>Time:</b> {ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}\n"
    f"<b>Stocks Watching:</b> {len(WATCHLIST)}\n"
    f"<b>Features Active:</b>\n"
    f"  📰 News + NSE Announcements\n"
    f"  📈 Price Alerts (&gt;{PRICE_ALERT_THRESHOLD}%)\n"
    f"  🚀 Day High Breakout\n"
    f"  📊 Daily Volume Spike ({VOLUME_SPIKE_MULTIPLIER}x avg)\n"
    f"  ⚡ 5/10/15-Min Candle Volume Breakouts"
)

# =========================================================
# MAIN LOOP
# =========================================================

print("BOT STARTED —", ist_now().strftime("%Y-%m-%d %H:%M:%S"))

news_last_scanned = 0   # epoch seconds

while True:
    try:
        now = ist_now()

        # ── Outside active window → sleep smartly ──────────
        if not is_market_open() and not is_pre_market():
            secs = seconds_until_next_market_open()
            hrs  = int(secs // 3600)
            mins = int((secs % 3600) // 60)
            print(f"Market Closed. Sleeping {hrs}h {mins}m")
            time.sleep(min(secs, 1800))
            continue

        print("\nNEW CYCLE:", now.strftime("%Y-%m-%d %H:%M:%S"))

        # ── News & Announcements (every 10 mins) ───────────
        if time.time() - news_last_scanned >= 600:
            print("  → Scanning announcements & news...")
            fetch_nse_announcements()
            fetch_google_news()
            news_last_scanned = time.time()

        # ── Price / Volume checks only during market hours ─
        if is_market_open():
            print("  → Fetching stock data...")
            all_data = fetch_all_stock_data()

            if all_data:
                process_price_alerts(all_data)
                process_day_high_breakouts(all_data)
                process_daily_volume_spikes(all_data)

                process_real_candle_volume_breakout(
                    all_data=all_data,
                    candle_store=candle_5m,
                    filename=CANDLE_5M_FILE,
                    candle_minutes=5,
                    spike_multiplier=FIVE_MIN_SPIKE_MULTIPLIER,
                    stats_key="5m"
                )
                process_real_candle_volume_breakout(
                    all_data=all_data,
                    candle_store=candle_10m,
                    filename=CANDLE_10M_FILE,
                    candle_minutes=10,
                    spike_multiplier=TEN_MIN_SPIKE_MULTIPLIER,
                    stats_key="10m"
                )
                process_real_candle_volume_breakout(
                    all_data=all_data,
                    candle_store=candle_15m,
                    filename=CANDLE_15M_FILE,
                    candle_minutes=15,
                    spike_multiplier=FIFTEEN_MIN_SPIKE_MULTIPLIER,
                    stats_key="15m"
                )

                maybe_send_eod_summary(all_data)

    except Exception as e:
        err_msg = (
            f"❌ <b>BOT ERROR</b>\n\n"
            f"{str(e)}\n\n"
            f"<b>Time:</b> {ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}"
        )
        print(err_msg)
        send_telegram(err_msg)

    time.sleep(CHECK_INTERVAL)
