# =========================================================
# ADVANCED NSE MARKET INTELLIGENCE TELEGRAM BOT
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

threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000))), 
    daemon=True
).start()

# =========================================================
# ENV VARIABLES
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID   = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")

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
    "2025-08-27", "2025-10-02", "2025-10-24", 
    "2025-11-05", "2025-11-15", "2025-12-25",
    "2026-01-26", "2026-03-14", "2026-08-15",
    "2026-10-02",
}

# =========================================================
# WATCHLIST  (NSE symbols — no spaces allowed)
# =========================================================

WATCHLIST = sorted(list(set([
    "ADANIENT", "ADANIGREEN", "ADANIPORTS", "AKZOINDIA", "ATGL", "AFCONS", "ATL",
    "ANANTRAJ", "ANTHEM", "ARIHANTCAP", "ASIANPAINT", "BAJAJFINSV", "BEL",
    "BLUEDART", "BLS", "CASTROLIND", "CGPOWER", "CLEAN", "DBL", "EIDPARRY",
    "FILATEX", "FORTIS", "GILLETTE", "GLOBUSSPR", "GSFC", "HDFCBANK",
    "HINDCOPPER", "HINDUNILVR", "HYUNDAI", "ITBEES", "ICICIAMC", "ICICIBANK",
    "IDBI", "IFCI", "INDUSTOWER", "CCAVENUE", "INFY", "IRB", "IRCTC", "JIOFIN", 
    "JPASSOCIAT", "JSWENERGY", "KWIL", "LATENTVIEW", "LGEINDIA", "LOTUSDEV", 
    "LLOYDSENGG", "LT", "MARUTI", "MAZDOCK", "MIRZAINT", "MENONPISTONS", 
    "NATCOPHARM", "ONGC", "ORIENTCEM", "PIDILITIND", "POONAWALLA", "PVRINOX",
    "RTNPOWER", "RELIANCE", "RELINFRA", "RVNL", "SANGHIIND", "SBIN", 
    "SRHHYPOLTD", "SUVIDHA", "SUPREMEIND", "SUZLON", "SWIGGY", "SYMPHONY", 
    "TATATECH", "TITAN", "TRENT", "VBL"
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
    "news": 0, "announcements": 0, "price": 0, "day_high": 0,
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
    if now.weekday() >= 5 or is_holiday():
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t < MARKET_CLOSE

def is_pre_market():
    now = ist_now()
    if now.weekday() >= 5 or is_holiday():
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
    return max(0, (candidate - now).total_seconds())

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
# NSE SESSION 
# =========================================================

NSE_SESSION = requests.Session()
NSE_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
})

def _nse_init_cookies():
    try:
        NSE_SESSION.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
    except Exception as e:
        print("NSE cookie init failed:", e)

_nse_init_cookies()

def nse_get(url, retries=3):
    for attempt in range(retries):
        try:
            resp = NSE_SESSION.get(url, timeout=15)
            if resp.status_code in [401, 403]:
                _nse_init_cookies()
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            time.sleep(2 * (attempt + 1))
    return None

# =========================================================
# FETCH PRICE DATA
# =========================================================

def fetch_price_data(symbol):
    url = f"https://www.nseindia.com/api/quote-equity?symbol={requests.utils.quote(symbol)}"
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
            "volume":      dp.get("quantityTraded", p.get("totalTradedVolume")),
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
            time.sleep(0.5)  # Slightly longer delay to avoid IP ban
        except Exception as e:
            print(f"Fetch Error [{symbol}]:", e)
    return all_data

# =========================================================
# CORPORATE ANNOUNCEMENTS & NEWS (Omitted for brevity, using original logic)
# =========================================================
def fetch_nse_announcements():
    url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
    data = nse_get(url)
    if not data or not isinstance(data, list):
        return

    cutoff = ist_now() - timedelta(hours=NEWS_MAX_AGE_HOURS)
    for item in data:
        try:
            symbol = item.get("symbol", "")
            if symbol not in WATCHLIST: continue
            subject = item.get("desc", item.get("subject", ""))
            an_dt_str = item.get("an_dt", "")
            try:
                an_dt = datetime.strptime(an_dt_str[:16], "%d-%b-%Y %H:%M").replace(tzinfo=IST)
            except:
                continue
            if an_dt < cutoff: continue
            
            unique_key = f"ANN-{symbol}-{an_dt_str}-{subject[:40]}"
            if unique_key in seen_alerts: continue
            
            seen_alerts.add(unique_key)
            safe_json_dump(list(seen_alerts), SEEN_FILE)
            daily_stats["announcements"] += 1

            send_telegram(f"📢 <b>NSE ANNOUNCEMENT</b>\n\n<b>Stock:</b> {symbol}\n<b>Time:</b> {an_dt_str}\n<b>Subject:</b> {subject}")
        except Exception as e:
            pass

def fetch_google_news():
    cutoff = ist_now() - timedelta(hours=NEWS_MAX_AGE_HOURS)
    for symbol in WATCHLIST:
        try:
            query = f"{symbol} NSE stock India"
            rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            feed = feedparser.parse(rss_url)
            for entry in feed.entries[:3]:
                title, link, pub = entry.get("title", ""), entry.get("link", ""), entry.get("published", "")
                try:
                    pub_dt = parsedate_to_datetime(pub).astimezone(IST)
                except:
                    continue
                if pub_dt < cutoff: continue
                
                unique_key = f"NEWS-{symbol}-{link[-60:]}"
                if unique_key in seen_alerts: continue
                
                seen_alerts.add(unique_key)
                safe_json_dump(list(seen_alerts), SEEN_FILE)
                daily_stats["news"] += 1
                age_mins = int((ist_now() - pub_dt).total_seconds() / 60)
                
                send_telegram(f"📰 <b>NEWS ALERT</b>\n\n<b>Stock:</b> {symbol}\n<b>Headline:</b> {title}\n<b>Age:</b> {age_mins} mins ago\n<b>Link:</b> {link}")
            time.sleep(0.5)
        except Exception:
            pass

# =========================================================
# ALERTS LOGIC (Price, Day High, Volume)
# =========================================================
def process_price_alerts(all_data):
    today = today_str()
    for symbol, data in all_data.items():
        pchange = data.get("pchange")
        if pchange is None or abs(pchange) < PRICE_ALERT_THRESHOLD: continue

        direction = "UP" if pchange > 0 else "DOWN"
        unique_key = f"{today}-PRICE-{symbol}-{direction}"
        if unique_key in seen_price_alerts: continue

        seen_price_alerts.add(unique_key)
        safe_json_dump(list(seen_price_alerts), PRICE_FILE)
        daily_stats["price"] += 1
        arrow = "📈" if pchange > 0 else "📉"
        send_telegram(f"{arrow} <b>PRICE ALERT</b>\n\n<b>Stock:</b> {symbol}\n<b>Change:</b> {pchange:+.2f}%\n<b>Price:</b> ₹{data['last_price']}\n<b>Open:</b> ₹{data['open_price']}\n<b>Day High:</b> ₹{data['day_high']}\n<b>Day Low:</b> ₹{data['day_low']}")

def process_day_high_breakouts(all_data):
    today = today_str()
    for symbol, data in all_data.items():
        price, day_high, pchange = data.get("last_price"), data.get("day_high"), data.get("pchange")
        if not price or not day_high or not pchange or pchange < 1.0: continue

        gap_pct = abs(day_high - price) / day_high * 100
        if gap_pct > DAY_HIGH_BUFFER_PCT: continue

        unique_key = f"{today}-DAYHIGH-{symbol}-{int(day_high)}"
        if unique_key in day_high_alerts: continue

        day_high_alerts.add(unique_key)
        safe_json_dump(list(day_high_alerts), DAY_HIGH_FILE)
        daily_stats["day_high"] += 1
        wk52, wk52_note = data.get("wk52_high"), ""
        if wk52 and price >= wk52 * 0.99: wk52_note = f"\n🏆 <b>Near 52-Week High:</b> ₹{wk52}"

        send_telegram(f"🚀 <b>DAY HIGH BREAKOUT</b>\n\n<b>Stock:</b> {symbol}\n<b>Price:</b> ₹{price}\n<b>Day High:</b> ₹{day_high}\n<b>Change:</b> {pchange:+.2f}%{wk52_note}\n<b>Time:</b> {ist_now().strftime('%H:%M:%S')}")

def process_daily_volume_spikes(all_data):
    today = today_str()
    for symbol, data in all_data.items():
        vol = data.get("volume")
        if not vol: continue
        history = volume_history.get(symbol, [])
        if len(history) >= 5:
            avg_vol = sum(history) / len(history)
            if avg_vol > 0 and (vol / avg_vol) >= VOLUME_SPIKE_MULTIPLIER:
                unique_key = f"{today}-DVOL-{symbol}"
                if unique_key not in seen_price_alerts:
                    seen_price_alerts.add(unique_key)
                    safe_json_dump(list(seen_price_alerts), PRICE_FILE)
                    daily_stats["volume"] += 1
                    pchange = data.get("pchange", 0) or 0
                    send_telegram(f"📊 <b>DAILY VOLUME SPIKE</b>\n\n<b>Stock:</b> {symbol}\n<b>Today Volume:</b> {int(vol):,}\n<b>Avg Volume:</b> {int(avg_vol):,}\n<b>Spike:</b> {(vol/avg_vol):.1f}x\n<b>Price Change:</b> {pchange:+.2f}%\n<b>Price:</b> ₹{data['last_price']}")

def update_volume_history(all_data):
    for symbol, data in all_data.items():
        vol = data.get("volume")
        if not vol: continue
        hist = volume_history.get(symbol, [])
        hist.append(vol)
        volume_history[symbol] = hist[-20:]
    safe_json_dump(volume_history, VOLUME_HISTORY_FILE)

def process_real_candle_volume_breakout(all_data, candle_store, filename, candle_minutes, spike_multiplier, stats_key):
    now = ist_now()
    rounded_minute = (now.minute // candle_minutes) * candle_minutes
    current_candle = now.replace(minute=rounded_minute, second=0, microsecond=0)
    candle_key = current_candle.strftime("%Y-%m-%d %H:%M")

    for symbol, data in all_data.items():
        total_volume = data.get("volume")
        if not total_volume: continue

        if symbol not in candle_store:
            candle_store[symbol] = {"candles": {}, "last_total_volume": total_volume}

        stock_data = candle_store[symbol]
        candles = stock_data["candles"]

        if candle_key not in candles:
            previous_total = stock_data.get("last_total_volume", total_volume)
            candles[candle_key] = max(total_volume - previous_total, 0)
        else:
            incremental = total_volume - stock_data.get("last_total_volume", total_volume)
            if incremental > 0: candles[candle_key] += incremental

        stock_data["last_total_volume"] = total_volume
        sorted_keys = sorted(candles.keys())
        for old_key in sorted_keys[:-50]: del candles[old_key]

        candle_values = list(candles.values())
        if len(candle_values) < 6: continue

        current_candle_volume = candle_values[-1]
        previous_candles = candle_values[:-1]
        avg_volume = sum(previous_candles) / len(previous_candles)

        if avg_volume <= 0: continue
        spike_ratio = current_candle_volume / avg_volume
        pchange = data.get("pchange", 0) or 0

        if spike_ratio >= spike_multiplier and abs(pchange) >= 0.5:
            unique_key = f"{candle_minutes}M-{symbol}-{candle_key}"
            if unique_key not in seen_price_alerts:
                seen_price_alerts.add(unique_key)
                safe_json_dump(list(seen_price_alerts), PRICE_FILE)
                daily_stats[stats_key] += 1
                direction = "📈" if pchange > 0 else "📉"
                send_telegram(f"{direction} <b>REAL {candle_minutes}-MIN VOLUME BREAKOUT</b>\n\n<b>Stock:</b> {symbol}\n<b>Candle Volume:</b> {int(current_candle_volume):,}\n<b>Avg Candle Vol:</b> {int(avg_volume):,}\n<b>Spike:</b> {spike_ratio:.1f}x\n<b>Price Change:</b> {pchange:+.2f}%\n<b>Price:</b> ₹{data['last_price']}\n<b>Candle:</b> {candle_key}")

    safe_json_dump(candle_store, filename)

# =========================================================
# END-OF-DAY SUMMARY
# =========================================================

eod_sent_date = ""

def maybe_send_eod_summary(all_data):
    global eod_sent_date
    now = ist_now()
    today = today_str()

    if eod_sent_date == today:
        return
    if not (now.hour >= 15 and now.minute >= 30):
        return

    eod_sent_date = today

    movers = sorted([(s, d["pchange"]) for s, d in all_data.items() if d.get("pchange") is not None], key=lambda x: x[1], reverse=True)
    top_gainers = movers[:5]
    top_losers  = movers[-5:][::-1]

    gainers_txt = "\n".join([f"  {s}: {p:+.2f}%" for s, p in top_gainers]) or "None"
    losers_txt  = "\n".join([f"  {s}: {p:+.2f}%" for s, p in top_losers]) or "None"

    send_telegram(f"📋 <b>END-OF-DAY SUMMARY</b>\n<b>Date:</b> {today}\n\n<b>Alerts Sent Today:</b>\n  📰 News: {daily_stats['news']}\n  📢 Announcements: {daily_stats['announcements']}\n  📈 Price: {daily_stats['price']}\n  🚀 Day High: {daily_stats['day_high']}\n  📊 Daily Vol: {daily_stats['volume']}\n  ⚡ 5-Min Vol: {daily_stats['5m']}\n  ⚡ 10-Min Vol: {daily_stats['10m']}\n  ⚡ 15-Min Vol: {daily_stats['15m']}\n\n<b>Top Gainers:</b>\n{gainers_txt}\n\n<b>Top Losers:</b>\n{losers_txt}")
    
    update_volume_history(all_data)
    for k in daily_stats: daily_stats[k] = 0

# =========================================================
# STARTUP MESSAGE
# =========================================================

send_telegram(f"✅ <b>NSE BOT STARTED</b>\n\n<b>Time:</b> {ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}\n<b>Stocks Watching:</b> {len(WATCHLIST)}")

# =========================================================
# MAIN LOOP
# =========================================================

print("BOT STARTED —", ist_now().strftime("%Y-%m-%d %H:%M:%S"))
news_last_scanned = 0
block_notified = False

while True:
    try:
        now = ist_now()

        if not is_market_open() and not is_pre_market():
            secs = seconds_until_next_market_open()
            hrs, mins = int(secs // 3600), int((secs % 3600) // 60)
            print(f"Market Closed. Sleeping {hrs}h {mins}m")
            time.sleep(min(secs, 1800))
            continue

        print("\nNEW CYCLE:", now.strftime("%Y-%m-%d %H:%M:%S"))

        if time.time() - news_last_scanned >= 600:
            print("  -> Scanning announcements & news...")
            fetch_nse_announcements()
            fetch_google_news()
            news_last_scanned = time.time()

        if is_market_open():
            print("  -> Fetching stock data...")
            all_data = fetch_all_stock_data()

            if not all_data:
                if not block_notified:
                    send_telegram("⚠️ <b>DEBUG:</b> Failed to fetch stock data. The NSE API might be blocking your IP.")
                    block_notified = True
                print("No data fetched. Skipping alerts cycle.")
            else:
                block_notified = False  # Reset if successful
                process_price_alerts(all_data)
                process_day_high_breakouts(all_data)
                process_daily_volume_spikes(all_data)

                process_real_candle_volume_breakout(all_data, candle_5m, CANDLE_5M_FILE, 5, FIVE_MIN_SPIKE_MULTIPLIER, "5m")
                process_real_candle_volume_breakout(all_data, candle_10m, CANDLE_10M_FILE, 10, TEN_MIN_SPIKE_MULTIPLIER, "10m")
                process_real_candle_volume_breakout(all_data, candle_15m, CANDLE_15M_FILE, 15, FIFTEEN_MIN_SPIKE_MULTIPLIER, "15m")

                maybe_send_eod_summary(all_data)

    except Exception as e:
        send_telegram(f"❌ <b>BOT ERROR</b>\n\n{str(e)}\n\n<b>Time:</b> {ist_now().strftime('%Y-%m-%d %H:%M:%S IST')}")

    time.sleep(CHECK_INTERVAL)
