# =========================================================
# NSE MOMENTUM ALERT BOT — v4 REWRITE
# =========================================================
#
# TRIGGERS (each fires its own detailed Telegram card)
# ---------------------------------------------------------
#
# 1. PRICE MOVE ALERT
#    Price moves ≥ 3% from day open (upside or downside)
#    - Shows: move %, current price, open, high, low, context
#
# 2. DAY HIGH BREAKOUT
#    Current price ≥ today's running high (new intraday high)
#    - Additional check: high must be meaningfully above open (> 0.5%)
#      to avoid flat-market false triggers
#    - Shows: how far above open, breakout strength
#
# 3. VOLUME SURGE — MULTI-TIMEFRAME LOGIC (REALISTIC)
#    The old 3-candle comparison was too noisy. Replaced with:
#
#    a) CANDLE-LEVEL SURGE
#       Current 5m candle volume > 2.5x average of last 20 candles
#       (detects single spike — e.g. large block trade or news hit)
#
#    b) MOMENTUM BUILDUP (multi-candle)
#       Rolling sum of last 3 candles > 2x rolling sum of 3 candles
#       before that (i.e. 15-min block vs previous 15-min block)
#       AND price is moving in the direction of the volume
#       (volume without price = distribution, not breakout)
#
#    c) 30-MIN BLOCK SURGE
#       Sum of last 6 candles (30 min) > 1.8x avg 30-min sum
#       computed over the day so far
#       Catches slower institutional accumulation
#
#    Only (b) or (c) in combination with a price move > 0.5%
#    are sent as alerts — avoids spam from random spikes.
#
# 4. NSE NOTICES / NEWS ALERT
#    Polls NSE API for corporate announcements on watchlist symbols
#    Every run checks: board meetings, results, buybacks, splits,
#    dividends, mergers, block deals, bulk deals, insider trading
#    New notices since last run are sent immediately.
#
# ALERT DEDUPLICATION
#    Each alert type+symbol+day is sent only ONCE per session.
#    State stored in seen_alerts.json (reset daily).
#
# =========================================================

import os
import sys
import json
import time
import random
import logging
import traceback
import requests
import pandas as pd
import yfinance as yf

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================================================
# LOGGER
# =========================================================

print("🚀 FILE STARTED", flush=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger()


def log(msg):
    print(msg, flush=True)
    logger.info(msg)


log("🚀 SCRIPT STARTED")

# =========================================================
# ENV
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID   = os.environ.get("CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    log("❌ BOT_TOKEN or CHAT_ID missing")
    raise SystemExit(1)

# =========================================================
# CONFIG
# =========================================================

PRICE_MOVE_PCT       = 3.0    # % from day open to trigger price alert
DAY_HIGH_MIN_MOVE    = 0.5    # % above open — ignores flat market day highs
VOL_SPIKE_MULT       = 2.5    # single candle spike: N x 20-candle avg
VOL_BLOCK_15M_MULT   = 2.0    # 15-min block vs previous 15-min block
VOL_BLOCK_30M_MULT   = 1.8    # 30-min block vs day avg 30-min block
VOL_PRICE_CONFIRM    = 0.5    # minimum price move % to confirm volume signal
MAX_WORKERS          = 2      # keep low to avoid Yahoo rate limits

IST         = timezone(timedelta(hours=5, minutes=30))
ALERT_START = (9, 15)
ALERT_END   = (15, 30)

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.nseindia.com/",
    "Connection":      "keep-alive",
}

# =========================================================
# WATCHLIST  — DO NOT MODIFY
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
])))

log(f"📊 Watchlist: {len(WATCHLIST)} stocks")

# =========================================================
# STATE FILES
# =========================================================

SEEN_FILE      = "seen_alerts.json"
NSE_NOTICE_FILE = "seen_nse_notices.json"


def load_json(filename, default):
    try:
        if not os.path.exists(filename):
            return default
        with open(filename, "r") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(data, filename):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        traceback.print_exc()


def today_str():
    return datetime.now(IST).strftime("%Y-%m-%d")


def load_seen_alerts():
    """
    Load seen_alerts. Auto-reset daily so alerts re-fire next day.
    Structure: { "date": "YYYY-MM-DD", "keys": [...] }
    """
    raw = load_json(SEEN_FILE, {})
    if raw.get("date") != today_str():
        return set()
    return set(raw.get("keys", []))


def save_seen_alerts(seen: set):
    save_json({"date": today_str(), "keys": list(seen)}, SEEN_FILE)


seen_alerts = load_seen_alerts()

# NSE notice cache: set of notice identifiers already sent
seen_nse_notices = set(load_json(NSE_NOTICE_FILE, []))

# =========================================================
# MARKET HOURS
# =========================================================

def is_market_open():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return ALERT_START <= t < ALERT_END

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(
            url,
            data={
                "chat_id":    CHAT_ID,
                "text":       msg[:4096],
                "parse_mode": "HTML",
            },
            timeout=20,
        )
        log(f"📨 Telegram status={r.status_code}")
        if r.status_code != 200:
            log(f"⚠️ Telegram error: {r.text[:200]}")
    except Exception:
        traceback.print_exc()

# =========================================================
# NSE SESSION
# =========================================================

_nse_session = None


def get_nse_session():
    global _nse_session
    if _nse_session:
        return _nse_session
    try:
        s = requests.Session()
        s.headers.update(NSE_HEADERS)
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
        _nse_session = s
        log("✅ NSE session ready")
    except Exception:
        log("⚠️ NSE session init failed")
        _nse_session = None
    return _nse_session

# =========================================================
# NSE CORPORATE ANNOUNCEMENTS
# =========================================================

# Categories we care about — maps NSE subject keywords to labels
NOTICE_KEYWORDS = {
    "board meeting":          ("📅", "BOARD MEETING"),
    "financial results":      ("📊", "FINANCIAL RESULTS"),
    "quarterly results":      ("📊", "QUARTERLY RESULTS"),
    "buyback":                ("💸", "BUYBACK"),
    "split":                  ("✂️",  "STOCK SPLIT"),
    "bonus":                  ("🎁", "BONUS ISSUE"),
    "dividend":               ("💰", "DIVIDEND"),
    "merger":                 ("🤝", "MERGER / ACQUISITION"),
    "acquisition":            ("🤝", "MERGER / ACQUISITION"),
    "amalgamation":           ("🤝", "AMALGAMATION"),
    "bulk deal":              ("🏦", "BULK DEAL"),
    "block deal":             ("🏦", "BLOCK DEAL"),
    "insider":                ("👤", "INSIDER TRADING"),
    "trading window":         ("🔒", "TRADING WINDOW"),
    "open offer":             ("📢", "OPEN OFFER"),
    "rights issue":           ("📋", "RIGHTS ISSUE"),
    "demerger":               ("🔀", "DEMERGER"),
    "pledging":               ("🔗", "PROMOTER PLEDGING"),
    "change in management":   ("👔", "MANAGEMENT CHANGE"),
    "resignation":            ("👔", "KEY RESIGNATION"),
    "appointment":            ("👔", "KEY APPOINTMENT"),
    "rating":                 ("🏷️", "CREDIT RATING"),
    "default":                ("🚨", "PAYMENT DEFAULT"),
    "npa":                    ("🚨", "NPA NOTICE"),
    "penalty":                ("⚠️", "PENALTY / FINE"),
    "regulatory":             ("⚠️", "REGULATORY ACTION"),
    "order":                  ("📜", "ORDER RECEIVED"),
    "contract":               ("📜", "CONTRACT / ORDER"),
}


def classify_notice(subject: str):
    """
    Returns (emoji, label) for a notice subject line,
    or None if it doesn't match any category we care about.
    """
    sl = subject.lower()
    for keyword, (emoji, label) in NOTICE_KEYWORDS.items():
        if keyword in sl:
            return emoji, label
    return None


def fetch_nse_announcements(symbol: str):
    """
    Returns list of recent corporate announcements for a symbol.
    Each item: { "subject", "desc", "date", "attchmntFile" }
    """
    try:
        s = get_nse_session()
        if not s:
            return []
        url = (
            "https://www.nseindia.com/api/corp-info"
            f"?symbol={symbol}&market=equities"
        )
        r = s.get(url, timeout=8)
        if r.status_code != 200:
            return []
        data = r.json()
        # NSE returns announcements under "corpInfo" > "announcements"
        return data.get("corpInfo", {}).get("announcements", [])
    except Exception:
        return []


def process_nse_notices():
    """
    Poll NSE for corporate announcements across the full watchlist.
    Send one Telegram alert per NEW notice found.
    """
    global seen_nse_notices
    new_notice_count = 0

    log("📰 Checking NSE announcements...")

    for symbol in WATCHLIST:
        try:
            announcements = fetch_nse_announcements(symbol)
            time.sleep(0.3)

            for ann in announcements:
                subject = ann.get("subject", "") or ann.get("desc", "") or ""
                ann_date = ann.get("date", "") or ann.get("bm_date", "")
                attachment = ann.get("attchmntFile", "")

                # Build a unique key: symbol + subject + date
                notice_key = f"{symbol}|{subject[:80]}|{ann_date}"

                if notice_key in seen_nse_notices:
                    continue

                classified = classify_notice(subject)
                if not classified:
                    # Don't spam with unclassified notices
                    seen_nse_notices.add(notice_key)
                    continue

                seen_nse_notices.add(notice_key)
                new_notice_count += 1

                emoji, label = classified
                ist_now = datetime.now(IST).strftime("%d %b %Y  %H:%M:%S IST")

                msg_lines = [
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"{emoji} <b>NSE NOTICE — {label}</b>",
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"",
                    f"🏷️ <b>Stock:</b>    {symbol}",
                    f"📋 <b>Category:</b> {label}",
                    f"📅 <b>Date:</b>     {ann_date or 'N/A'}",
                    f"",
                    f"📝 <b>Subject:</b>",
                    f"   {subject[:300]}",
                ]

                if attachment:
                    doc_url = (
                        f"https://www.nseindia.com/{attachment}"
                        if not attachment.startswith("http")
                        else attachment
                    )
                    msg_lines += [f"", f"📎 <a href='{doc_url}'>View Filing</a>"]

                msg_lines += [f"", f"🕐 {ist_now}"]

                send_telegram("\n".join(msg_lines))
                time.sleep(0.5)

        except Exception:
            traceback.print_exc()
            continue

    save_json(list(seen_nse_notices), NSE_NOTICE_FILE)
    log(f"📰 NSE notices: {new_notice_count} new alerts sent")

# =========================================================
# PRICE / VOLUME DATA FETCH
# =========================================================

def fetch_stock(symbol: str):
    """
    Fetches 2 days of 5-min candles.
    Returns structured data dict or None.

    Today's candles are isolated (index-based, not by timestamp,
    to work around yfinance timezone inconsistencies).
    The currently-forming candle is always dropped.
    """
    try:
        time.sleep(random.uniform(0.3, 0.8))

        df = yf.download(
            f"{symbol}.NS",
            period="2d",
            interval="5m",
            progress=False,
            auto_adjust=True,
            threads=False,
        )

        if df.empty:
            return None

        # Fix MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()]

        # Drop the currently forming candle (last row may be partial)
        if len(df) > 1:
            df = df.iloc[:-1]

        if len(df) < 12:
            return None

        # ── Isolate today's candles ───────────────────────
        # yfinance 2d/5m returns previous session + today
        # Find where today's session starts by looking for a volume
        # drop-off (end of previous session) or use last ~78 rows max
        # (NSE has ~75 candles in a full day: 6h15m / 5m)
        today_candles = df.tail(min(len(df), 78)).copy()

        if len(today_candles) < 3:
            return None

        # ── Price levels ─────────────────────────────────
        day_open   = float(today_candles["Open"].iloc[0])
        last_price = float(today_candles["Close"].iloc[-1])
        day_high   = float(today_candles["High"].max())
        day_low    = float(today_candles["Low"].min())

        if day_open <= 0 or last_price <= 0:
            return None

        move_pct = ((last_price - day_open) / day_open) * 100

        # ── Volume analysis ───────────────────────────────
        volumes = today_candles["Volume"].values.astype(float)

        # Candle-level spike: current vs 20-candle avg
        last_vol   = volumes[-1]
        avg_20     = float(pd.Series(volumes[:-1]).tail(20).mean()) if len(volumes) > 1 else 0
        spike_ratio = (last_vol / avg_20) if avg_20 > 0 else 0

        # 15-min block surge: last 3 candles vs prior 3 candles
        block_15m_now  = float(sum(volumes[-3:])) if len(volumes) >= 3 else 0
        block_15m_prev = float(sum(volumes[-6:-3])) if len(volumes) >= 6 else 0
        block_15m_ratio = (block_15m_now / block_15m_prev) if block_15m_prev > 0 else 0

        # 30-min block surge: last 6 candles vs average 30-min block today
        block_30m_now = float(sum(volumes[-6:])) if len(volumes) >= 6 else 0
        # Build all non-overlapping 30-min blocks from today
        all_30m_blocks = []
        for i in range(0, len(volumes) - 6, 6):
            all_30m_blocks.append(float(sum(volumes[i:i+6])))
        avg_30m_block = float(pd.Series(all_30m_blocks).mean()) if all_30m_blocks else 0
        block_30m_ratio = (block_30m_now / avg_30m_block) if avg_30m_block > 0 else 0

        # ── Volume signal classification ──────────────────
        # Each signal requires price confirmation (move_pct > VOL_PRICE_CONFIRM)
        # to avoid flagging distribution / reversal volume as "breakout"

        vol_spike_triggered   = spike_ratio >= VOL_SPIKE_MULT
        vol_15m_triggered     = (
            block_15m_ratio >= VOL_BLOCK_15M_MULT
            and abs(move_pct) >= VOL_PRICE_CONFIRM
        )
        vol_30m_triggered     = (
            block_30m_ratio >= VOL_BLOCK_30M_MULT
            and abs(move_pct) >= VOL_PRICE_CONFIRM
        )

        # ── Day high breakout ─────────────────────────────
        # Must be a meaningful high (above open by > DAY_HIGH_MIN_MOVE)
        # and the latest close must be at or very near the high
        high_vs_open_pct = ((day_high - day_open) / day_open) * 100
        day_high_breakout = (
            last_price >= day_high * 0.998   # within 0.2% of high
            and high_vs_open_pct >= DAY_HIGH_MIN_MOVE
        )

        # ── Candle direction for volume ───────────────────
        last_candle_bullish = (
            float(today_candles["Close"].iloc[-1]) >=
            float(today_candles["Open"].iloc[-1])
        )

        return {
            "symbol":             symbol,
            "price":              last_price,
            "day_open":           day_open,
            "day_high":           day_high,
            "day_low":            day_low,
            "move_pct":           move_pct,
            "high_vs_open_pct":   high_vs_open_pct,

            # Volume metrics
            "last_vol":           int(last_vol),
            "avg_20_vol":         int(avg_20),
            "spike_ratio":        round(spike_ratio, 2),
            "block_15m_now":      int(block_15m_now),
            "block_15m_prev":     int(block_15m_prev),
            "block_15m_ratio":    round(block_15m_ratio, 2),
            "block_30m_now":      int(block_30m_now),
            "avg_30m_block":      int(avg_30m_block),
            "block_30m_ratio":    round(block_30m_ratio, 2),

            # Signal flags
            "vol_spike_triggered":   vol_spike_triggered,
            "vol_15m_triggered":     vol_15m_triggered,
            "vol_30m_triggered":     vol_30m_triggered,
            "day_high_breakout":     day_high_breakout,
            "last_candle_bullish":   last_candle_bullish,
        }

    except Exception:
        err = traceback.format_exc()
        if "YFRateLimitError" in err:
            log(f"⏳ {symbol}: Rate limited")
            return None
        if any(x in err for x in ["possibly delisted", "404", "No data found"]):
            return None
        log(f"❌ {symbol}: fetch error")
        return None

# =========================================================
# FETCH ALL STOCKS
# =========================================================

def fetch_all():
    results = {}
    log("📊 Fetching price data...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_stock, sym): sym
            for sym in WATCHLIST
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                data = future.result()
                if data:
                    results[sym] = data
            except Exception:
                log(f"❌ {sym}: thread error")
                traceback.print_exc()

    log(f"📦 Fetch done — {len(results)} valid")
    return results

# =========================================================
# ALERT MESSAGE BUILDERS
# =========================================================

def ist_stamp():
    return datetime.now(IST).strftime("%d %b %Y  %H:%M:%S IST")


def direction_label(move_pct):
    if move_pct > 0:
        return "📈 UPSIDE"
    return "📉 DOWNSIDE"


def build_price_alert(stock):
    sym      = stock["symbol"]
    price    = stock["price"]
    move_pct = stock["move_pct"]
    day_open = stock["day_open"]
    day_high = stock["day_high"]
    day_low  = stock["day_low"]
    direct   = direction_label(move_pct)

    return "\n".join([
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🚨 <b>PRICE MOVE ALERT</b>  |  {direct}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"🏷️ <b>Stock:</b>      {sym}",
        f"💰 <b>LTP:</b>        ₹{price:,.2f}",
        f"📊 <b>Move:</b>       <b>{move_pct:+.2f}%</b> from day open",
        f"",
        f"━━ 📌 PRICE LEVELS ━━",
        f"  🔓 Day Open:   ₹{day_open:,.2f}",
        f"  ⬆️ Day High:   ₹{day_high:,.2f}",
        f"  ⬇️ Day Low:    ₹{day_low:,.2f}",
        f"  📐 Range:      ₹{day_high - day_low:,.2f}",
        f"",
        f"━━ 🎯 WHY THIS TRIGGERED ━━",
        f"  🚨 Price crossed <b>{PRICE_MOVE_PCT:.0f}% threshold</b> from open",
        f"  Move of {move_pct:+.2f}% in today's session",
        f"  {'Strong momentum — price holding gains' if move_pct > 0 else 'Heavy selling — watch for support'}",
        f"",
        f"🕐 {ist_stamp()}",
    ])


def build_day_high_alert(stock):
    sym              = stock["symbol"]
    price            = stock["price"]
    day_open         = stock["day_open"]
    day_high         = stock["day_high"]
    day_low          = stock["day_low"]
    move_pct         = stock["move_pct"]
    high_vs_open_pct = stock["high_vs_open_pct"]

    return "\n".join([
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔥 <b>DAY HIGH BREAKOUT</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"🏷️ <b>Stock:</b>      {sym}",
        f"💰 <b>LTP:</b>        ₹{price:,.2f}",
        f"⬆️ <b>Day High:</b>   ₹{day_high:,.2f}",
        f"📊 <b>Move:</b>       {move_pct:+.2f}% from open",
        f"",
        f"━━ 📌 PRICE LEVELS ━━",
        f"  🔓 Day Open:   ₹{day_open:,.2f}",
        f"  ⬆️ Day High:   ₹{day_high:,.2f}  ← at/near current price",
        f"  ⬇️ Day Low:    ₹{day_low:,.2f}",
        f"  📐 High vs Open: +{high_vs_open_pct:.2f}%",
        f"",
        f"━━ 🎯 WHY THIS TRIGGERED ━━",
        f"  🔥 Price is at/near intraday high",
        f"  High is <b>{high_vs_open_pct:.2f}% above open</b> — meaningful breakout",
        f"  {'Strong buying pressure — price making new highs' if move_pct > 1 else 'Pushing higher — watch for follow-through'}",
        f"",
        f"🕐 {ist_stamp()}",
    ])


def build_volume_alert(stock, trigger_type):
    sym      = stock["symbol"]
    price    = stock["price"]
    day_open = stock["day_open"]
    day_high = stock["day_high"]
    day_low  = stock["day_low"]
    move_pct = stock["move_pct"]
    direction = "buying" if stock["last_candle_bullish"] else "selling"

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>VOLUME SURGE ALERT</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"🏷️ <b>Stock:</b>      {sym}",
        f"💰 <b>LTP:</b>        ₹{price:,.2f}",
        f"📊 <b>Move:</b>       {move_pct:+.2f}% from open",
        f"",
        f"━━ 📌 PRICE LEVELS ━━",
        f"  🔓 Day Open:   ₹{day_open:,.2f}",
        f"  ⬆️ Day High:   ₹{day_high:,.2f}",
        f"  ⬇️ Day Low:    ₹{day_low:,.2f}",
        f"",
        f"━━ 🔊 VOLUME DATA ━━",
    ]

    if trigger_type == "SPIKE":
        lines += [
            f"  🔊 Last 5m candle vol:  {stock['last_vol']:,}",
            f"  📏 20-candle avg vol:   {stock['avg_20_vol']:,}",
            f"  📊 Spike ratio:         <b>{stock['spike_ratio']:.2f}x</b> avg",
            f"  ⚡ Type: Single-candle spike",
        ]
    elif trigger_type == "15M":
        lines += [
            f"  🔊 Last 15m vol:        {stock['block_15m_now']:,}",
            f"  📏 Prior 15m vol:       {stock['block_15m_prev']:,}",
            f"  📊 15m block ratio:     <b>{stock['block_15m_ratio']:.2f}x</b>",
            f"  ⚡ Type: 15-min momentum buildup",
        ]
    elif trigger_type == "30M":
        lines += [
            f"  🔊 Last 30m vol:        {stock['block_30m_now']:,}",
            f"  📏 Avg 30m vol today:   {stock['avg_30m_block']:,}",
            f"  📊 30m block ratio:     <b>{stock['block_30m_ratio']:.2f}x</b>",
            f"  ⚡ Type: 30-min accumulation surge",
        ]

    lines += [
        f"",
        f"━━ 🎯 WHY THIS TRIGGERED ━━",
    ]

    if trigger_type == "SPIKE":
        lines += [
            f"  📊 A single 5m candle just saw <b>{stock['spike_ratio']:.1f}x</b> normal volume",
            f"  This often signals news, block trade, or breakout entry",
            f"  Direction: <b>{direction.upper()}</b> candle",
        ]
    elif trigger_type == "15M":
        lines += [
            f"  📊 Volume over last 15 mins is <b>{stock['block_15m_ratio']:.1f}x</b> the prior 15 mins",
            f"  Sustained buying/selling — not a single spike",
            f"  Price confirming: {move_pct:+.2f}% move | Direction: <b>{direction.upper()}</b>",
        ]
    elif trigger_type == "30M":
        lines += [
            f"  📊 This 30-min window is <b>{stock['block_30m_ratio']:.1f}x</b> the avg 30-min volume today",
            f"  Institutional-style accumulation/distribution pattern",
            f"  Price confirming: {move_pct:+.2f}% move | Direction: <b>{direction.upper()}</b>",
        ]

    lines += [f"", f"🕐 {ist_stamp()}"]
    return "\n".join(lines)

# =========================================================
# ALERT PROCESSOR
# =========================================================

def process_alerts(all_data: dict):
    alert_count = 0

    for symbol, stock in all_data.items():
        move_pct = stock["move_pct"]

        # ── 1. Price Move Alert ─────────────────────────
        if abs(move_pct) >= PRICE_MOVE_PCT:
            direction = "UP" if move_pct > 0 else "DOWN"
            key = f"{symbol}-PRICE-{direction}-{today_str()}"
            if key not in seen_alerts:
                seen_alerts.add(key)
                log(f"🚨 PRICE ALERT: {symbol} {move_pct:+.2f}%")
                send_telegram(build_price_alert(stock))
                alert_count += 1
                time.sleep(0.5)

        # ── 2. Day High Breakout ────────────────────────
        if stock["day_high_breakout"]:
            key = f"{symbol}-DAYHIGH-{today_str()}"
            if key not in seen_alerts:
                seen_alerts.add(key)
                log(f"🔥 DAY HIGH: {symbol} ₹{stock['day_high']:,.2f}")
                send_telegram(build_day_high_alert(stock))
                alert_count += 1
                time.sleep(0.5)

        # ── 3a. Volume Spike (single candle) ───────────
        if stock["vol_spike_triggered"]:
            key = f"{symbol}-VOLSPIKE-{today_str()}"
            if key not in seen_alerts:
                seen_alerts.add(key)
                log(f"📊 VOL SPIKE: {symbol} {stock['spike_ratio']:.1f}x")
                send_telegram(build_volume_alert(stock, "SPIKE"))
                alert_count += 1
                time.sleep(0.5)

        # ── 3b. Volume 15-min Block Surge ──────────────
        if stock["vol_15m_triggered"]:
            key = f"{symbol}-VOL15M-{today_str()}"
            if key not in seen_alerts:
                seen_alerts.add(key)
                log(f"📊 VOL 15M: {symbol} {stock['block_15m_ratio']:.1f}x")
                send_telegram(build_volume_alert(stock, "15M"))
                alert_count += 1
                time.sleep(0.5)

        # ── 3c. Volume 30-min Block Surge ──────────────
        if stock["vol_30m_triggered"]:
            key = f"{symbol}-VOL30M-{today_str()}"
            if key not in seen_alerts:
                seen_alerts.add(key)
                log(f"📊 VOL 30M: {symbol} {stock['block_30m_ratio']:.1f}x")
                send_telegram(build_volume_alert(stock, "30M"))
                alert_count += 1
                time.sleep(0.5)

    return alert_count

# =========================================================
# MAIN BOT
# =========================================================

def run_bot():
    ist_now_str = datetime.now(IST).strftime("%H:%M:%S")
    log(f"🚀 RUN STARTED | {ist_now_str} IST")

    if not is_market_open():
        log("⏰ Outside market hours — skipping")
        return

    log("✅ Market hours active")

    # ── NSE Notices (runs every cycle) ───────────────
    try:
        process_nse_notices()
    except Exception:
        log("⚠️ NSE notice check failed — continuing")
        traceback.print_exc()

    # ── Price / Volume data ───────────────────────────
    all_data = fetch_all()

    if not all_data:
        log("⚠️ No data fetched this run")
        save_seen_alerts(seen_alerts)
        return

    # ── Process alerts ────────────────────────────────
    alert_count = process_alerts(all_data)

    # ── Persist state ─────────────────────────────────
    save_seen_alerts(seen_alerts)

    log(
        f"✅ RUN COMPLETE | "
        f"Stocks={len(all_data)} | "
        f"Alerts={alert_count}"
    )

# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":
    try:
        run_bot()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        log("❌ CRITICAL ERROR IN MAIN")
