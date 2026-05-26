# =========================================================
# NSE MOMENTUM ALERT BOT — v5
# =========================================================
#
# CHANGES FROM v4
# ---------------------------------------------------------
#
# [REMOVED] Volume breakout alerts (SPIKE / 15M / 30M)
#           Too noisy — fired constantly on normal activity
#
# [CHANGED] Price move alert now fires at EVERY new price
#           milestone crossed (every +0.5% above last alert)
#           Instead of once-per-day, it tracks the last
#           alerted price level and re-fires when price
#           moves another threshold above it
#           e.g. 3% → alert, 3.5% → alert, 4% → alert
#
# [CHANGED] Day high alert re-fires only when the day high
#           is meaningfully EXTENDED (not the same high again)
#           Tracks last alerted day-high price, fires again
#           only when new high exceeds previous by >= 0.5%
#
# [ADDED]   Consolidation Breakout detection on 5m and 15m
#           Logic: detect tight price range (consolidation)
#           over N candles, then fire when price breaks out
#           of that range with volume confirmation
#           Header: 🔲 CONSOLIDATION BREAKOUT
#
# [ADDED]   NSE News fetch — searches NSE search API for
#           recent news headlines per watchlist symbol
#           Fires alert for any new headline found
#
# [KEPT]    NSE corporate announcements (board meeting,
#           results, dividend, splits, bulk deals, etc.)
#
# [KEPT]    Bug fix: load_seen_alerts() handles old plain-list
#           format gracefully with isinstance(raw, dict) guard
#
# =========================================================
#
# ALERT TYPES (in order of priority)
# ---------------------------------------------------------
#
# 1. 🚨 PRICE MOVE ALERT
#    Fires when price moves >= PRICE_MOVE_PCT (3%) from open
#    Re-fires every PRICE_STEP_PCT (0.5%) beyond last alert
#    e.g. fires at 3.0%, 3.5%, 4.0%, 4.5% etc.
#    Both upside and downside tracked independently
#
# 2. 🔥 DAY HIGH BREAKOUT
#    Fires when price is at/near day high (within 0.2%)
#    AND high is >= DAY_HIGH_MIN_MOVE (0.5%) above open
#    Re-fires only when new high exceeds last alerted high
#    by >= DAY_HIGH_STEP_PCT (0.5%) — avoids repeated alerts
#    on the same level
#
# 3. 🔲 CONSOLIDATION BREAKOUT
#    Fires when price breaks out of a tight consolidation
#    zone detected on 5m or 15m candles
#
#    CONSOLIDATION detection logic (best-practice):
#      a) Look at last CONSOL_CANDLES (8) completed candles
#      b) Compute the High-Low range across those candles
#      c) Range must be <= CONSOL_RANGE_PCT (1.2%) of price
#         (tight consolidation — not just low volatility)
#      d) At least CONSOL_MIN_FLAT (5) of those candles must
#         have body ratio < 0.4 (small-bodied / doji-like)
#         confirming price is truly coiling, not just slow
#      e) Breakout = current close breaks ABOVE the zone high
#         by >= CONSOL_BREAK_PCT (0.3%) with bullish candle
#      f) Volume on breakout candle must be >= 1.5x the avg
#         volume of the consolidation candles (expansion)
#    Separate checks on 5m and 15m timeframes
#    15m consolidation breakout = stronger / more reliable
#
# 4. 📰 NSE NEWS ALERT
#    Polls NSE search API for stock-specific news headlines
#    Fires once per new headline found (deduped by headline)
#
# 5. 📋 NSE CORPORATE NOTICE
#    Polls NSE corp-info API for announcements
#    Board meetings, results, buybacks, splits, dividends,
#    mergers, block/bulk deals, insider trading, etc.
#
# DEDUPLICATION
#    Price alerts: re-fire at each 0.5% step (not once/day)
#    Day high: re-fire only on meaningful new high
#    Consolidation: once per symbol per timeframe per day
#    News/notices: once per unique headline/notice key ever
#    All state stored in seen_alerts.json (price/high reset
#    daily; news/notice cache persists across days)
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
import numpy as np
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

# ── Price move alert ──────────────────────────────────────
PRICE_MOVE_PCT   = 3.0   # % from open to trigger first alert
PRICE_STEP_PCT   = 0.5   # re-fire every additional % beyond last alert

# ── Day high alert ────────────────────────────────────────
DAY_HIGH_MIN_MOVE  = 0.5  # high must be >= this % above open to qualify
DAY_HIGH_STEP_PCT  = 0.5  # re-fire only when new high exceeds last by this %

# ── Consolidation breakout (5m and 15m) ──────────────────
CONSOL_CANDLES    = 8     # look back this many completed candles
CONSOL_RANGE_PCT  = 1.2   # max High-Low range % across zone to call it tight
CONSOL_MIN_FLAT   = 5     # min candles with small body (body/range < 0.4)
CONSOL_BREAK_PCT  = 0.3   # breakout: close must exceed zone high by this %
CONSOL_VOL_MULT   = 1.5   # breakout candle volume >= N x avg zone volume

# ── General ──────────────────────────────────────────────
MAX_WORKERS = 2           # keep low to avoid Yahoo rate limits

IST = timezone(timedelta(hours=5, minutes=30))

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
# WATCHLIST — DO NOT MODIFY
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

SEEN_FILE       = "seen_alerts.json"
NSE_NOTICE_FILE = "seen_nse_notices.json"
NSE_NEWS_FILE   = "seen_nse_news.json"


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


# ── seen_alerts: dict keyed by today's date ───────────────
# Structure:
# {
#   "date": "2025-05-26",
#   "price_levels": {
#       "SBIN-UP": 3.5,      ← last alerted move% for SBIN upside
#       "SBIN-DOWN": -3.0,
#   },
#   "day_high_levels": {
#       "SBIN": 842.50,      ← last alerted day-high price for SBIN
#   },
#   "keys": [               ← one-shot keys (consolidation, etc.)
#       "SBIN-CONSOL5M-2025-05-26",
#   ]
# }

def load_seen_alerts():
    """
    [FIX v4→v5] isinstance guard handles old plain-list format
    that caused AttributeError: 'list' object has no attribute 'get'
    """
    raw = load_json(SEEN_FILE, {})

    # [FIX] old code saved a plain list — reset cleanly instead of crashing
    if not isinstance(raw, dict):
        return _empty_seen()

    if raw.get("date") != today_str():
        return _empty_seen()

    return raw


def _empty_seen():
    return {
        "date":           today_str(),
        "price_levels":   {},
        "day_high_levels": {},
        "keys":           [],
    }


def save_seen_alerts():
    save_json(seen_alerts, SEEN_FILE)


# Load state at startup
seen_alerts     = load_seen_alerts()
seen_nse_notices = set(load_json(NSE_NOTICE_FILE, []))
seen_nse_news    = set(load_json(NSE_NEWS_FILE, []))

# =========================================================
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
# NSE NEWS  [NEW in v5]
# =========================================================

def fetch_nse_news(symbol: str):
    """
    Fetches recent news headlines from NSE search API for a symbol.
    Returns list of { "headline", "date", "url" }
    """
    try:
        s = get_nse_session()
        if not s:
            return []
        # NSE search endpoint returns news + announcements
        url = (
            "https://www.nseindia.com/api/search-autocomplete"
            f"?q={symbol}"
        )
        r = s.get(url, timeout=8)
        if r.status_code != 200:
            return []
        data = r.json()
        # News items are under 'results' with type 'news'
        news_items = []
        for item in data.get("results", []):
            if item.get("type", "").lower() in ("news", "announcement"):
                news_items.append({
                    "headline": item.get("symbol_info", "") or item.get("name", ""),
                    "date":     item.get("date", ""),
                    "url":      item.get("url", ""),
                })
        return news_items
    except Exception:
        return []


def process_nse_news():
    """
    Poll NSE for news headlines across the full watchlist.
    [NEW v5] Separate from corporate notices — catches market news,
    analyst reports, regulatory headlines etc.
    """
    global seen_nse_news
    new_count = 0

    log("📰 Checking NSE news...")

    for symbol in WATCHLIST:
        try:
            news_list = fetch_nse_news(symbol)
            time.sleep(0.2)

            for item in news_list:
                headline = item.get("headline", "").strip()
                if not headline or len(headline) < 10:
                    continue

                news_key = f"{symbol}|{headline[:100]}"
                if news_key in seen_nse_news:
                    continue

                seen_nse_news.add(news_key)
                new_count += 1

                ist_now = datetime.now(IST).strftime("%d %b %Y  %H:%M:%S IST")
                url_line = f"\n🔗 <a href='{item['url']}'>Read More</a>" if item.get("url") else ""

                msg = "\n".join([
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"📰 <b>NSE NEWS — {symbol}</b>",
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"",
                    f"🏷️ <b>Stock:</b>    {symbol}",
                    f"📅 <b>Date:</b>     {item.get('date') or 'Recent'}",
                    f"",
                    f"📝 <b>Headline:</b>",
                    f"   {headline[:300]}",
                    f"{url_line}",
                    f"",
                    f"🕐 {ist_now}",
                ])
                send_telegram(msg)
                time.sleep(0.4)

        except Exception:
            traceback.print_exc()
            continue

    save_json(list(seen_nse_news), NSE_NEWS_FILE)
    log(f"📰 NSE news: {new_count} new alerts sent")

# =========================================================
# NSE CORPORATE NOTICES  [KEPT from v4]
# =========================================================

NOTICE_KEYWORDS = {
    "board meeting":        ("📅", "BOARD MEETING"),
    "financial results":    ("📊", "FINANCIAL RESULTS"),
    "quarterly results":    ("📊", "QUARTERLY RESULTS"),
    "buyback":              ("💸", "BUYBACK"),
    "split":                ("✂️",  "STOCK SPLIT"),
    "bonus":                ("🎁", "BONUS ISSUE"),
    "dividend":             ("💰", "DIVIDEND"),
    "merger":               ("🤝", "MERGER / ACQUISITION"),
    "acquisition":          ("🤝", "MERGER / ACQUISITION"),
    "amalgamation":         ("🤝", "AMALGAMATION"),
    "bulk deal":            ("🏦", "BULK DEAL"),
    "block deal":           ("🏦", "BLOCK DEAL"),
    "insider":              ("👤", "INSIDER TRADING"),
    "trading window":       ("🔒", "TRADING WINDOW"),
    "open offer":           ("📢", "OPEN OFFER"),
    "rights issue":         ("📋", "RIGHTS ISSUE"),
    "demerger":             ("🔀", "DEMERGER"),
    "pledging":             ("🔗", "PROMOTER PLEDGING"),
    "change in management": ("👔", "MANAGEMENT CHANGE"),
    "resignation":          ("👔", "KEY RESIGNATION"),
    "appointment":          ("👔", "KEY APPOINTMENT"),
    "rating":               ("🏷️", "CREDIT RATING"),
    "default":              ("🚨", "PAYMENT DEFAULT"),
    "npa":                  ("🚨", "NPA NOTICE"),
    "penalty":              ("⚠️", "PENALTY / FINE"),
    "regulatory":           ("⚠️", "REGULATORY ACTION"),
    "order":                ("📜", "ORDER RECEIVED"),
    "contract":             ("📜", "CONTRACT / ORDER"),
}


def classify_notice(subject: str):
    sl = subject.lower()
    for keyword, (emoji, label) in NOTICE_KEYWORDS.items():
        if keyword in sl:
            return emoji, label
    return None


def fetch_nse_announcements(symbol: str):
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
        return data.get("corpInfo", {}).get("announcements", [])
    except Exception:
        return []


def process_nse_notices():
    global seen_nse_notices
    new_count = 0
    log("📋 Checking NSE corporate notices...")

    for symbol in WATCHLIST:
        try:
            announcements = fetch_nse_announcements(symbol)
            time.sleep(0.3)

            for ann in announcements:
                subject    = ann.get("subject", "") or ann.get("desc", "") or ""
                ann_date   = ann.get("date", "") or ann.get("bm_date", "")
                attachment = ann.get("attchmntFile", "")

                notice_key = f"{symbol}|{subject[:80]}|{ann_date}"
                if notice_key in seen_nse_notices:
                    continue

                classified = classify_notice(subject)
                if not classified:
                    seen_nse_notices.add(notice_key)
                    continue

                seen_nse_notices.add(notice_key)
                new_count += 1

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
    log(f"📋 NSE notices: {new_count} new alerts sent")

# =========================================================
# CONSOLIDATION DETECTION  [NEW in v5]
# =========================================================

def detect_consolidation_breakout(candles: pd.DataFrame, tf_label: str):
    """
    Detect tight consolidation followed by a clean upside breakout.

    Parameters
    ----------
    candles   : DataFrame with Open/High/Low/Close/Volume columns,
                completed candles only (partial candle already dropped)
    tf_label  : "5m" or "15m" — used in the alert message only

    Returns
    -------
    dict with breakout details, or None if no breakout detected.

    LOGIC (best-practice consolidation breakout):
    ─────────────────────────────────────────────
    Step 1 — Need at least CONSOL_CANDLES + 1 rows (zone + breakout)
    Step 2 — Take the CONSOL_CANDLES candles BEFORE the last candle
             as the consolidation zone
    Step 3 — Zone range = (zone_high - zone_low) / zone_mid_price
             Must be <= CONSOL_RANGE_PCT% — "tight" zone
    Step 4 — Count candles with small body (body/range < 0.4)
             Must be >= CONSOL_MIN_FLAT — truly coiling, not lazy
    Step 5 — Last completed candle (breakout candle):
             - Close must be above zone_high by >= CONSOL_BREAK_PCT%
             - Must be a bullish candle (Close >= Open)
             - Volume must be >= CONSOL_VOL_MULT x avg zone volume
    Step 6 — All conditions met → return breakout details dict
    """
    try:
        min_rows = CONSOL_CANDLES + 1
        if len(candles) < min_rows:
            return None

        # Zone = last CONSOL_CANDLES candles before the breakout candle
        zone       = candles.iloc[-(CONSOL_CANDLES + 1):-1]
        breakout_c = candles.iloc[-1]   # the current completed candle

        zone_high  = float(zone["High"].max())
        zone_low   = float(zone["Low"].min())
        zone_mid   = (zone_high + zone_low) / 2

        if zone_mid <= 0:
            return None

        # Step 3: range tightness check
        zone_range_pct = ((zone_high - zone_low) / zone_mid) * 100
        if zone_range_pct > CONSOL_RANGE_PCT:
            return None     # range too wide — not a consolidation

        # Step 4: small-body count (doji/spinning top candles)
        flat_count = 0
        for _, row in zone.iterrows():
            h = float(row["High"])
            l = float(row["Low"])
            o = float(row["Open"])
            c = float(row["Close"])
            candle_range = h - l
            body         = abs(c - o)
            if candle_range > 0 and (body / candle_range) < 0.4:
                flat_count += 1

        if flat_count < CONSOL_MIN_FLAT:
            return None     # not enough coiling candles

        # Step 5a: breakout candle must be bullish
        b_open  = float(breakout_c["Open"])
        b_close = float(breakout_c["Close"])
        b_high  = float(breakout_c["High"])
        b_vol   = float(breakout_c["Volume"])

        if b_close < b_open:
            return None     # bearish candle — not a bullish breakout

        # Step 5b: close must break above zone high meaningfully
        break_above_pct = ((b_close - zone_high) / zone_high) * 100
        if break_above_pct < CONSOL_BREAK_PCT:
            return None     # not a clean break above zone

        # Step 5c: volume expansion on breakout candle
        avg_zone_vol = float(zone["Volume"].mean())
        vol_ratio    = (b_vol / avg_zone_vol) if avg_zone_vol > 0 else 0
        if vol_ratio < CONSOL_VOL_MULT:
            return None     # no volume expansion — weak breakout

        return {
            "tf":              tf_label,
            "zone_high":       round(zone_high, 2),
            "zone_low":        round(zone_low, 2),
            "zone_range_pct":  round(zone_range_pct, 2),
            "flat_candles":    flat_count,
            "breakout_price":  round(b_close, 2),
            "break_above_pct": round(break_above_pct, 2),
            "vol_ratio":       round(vol_ratio, 2),
            "zone_candles":    CONSOL_CANDLES,
        }

    except Exception:
        traceback.print_exc()
        return None

# =========================================================
# PRICE / VOLUME DATA FETCH
# =========================================================

def fetch_stock(symbol: str):
    """
    Fetches 2 days of 5-min candles from Yahoo Finance.
    Isolates today's session, drops partial candle.
    Also builds a 15-min candle DataFrame by resampling.
    Returns structured dict or None.
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

        # Drop currently forming candle (partial)
        if len(df) > 1:
            df = df.iloc[:-1]

        if len(df) < 12:
            return None

        # Isolate today's candles (NSE: ~75 candles per day max)
        today_5m = df.tail(min(len(df), 78)).copy()

        if len(today_5m) < CONSOL_CANDLES + 2:
            return None

        # ── Price levels ─────────────────────────────────
        day_open   = float(today_5m["Open"].iloc[0])
        last_price = float(today_5m["Close"].iloc[-1])
        day_high   = float(today_5m["High"].max())
        day_low    = float(today_5m["Low"].min())

        if day_open <= 0 or last_price <= 0:
            return None

        move_pct = ((last_price - day_open) / day_open) * 100

        # ── Build 15m candles by resampling 5m ───────────
        # [NEW v5] needed for 15m consolidation detection
        today_15m = None
        try:
            # Need datetime index for resample
            df_idx = today_5m.copy()
            if not isinstance(df_idx.index, pd.DatetimeIndex):
                df_idx.index = pd.to_datetime(df_idx.index)

            today_15m = df_idx.resample("15min").agg({
                "Open":   "first",
                "High":   "max",
                "Low":    "min",
                "Close":  "last",
                "Volume": "sum",
            }).dropna()
        except Exception:
            today_15m = None

        # ── Candle direction ──────────────────────────────
        last_candle_bullish = (
            float(today_5m["Close"].iloc[-1]) >=
            float(today_5m["Open"].iloc[-1])
        )

        # ── Day high check ────────────────────────────────
        high_vs_open_pct = ((day_high - day_open) / day_open) * 100
        at_day_high = (
            last_price >= day_high * 0.998
            and high_vs_open_pct >= DAY_HIGH_MIN_MOVE
        )

        # ── Consolidation breakout checks ─────────────────
        consol_5m  = detect_consolidation_breakout(today_5m,  "5m")
        consol_15m = detect_consolidation_breakout(today_15m, "15m") \
                     if today_15m is not None and len(today_15m) >= CONSOL_CANDLES + 1 \
                     else None

        return {
            "symbol":             symbol,
            "price":              last_price,
            "day_open":           day_open,
            "day_high":           day_high,
            "day_low":            day_low,
            "move_pct":           move_pct,
            "high_vs_open_pct":   high_vs_open_pct,
            "at_day_high":        at_day_high,
            "last_candle_bullish": last_candle_bullish,
            "consol_5m":          consol_5m,
            "consol_15m":         consol_15m,
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
    return "📈 UPSIDE" if move_pct > 0 else "📉 DOWNSIDE"


def build_price_alert(stock, step_num: int):
    """
    [CHANGED v5] step_num indicates which alert step this is
    e.g. step 1 = first 3% alert, step 2 = 3.5%, step 3 = 4% etc.
    """
    sym      = stock["symbol"]
    price    = stock["price"]
    move_pct = stock["move_pct"]
    day_open = stock["day_open"]
    day_high = stock["day_high"]
    day_low  = stock["day_low"]
    direct   = direction_label(move_pct)

    step_label = f"Alert #{step_num}" if step_num > 1 else "First Alert"

    return "\n".join([
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🚨 <b>PRICE MOVE ALERT</b>  |  {direct}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"🏷️ <b>Stock:</b>      {sym}",
        f"💰 <b>LTP:</b>        ₹{price:,.2f}",
        f"📊 <b>Move:</b>       <b>{move_pct:+.2f}%</b> from day open",
        f"📶 <b>Step:</b>       {step_label} (every {PRICE_STEP_PCT}% thereafter)",
        f"",
        f"━━ 📌 PRICE LEVELS ━━",
        f"  🔓 Day Open:   ₹{day_open:,.2f}",
        f"  ⬆️ Day High:   ₹{day_high:,.2f}",
        f"  ⬇️ Day Low:    ₹{day_low:,.2f}",
        f"  📐 Range:      ₹{day_high - day_low:,.2f}",
        f"",
        f"━━ 🎯 WHY THIS TRIGGERED ━━",
        f"  🚨 Price moved <b>{move_pct:+.2f}%</b> from today's open",
        f"  Threshold: {PRICE_MOVE_PCT:.0f}% first, then every {PRICE_STEP_PCT}% step",
        f"  {'Momentum building — strong intraday move' if abs(move_pct) > 4 else 'Significant intraday move — watch for continuation'}",
        f"",
        f"🕐 {ist_stamp()}",
    ])


def build_day_high_alert(stock, new_high: float):
    """
    [CHANGED v5] new_high passed explicitly so message is precise
    """
    sym              = stock["symbol"]
    price            = stock["price"]
    day_open         = stock["day_open"]
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
        f"⬆️ <b>New Day High:</b> ₹{new_high:,.2f}",
        f"📊 <b>Move:</b>        {move_pct:+.2f}% from open",
        f"",
        f"━━ 📌 PRICE LEVELS ━━",
        f"  🔓 Day Open:      ₹{day_open:,.2f}",
        f"  ⬆️ Day High:      ₹{new_high:,.2f}  ← NEW HIGH",
        f"  ⬇️ Day Low:       ₹{day_low:,.2f}",
        f"  📐 High vs Open:  +{high_vs_open_pct:.2f}%",
        f"",
        f"━━ 🎯 WHY THIS TRIGGERED ━━",
        f"  🔥 Price printing a new intraday high",
        f"  Re-fires every {DAY_HIGH_STEP_PCT}% above previous high alert",
        f"  {'Strong buying — price pushing to fresh highs' if move_pct > 1.5 else 'Grinding higher — watch for volume confirmation'}",
        f"",
        f"🕐 {ist_stamp()}",
    ])


def build_consolidation_alert(stock, consol: dict):
    """
    [NEW v5] Consolidation breakout alert card.
    Shows zone details, breakout metrics, and why it triggered.
    """
    sym   = stock["symbol"]
    price = stock["price"]
    tf    = consol["tf"]
    tf_full = "5-Minute" if tf == "5m" else "15-Minute"
    strength = "🔥 STRONG" if consol["vol_ratio"] >= 2.5 else "✅ CONFIRMED"

    return "\n".join([
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔲 <b>CONSOLIDATION BREAKOUT</b>  [{tf_full}]",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"🏷️ <b>Stock:</b>         {sym}",
        f"💰 <b>LTP:</b>           ₹{price:,.2f}",
        f"⏱️ <b>Timeframe:</b>     {tf_full} candles",
        f"📶 <b>Strength:</b>      {strength}",
        f"",
        f"━━ 🔲 CONSOLIDATION ZONE ━━",
        f"  📦 Zone candles:    {consol['zone_candles']} completed candles",
        f"  ⬆️ Zone High:       ₹{consol['zone_high']:,.2f}",
        f"  ⬇️ Zone Low:        ₹{consol['zone_low']:,.2f}",
        f"  📐 Zone Range:      {consol['zone_range_pct']:.2f}%  (tight ≤ {CONSOL_RANGE_PCT}%)",
        f"  🕯️ Flat candles:    {consol['flat_candles']}/{consol['zone_candles']} coiling",
        f"",
        f"━━ 💥 BREAKOUT DETAILS ━━",
        f"  🚀 Breakout price:  ₹{consol['breakout_price']:,.2f}",
        f"  📊 Above zone by:   +{consol['break_above_pct']:.2f}%",
        f"  🔊 Volume ratio:    {consol['vol_ratio']:.2f}x zone avg",
        f"",
        f"━━ 🎯 WHY THIS TRIGGERED ━━",
        f"  🔲 Price coiled in {consol['zone_range_pct']:.2f}% range for {consol['zone_candles']} {tf} candles",
        f"  {consol['flat_candles']} of those were small-bodied / doji — true compression",
        f"  Breakout candle closed <b>+{consol['break_above_pct']:.2f}% above zone</b>",
        f"  Volume expanded to <b>{consol['vol_ratio']:.1f}x</b> avg — real buying, not noise",
        f"  {'15m breakout = higher conviction setup' if tf == '15m' else '5m breakout — fast move, watch for 15m confirmation'}",
        f"",
        f"🕐 {ist_stamp()}",
    ])

# =========================================================
# ALERT PROCESSOR  [CHANGED v5]
# =========================================================

def process_alerts(all_data: dict):
    """
    [CHANGED v5]
    - Price alerts: re-fire at every PRICE_STEP_PCT beyond last alerted level
    - Day high: re-fire only when new high > last alerted high by DAY_HIGH_STEP_PCT
    - Consolidation: once per symbol per timeframe per day
    - Volume alerts: REMOVED (too noisy)
    """
    alert_count = 0

    price_levels    = seen_alerts.setdefault("price_levels", {})
    day_high_levels = seen_alerts.setdefault("day_high_levels", {})
    one_shot_keys   = seen_alerts.setdefault("keys", [])

    for symbol, stock in all_data.items():
        move_pct   = stock["move_pct"]
        last_price = stock["price"]
        day_high   = stock["day_high"]

        # ── 1. Price Move Alert ─────────────────────────
        # [CHANGED] Re-fires at every PRICE_STEP_PCT step
        if abs(move_pct) >= PRICE_MOVE_PCT:
            direction = "UP" if move_pct > 0 else "DOWN"
            level_key = f"{symbol}-{direction}"

            last_alerted = price_levels.get(level_key)  # last alerted move%

            should_fire = False
            step_num    = 1

            if last_alerted is None:
                # First time crossing threshold
                should_fire = True
                step_num    = 1
            else:
                # Re-fire if moved another PRICE_STEP_PCT beyond last alert
                gap = abs(abs(move_pct) - abs(last_alerted))
                if gap >= PRICE_STEP_PCT:
                    should_fire = True
                    # Calculate which step number this is
                    step_num = int(
                        (abs(move_pct) - PRICE_MOVE_PCT) / PRICE_STEP_PCT
                    ) + 1

            if should_fire:
                price_levels[level_key] = move_pct
                log(f"🚨 PRICE ALERT #{step_num}: {symbol} {move_pct:+.2f}%")
                send_telegram(build_price_alert(stock, step_num))
                alert_count += 1
                time.sleep(0.5)

        # ── 2. Day High Breakout ────────────────────────
        # [CHANGED] Re-fires only when new high exceeds last alerted high
        # by at least DAY_HIGH_STEP_PCT — avoids repeated same-level alerts
        if stock["at_day_high"]:
            last_high_alerted = day_high_levels.get(symbol, 0.0)

            high_extension = 0.0
            if last_high_alerted > 0:
                high_extension = ((day_high - last_high_alerted) / last_high_alerted) * 100

            if last_high_alerted == 0.0 or high_extension >= DAY_HIGH_STEP_PCT:
                day_high_levels[symbol] = day_high
                log(f"🔥 DAY HIGH: {symbol} ₹{day_high:,.2f}")
                send_telegram(build_day_high_alert(stock, day_high))
                alert_count += 1
                time.sleep(0.5)

        # ── 3. Consolidation Breakout — 5m ─────────────
        # [NEW v5] Once per symbol per timeframe per day
        if stock["consol_5m"]:
            key = f"{symbol}-CONSOL5M-{today_str()}"
            if key not in one_shot_keys:
                one_shot_keys.append(key)
                log(f"🔲 CONSOL 5M: {symbol} break +{stock['consol_5m']['break_above_pct']:.2f}%")
                send_telegram(build_consolidation_alert(stock, stock["consol_5m"]))
                alert_count += 1
                time.sleep(0.5)

        # ── 4. Consolidation Breakout — 15m ────────────
        # [NEW v5] 15m is stronger signal — fires independently of 5m
        if stock["consol_15m"]:
            key = f"{symbol}-CONSOL15M-{today_str()}"
            if key not in one_shot_keys:
                one_shot_keys.append(key)
                log(f"🔲 CONSOL 15M: {symbol} break +{stock['consol_15m']['break_above_pct']:.2f}%")
                send_telegram(build_consolidation_alert(stock, stock["consol_15m"]))
                alert_count += 1
                time.sleep(0.5)

    return alert_count

# =========================================================
# MAIN BOT
# =========================================================

def run_bot():
    ist_now_str = datetime.now(IST).strftime("%H:%M:%S")
    log(f"🚀 RUN STARTED | {ist_now_str} IST")

    log("✅ Running scan")

    # ── NSE News [NEW v5] ─────────────────────────────
    try:
        process_nse_news()
    except Exception:
        log("⚠️ NSE news check failed — continuing")
        traceback.print_exc()

    # ── NSE Corporate Notices [KEPT] ──────────────────
    try:
        process_nse_notices()
    except Exception:
        log("⚠️ NSE notice check failed — continuing")
        traceback.print_exc()

    # ── Price / Consolidation data ────────────────────
    all_data = fetch_all()

    if not all_data:
        log("⚠️ No data fetched this run")
        save_seen_alerts()
        return

    # ── Process alerts ────────────────────────────────
    alert_count = process_alerts(all_data)

    # ── Persist state ─────────────────────────────────
    save_seen_alerts()

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
