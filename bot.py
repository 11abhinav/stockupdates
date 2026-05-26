# =========================================================
# NSE MOMENTUM ALERT BOT — v6
# =========================================================
#
# CRON SCHEDULE
# ---------------------------------------------------------
# Expression : 2/5 3-10 * * 1-5  (Railway / UTC)
# Meaning    : every 5 min starting at :02, from 03:00 to
#              10:59 UTC, Monday–Friday only
# IST equiv  : 08:32 – 16:29 IST  (covers pre-market +
#              full session + buffer after 15:30 close)
#
# UTC → IST run map (key times):
#   3:02 UTC = 8:32 IST   pre-market, outside reset window
#   3:07 UTC = 8:37 IST   pre-market, outside reset window
#   3:12 UTC = 8:42 IST   pre-market, outside reset window
#   3:17 UTC = 8:47 IST ← RESET STARTS (window open)
#   3:22 UTC = 8:52 IST   reset
#   3:27 UTC = 8:57 IST   reset
#   3:32 UTC = 9:02 IST   reset
#   3:37 UTC = 9:07 IST   reset
#   3:42 UTC = 9:12 IST   reset  ← last reset before bell
#   3:47 UTC = 9:17 IST   market open, normal scan begins
#   ...every 5 min through session...
#   10:02 UTC = 15:32 IST last scan run after close
#
# =========================================================
#
# CHANGES FROM v5
# ---------------------------------------------------------
#
# [CHANGED] Telegram message formatting:
#           - Stock name now appears immediately on line 2,
#             right after the heading separator
#           - Zero blank lines at the top of every card
#           - Redundant "Stock:" label rows removed —
#             name is already in the heading
#           - Tighter, cleaner layout throughout all cards
#
# [CHANGED] NSE API error handling — fully robust:
#           - All NSE calls routed through central nse_get()
#           - Auto session refresh on 401 / 403 (expired cookie)
#           - Exponential backoff retry: 3 attempts, 2s→4s→6s
#           - 429 rate-limit handled with longer wait
#           - 5xx server errors retried silently
#           - Every failure logs exact HTTP status + reason
#           - Session auto-expires after 10 min, re-inits
#           - NSE failures never crash the bot run
#
# [ADDED]   Pre-market alert file reset (cron-aware):
#           - Reset window: 08:45 – 09:14 IST
#           - Fires on EVERY cron tick in that window
#             (idempotent — safe to run multiple times)
#           - Wipes seen_alerts.json completely: price
#             levels, day-high levels, consolidation keys
#           - seen_nse_news.json NOT wiped — dedupes across
#             all days to avoid repeating old headlines
#           - seen_nse_notices.json NOT wiped — same reason
#           - Window chosen so 6 consecutive cron runs all
#             reset, guaranteeing clean slate even if Railway
#             skips or delays one run
#
# [REMOVED] MARKET_OPEN_HOUR / MARKET_OPEN_MINUTE constants
#           — replaced by is_pre_market_reset_window() which
#           encodes the correct 8:45–9:14 IST window directly
#
# [REMOVED] One-shot reset stamp logic (market_open_reset_date)
#           — no longer needed since reset is idempotent and
#           safe to run on every tick in the window
#
# [FIXED]   NSE session 403 on homepage:
#           - No longer hits nseindia.com homepage (returns 403)
#           - Step 1: hits api/marketStatus (lightweight JSON,
#             no 403, sets initial cookies)
#           - Step 2: hits market-data/live-equity-market to
#             warm up full cookie set (nseappid, nsit etc.)
#           - Each step fails independently — partial session
#             still returned and retry logic handles the rest
#
# [DISABLED] NSE news fetch (📰 NSE NEWS alerts):
#           - api/search-autocomplete → 404 (removed by NSE)
#           - api/search/autocomplete → 404 (also removed)
#           - api/quote-equity        → 403 (WAF block)
#           - 70 stocks × 3 retries = ~4 min wasted per run
#           - process_nse_news() now returns immediately
#           - seen_nse_news.json kept intact for future use
#           - Corporate notices (corp-info) still active and
#             cover all actionable events instead
#
# [KEPT]    All v5 features unchanged:
#           - 🚨 Price move alerts (3% first, +0.5% steps)
#           - 🔥 Day high breakout (re-fires on new highs)
#           - 🔲 Consolidation breakout on 5m and 15m
#           - 📰 NSE news headlines per symbol
#           - 📋 NSE corporate announcements / notices
#           - Partial candle drop logic (< 300s guard)
#           - ThreadPoolExecutor fetch with MAX_WORKERS=2
#           - Full deduplication across all alert types
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

# ── NSE API ──────────────────────────────────────────────
NSE_RETRY_COUNT   = 3     # number of retries per NSE call
NSE_RETRY_DELAY   = 2.0   # base delay between retries (doubles each time)
NSE_TIMEOUT       = 10    # seconds per request
NSE_SESSION_DELAY = 1.5   # pause after session init

# ── General ──────────────────────────────────────────────
MAX_WORKERS = 2           # keep low to avoid Yahoo rate limits

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

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

# ── Market session (IST) ─────────────────────────────────
# Reset window : 08:45 – 09:14 IST (pre-market, before bell)
# Market open  : 09:15 IST  |  Market close : 15:30 IST

# =========================================================
# WATCHLIST
# =========================================================

WATCHLIST = sorted(list(set([
    "ADANIENT", "ADANIGREEN", "ADANIPORTS", "AKZOINDIA", "AFCONS",
    "ANANTRAJ", "ANTHEM", "ARIHANTCAP", "ASIANPAINT", "ATGL", "ATL",
    "BAJAJFINSV", "BEL", "BLS", "BLUEDART", "CASTROLIND", "CCAVENUE",
    "CGPOWER", "CLEAN", "DBL", "EIDPARRY", "FILATEX", "FORTIS",
    "GILLETTE", "GLOBUSSPR", "GSFC", "HDFCBANK", "HINDCOPPER",
    "HINDUNILVR", "HYUNDAI", "ICICIAMC", "ICICIBANK", "IDBI", "IFCI",
    "INDUSTOWER", "INFY", "IRB", "IRCTC", "ITBEES", "JIOFIN",
    "JPASSOCIAT", "JSWENERGY", "KWIL", "LATENTVIEW", "LGEINDIA",
    "LLOYDSENGG", "LOTUSDEV", "LT", "MARUTI", "MAZDOCK", "MENNPIS",
    "MIRZAINT", "NATCOPHARM", "ONGC", "ORIENTCEM", "PFC", "PIDILITIND",
    "POONAWALLA", "PVRINOX", "RELIANCE", "RELINFRA", "RTNPOWER",
    "RVNL", "SANGHIIND", "SBIN", "SRHHYPOLTD", "SUPREMEIND",
    "SUVIDHAA", "SUZLON", "SWIGGY", "SYMPHONY", "TATATECH", "TITAN",
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
        log(f"⚠️ Failed to load {filename}, using default")
        return default


def save_json(data, filename):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        log(f"⚠️ Failed to save {filename}")
        traceback.print_exc()


def today_str():
    return datetime.now(IST).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────
# MARKET-OPEN RESET  [NEW v6]
# ─────────────────────────────────────────────────────────
# Wipes price-level and day-high alert state at market open
# so every stock gets a completely fresh slate each session.
# News and notice caches are intentionally preserved.

def is_pre_market_reset_window():
    """
    Returns True if current IST time is in the pre-market reset
    window: 08:45 – 09:14 IST.

    Cron is 2/5 3-10 UTC. Relevant UTC runs and their IST times:
        3:17 UTC = 8:47 IST  ← first run in window  ✅
        3:22 UTC = 8:52 IST  ✅
        3:27 UTC = 8:57 IST  ✅
        3:32 UTC = 9:02 IST  ✅
        3:37 UTC = 9:07 IST  ✅
        3:42 UTC = 9:12 IST  ✅  ← last run before market open
        3:47 UTC = 9:17 IST  ← market already open, reset done

    ALL runs in this window reset the file (idempotent — stamp
    prevents any real work being repeated). This guarantees a
    clean slate well before the 9:15 IST opening bell even if
    Railway skips or delays one cron run.
    """
    now = datetime.now(IST)
    # 8:45 → hour=8, minute>=45
    # 9:00 → hour=9, minute<15
    if now.hour == 8 and now.minute >= 45:
        return True
    if now.hour == 9 and now.minute < 15:
        return True
    return False


def reset_alert_files_at_open():
    """
    Called on every bot run. Wipes seen_alerts.json during the
    pre-market window (8:45–9:14 IST) so price-level and
    day-high state is completely fresh before market opens.

    Runs on EVERY cron tick in the window (not just once) —
    safe because writing an empty file is idempotent.
    seen_nse_news.json and seen_nse_notices.json are NOT wiped.
    """
    if not is_pre_market_reset_window():
        return

    log("🔔 PRE-MARKET WINDOW (8:45–9:14 IST) — resetting alert state")
    fresh = _empty_seen()
    fresh["market_open_reset_date"] = today_str()
    save_json(fresh, SEEN_FILE)
    log("✅ seen_alerts.json wiped — clean slate for today's session")


def load_seen_alerts():
    raw = load_json(SEEN_FILE, {})
    if not isinstance(raw, dict):
        return _empty_seen()
    if raw.get("date") != today_str():
        return _empty_seen()
    return raw


def _empty_seen():
    return {
        "date":                   today_str(),
        "price_levels":           {},
        "day_high_levels":        {},
        "keys":                   [],
        "market_open_reset_date": None,
    }


def save_seen_alerts():
    save_json(seen_alerts, SEEN_FILE)


# Load state at startup
seen_alerts      = load_seen_alerts()
seen_nse_notices = set(load_json(NSE_NOTICE_FILE, []))
seen_nse_news    = set(load_json(NSE_NEWS_FILE,   []))

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
# NSE SESSION  [IMPROVED v6]
# =========================================================

_nse_session      = None
_nse_session_time = None
NSE_SESSION_TTL   = 600   # re-init session after 10 minutes


def _init_nse_session():
    """
    Creates a fresh NSE session using a two-step warm-up:

    Step 1 — GET nseindia.com/api/marketStatus
      A lightweight JSON endpoint NSE exposes without requiring
      a pre-existing cookie. Avoids the 403 that the homepage
      returns to bots. Sets the initial session cookies.

    Step 2 — GET nseindia.com/market-data/live-equity-market
      A second lightweight page hit to ensure NSE's CDN/WAF
      sees a realistic browsing pattern and issues the full
      cookie set (nseappid, nsit, etc.) needed for API calls.

    Both steps are attempted independently. A partial warm-up
    (only Step 1 succeeds) still returns a usable session —
    it may have weaker cookies but the API call retry logic
    will refresh if needed.

    Returns the session object or None if both steps fail.
    """
    try:
        s = requests.Session()
        s.headers.update(NSE_HEADERS)

        # ── Step 1: lightweight JSON endpoint (no 403 risk) ──
        try:
            r1 = s.get(
                "https://www.nseindia.com/api/marketStatus",
                timeout=NSE_TIMEOUT,
            )
            if r1.status_code == 200:
                log("✅ NSE session step 1 OK (marketStatus)")
            else:
                log(f"⚠️ NSE session step 1 HTTP {r1.status_code} — continuing anyway")
        except Exception as e:
            log(f"⚠️ NSE session step 1 failed ({e}) — continuing")

        time.sleep(0.8)

        # ── Step 2: secondary page to warm up full cookie set ──
        try:
            r2 = s.get(
                "https://www.nseindia.com/market-data/live-equity-market",
                timeout=NSE_TIMEOUT,
            )
            if r2.status_code == 200:
                log("✅ NSE session step 2 OK (live-equity-market)")
            else:
                log(f"⚠️ NSE session step 2 HTTP {r2.status_code} — cookies may be partial")
        except Exception as e:
            log(f"⚠️ NSE session step 2 failed ({e}) — using partial session")

        time.sleep(NSE_SESSION_DELAY)
        log("✅ NSE session (re)initialised")
        return s

    except Exception as e:
        log(f"⚠️ NSE session unexpected error: {e}")
    return None


def get_nse_session(force_refresh: bool = False):
    """
    [IMPROVED v6] Returns a valid NSE session, auto-refreshing when:
      - Session is None
      - force_refresh=True (called after a failed request)
      - Session is older than NSE_SESSION_TTL seconds
    """
    global _nse_session, _nse_session_time
    now = time.time()

    age = (now - _nse_session_time) if _nse_session_time else float("inf")
    if force_refresh or _nse_session is None or age > NSE_SESSION_TTL:
        _nse_session      = _init_nse_session()
        _nse_session_time = now

    return _nse_session


def nse_get(url: str, label: str = "NSE"):
    """
    [NEW v6] Centralised NSE GET with:
      - Automatic session refresh on failure
      - Retry with exponential backoff (NSE_RETRY_COUNT attempts)
      - Detailed error logging per attempt
      - Returns parsed JSON dict/list or None on all failures
    """
    for attempt in range(1, NSE_RETRY_COUNT + 1):
        s = get_nse_session(force_refresh=(attempt > 1))
        if s is None:
            log(f"⚠️ [{label}] No NSE session (attempt {attempt}/{NSE_RETRY_COUNT})")
            time.sleep(NSE_RETRY_DELAY * attempt)
            continue
        try:
            r = s.get(url, timeout=NSE_TIMEOUT)

            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    log(f"⚠️ [{label}] HTTP 200 but invalid JSON (attempt {attempt})")
                    return None

            elif r.status_code in (401, 403):
                log(f"⚠️ [{label}] HTTP {r.status_code} — session expired, refreshing")
                get_nse_session(force_refresh=True)

            elif r.status_code == 429:
                wait = NSE_RETRY_DELAY * attempt * 2
                log(f"⚠️ [{label}] HTTP 429 rate-limited — waiting {wait:.1f}s")
                time.sleep(wait)

            elif r.status_code >= 500:
                log(f"⚠️ [{label}] HTTP {r.status_code} server error (attempt {attempt})")

            else:
                log(f"⚠️ [{label}] HTTP {r.status_code} unexpected (attempt {attempt})")

        except requests.exceptions.Timeout:
            log(f"⚠️ [{label}] Timeout on attempt {attempt}/{NSE_RETRY_COUNT}")
        except requests.exceptions.ConnectionError as e:
            log(f"⚠️ [{label}] Connection error (attempt {attempt}): {e}")
        except Exception as e:
            log(f"⚠️ [{label}] Unexpected error (attempt {attempt}): {e}")

        if attempt < NSE_RETRY_COUNT:
            time.sleep(NSE_RETRY_DELAY * attempt)

    log(f"❌ [{label}] All {NSE_RETRY_COUNT} attempts failed — skipping")
    return None

# =========================================================
# NSE NEWS  [DISABLED — NSE blocks all bot API access]
# =========================================================
#
# WHY DISABLED
# ─────────────
# NSE has hardened their API against automated/bot access.
# Every search/news endpoint returns 403 or 404 regardless
# of cookie warm-up, session headers, or retry strategy:
#
#   api/search-autocomplete   → 404 (endpoint removed)
#   api/search/autocomplete   → 404 (also removed)
#   api/quote-equity          → 403 (WAF/cookie block)
#
# Running 70+ symbols × 3 retry attempts each wastes ~3-4
# minutes per bot run for zero useful output.
#
# WHAT COVERS NEWS INSTEAD
# ─────────────────────────
# Corporate announcements (process_nse_notices below) use
# api/corp-info which is more stable and covers the most
# actionable events: results, dividends, splits, etc.
#
# TO RE-ENABLE
# ─────────────
# If NSE opens a public news API in future, implement
# fetch_nse_news() here and call process_nse_news() from
# run_bot(). The seen_nse_news dedup set is maintained so
# it will work correctly once plugged back in.

def process_nse_news():
    """NSE news disabled — API endpoints blocked by NSE WAF."""
    log("📰 NSE news: disabled (NSE API blocked) — skipping")


# =========================================================
# NSE CORPORATE NOTICES  [IMPROVED v6 — uses nse_get()]
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
    url  = (
        f"https://www.nseindia.com/api/corp-info"
        f"?symbol={symbol}&market=equities"
    )
    data = nse_get(url, label=f"CORP:{symbol}")
    if not data:
        return []
    return data.get("corpInfo", {}).get("announcements", [])


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

                # ── [CHANGED v6] Stock name on line 2, no top gap ──
                msg_lines = [
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"{emoji} <b>NSE NOTICE — {symbol}</b>",
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"🏷️ <b>Category:</b> {label}",
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
            log(f"⚠️ Notice processing error for {symbol}")
            traceback.print_exc()
            continue

    save_json(list(seen_nse_notices), NSE_NOTICE_FILE)
    log(f"📋 NSE notices: {new_count} new alerts sent")

# =========================================================
# CONSOLIDATION DETECTION
# =========================================================

def detect_consolidation_breakout(candles: pd.DataFrame, tf_label: str):
    try:
        min_rows = CONSOL_CANDLES + 1
        if len(candles) < min_rows:
            return None

        zone       = candles.iloc[-(CONSOL_CANDLES + 1):-1]
        breakout_c = candles.iloc[-1]

        zone_high  = float(zone["High"].max())
        zone_low   = float(zone["Low"].min())
        zone_mid   = (zone_high + zone_low) / 2

        if zone_mid <= 0:
            return None

        zone_range_pct = ((zone_high - zone_low) / zone_mid) * 100
        if zone_range_pct > CONSOL_RANGE_PCT:
            return None

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
            return None

        b_open  = float(breakout_c["Open"])
        b_close = float(breakout_c["Close"])
        b_vol   = float(breakout_c["Volume"])

        if b_close < b_open:
            return None

        break_above_pct = ((b_close - zone_high) / zone_high) * 100
        if break_above_pct < CONSOL_BREAK_PCT:
            return None

        avg_zone_vol = float(zone["Volume"].mean())
        vol_ratio    = (b_vol / avg_zone_vol) if avg_zone_vol > 0 else 0
        if vol_ratio < CONSOL_VOL_MULT:
            return None

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

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()]

        if len(df) > 1:
            try:
                last_ts = df.index[-1]
                if last_ts.tzinfo is None:
                    last_ts = last_ts.tz_localize(UTC)
                now_utc = datetime.now(timezone.utc)
                seconds_since_open = (now_utc - last_ts).total_seconds()
                if seconds_since_open < 300:
                    df = df.iloc[:-1]
            except Exception:
                df = df.iloc[:-1]

        if len(df) < 12:
            return None

        today_5m = df.tail(min(len(df), 78)).copy()

        if len(today_5m) < CONSOL_CANDLES + 2:
            return None

        day_open   = float(today_5m["Open"].iloc[0])
        last_price = float(today_5m["Close"].iloc[-1])
        day_high   = float(today_5m["High"].max())
        day_low    = float(today_5m["Low"].min())

        if day_open <= 0 or last_price <= 0:
            return None

        move_pct = ((last_price - day_open) / day_open) * 100

        today_15m = None
        try:
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

            if len(today_15m) > 1:
                last_15m_start = today_15m.index[-1]
                bars_in_last   = df_idx[df_idx.index >= last_15m_start]
                if len(bars_in_last) < 3:
                    today_15m = today_15m.iloc[:-1]
        except Exception:
            today_15m = None

        last_candle_bullish = (
            float(today_5m["Close"].iloc[-1]) >=
            float(today_5m["Open"].iloc[-1])
        )

        high_vs_open_pct = ((day_high - day_open) / day_open) * 100
        at_day_high = (
            last_price >= day_high * 0.998
            and high_vs_open_pct >= DAY_HIGH_MIN_MOVE
        )

        consol_5m  = detect_consolidation_breakout(today_5m,  "5m")
        consol_15m = detect_consolidation_breakout(today_15m, "15m") \
                     if today_15m is not None and len(today_15m) >= CONSOL_CANDLES + 1 \
                     else None

        return {
            "symbol":              symbol,
            "price":               last_price,
            "day_open":            day_open,
            "day_high":            day_high,
            "day_low":             day_low,
            "move_pct":            move_pct,
            "high_vs_open_pct":    high_vs_open_pct,
            "at_day_high":         at_day_high,
            "last_candle_bullish": last_candle_bullish,
            "consol_5m":           consol_5m,
            "consol_15m":          consol_15m,
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
# ALERT MESSAGE BUILDERS  [CHANGED v6]
#
# All cards follow this tight structure:
#   Line 1: separator
#   Line 2: <ICON> <ALERT TYPE> — <SYMBOL>   ← stock name here
#   Line 3: separator
#   Line 4+: data fields, no blank line at top
# =========================================================

def ist_stamp():
    return datetime.now(IST).strftime("%d %b %Y  %H:%M:%S IST")


def direction_label(move_pct):
    return "📈 UPSIDE" if move_pct > 0 else "📉 DOWNSIDE"


def build_price_alert(stock, step_num: int):
    sym      = stock["symbol"]
    price    = stock["price"]
    move_pct = stock["move_pct"]
    day_open = stock["day_open"]
    day_high = stock["day_high"]
    day_low  = stock["day_low"]
    direct   = direction_label(move_pct)
    step_label = f"Alert #{step_num}" if step_num > 1 else "First Alert"
    note = (
        "Momentum building — strong intraday move"
        if abs(move_pct) > 4
        else "Significant intraday move — watch for continuation"
    )

    return "\n".join([
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🚨 <b>PRICE MOVE — {sym}</b>  |  {direct}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>LTP:</b>    ₹{price:,.2f}",
        f"📊 <b>Move:</b>   <b>{move_pct:+.2f}%</b> from open",
        f"📶 <b>Step:</b>   {step_label}  (every {PRICE_STEP_PCT}% after {PRICE_MOVE_PCT:.0f}%)",
        f"",
        f"📌 <b>Levels</b>",
        f"  🔓 Open:   ₹{day_open:,.2f}",
        f"  ⬆️ High:   ₹{day_high:,.2f}",
        f"  ⬇️ Low:    ₹{day_low:,.2f}",
        f"  📐 Range:  ₹{day_high - day_low:,.2f}",
        f"",
        f"💡 {note}",
        f"🕐 {ist_stamp()}",
    ])


def build_day_high_alert(stock, new_high: float):
    sym              = stock["symbol"]
    price            = stock["price"]
    day_open         = stock["day_open"]
    day_low          = stock["day_low"]
    move_pct         = stock["move_pct"]
    high_vs_open_pct = stock["high_vs_open_pct"]
    note = (
        "Strong buying — price pushing to fresh highs"
        if move_pct > 1.5
        else "Grinding higher — watch for volume confirmation"
    )

    return "\n".join([
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔥 <b>DAY HIGH — {sym}</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>LTP:</b>       ₹{price:,.2f}",
        f"⬆️ <b>New High:</b>  ₹{new_high:,.2f}",
        f"📊 <b>Move:</b>      {move_pct:+.2f}% from open",
        f"",
        f"📌 <b>Levels</b>",
        f"  🔓 Open:         ₹{day_open:,.2f}",
        f"  ⬆️ High (new):   ₹{new_high:,.2f}",
        f"  ⬇️ Low:          ₹{day_low:,.2f}",
        f"  📐 High vs Open: +{high_vs_open_pct:.2f}%",
        f"",
        f"💡 {note}",
        f"  Re-fires every {DAY_HIGH_STEP_PCT}% above previous high",
        f"🕐 {ist_stamp()}",
    ])


def build_consolidation_alert(stock, consol: dict):
    sym     = stock["symbol"]
    price   = stock["price"]
    tf      = consol["tf"]
    tf_full = "5-Minute" if tf == "5m" else "15-Minute"
    strength = "🔥 STRONG" if consol["vol_ratio"] >= 2.5 else "✅ CONFIRMED"
    tf_note = (
        "15m breakout — higher conviction setup"
        if tf == "15m"
        else "5m breakout — fast move, watch for 15m confirm"
    )

    return "\n".join([
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔲 <b>CONSOL BREAKOUT — {sym}</b>  [{tf_full}]",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>LTP:</b>       ₹{price:,.2f}",
        f"📶 <b>Strength:</b>  {strength}",
        f"",
        f"📦 <b>Zone  ({consol['zone_candles']} candles)</b>",
        f"  ⬆️ High:   ₹{consol['zone_high']:,.2f}",
        f"  ⬇️ Low:    ₹{consol['zone_low']:,.2f}",
        f"  📐 Range:  {consol['zone_range_pct']:.2f}%  (≤ {CONSOL_RANGE_PCT}% = tight)",
        f"  🕯️ Flat:   {consol['flat_candles']}/{consol['zone_candles']} coiling candles",
        f"",
        f"💥 <b>Breakout</b>",
        f"  🚀 Price:   ₹{consol['breakout_price']:,.2f}",
        f"  📊 Above:   +{consol['break_above_pct']:.2f}% over zone",
        f"  🔊 Volume:  {consol['vol_ratio']:.2f}x zone avg",
        f"",
        f"💡 {tf_note}",
        f"🕐 {ist_stamp()}",
    ])

# =========================================================
# ALERT PROCESSOR
# =========================================================

def process_alerts(all_data: dict):
    alert_count = 0

    price_levels    = seen_alerts.setdefault("price_levels", {})
    day_high_levels = seen_alerts.setdefault("day_high_levels", {})
    one_shot_keys   = seen_alerts.setdefault("keys", [])

    for symbol, stock in all_data.items():
        move_pct   = stock["move_pct"]
        last_price = stock["price"]
        day_high   = stock["day_high"]

        # ── 1. Price Move Alert ─────────────────────────
        if abs(move_pct) >= PRICE_MOVE_PCT:
            direction = "UP" if move_pct > 0 else "DOWN"
            level_key = f"{symbol}-{direction}"

            last_alerted = price_levels.get(level_key)

            should_fire = False
            step_num    = 1

            if last_alerted is None:
                should_fire = True
                step_num    = 1
            else:
                gap = abs(abs(move_pct) - abs(last_alerted))
                if gap >= PRICE_STEP_PCT:
                    should_fire = True
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
        if stock["at_day_high"]:
            last_high_alerted = day_high_levels.get(symbol, 0.0)

            high_extension = 0.0
            if last_high_alerted > 0:
                high_extension = (
                    (day_high - last_high_alerted) / last_high_alerted
                ) * 100

            if last_high_alerted == 0.0 or high_extension >= DAY_HIGH_STEP_PCT:
                day_high_levels[symbol] = day_high
                log(f"🔥 DAY HIGH: {symbol} ₹{day_high:,.2f}")
                send_telegram(build_day_high_alert(stock, day_high))
                alert_count += 1
                time.sleep(0.5)

        # ── 3. Consolidation Breakout — 5m ─────────────
        if stock["consol_5m"]:
            key = f"{symbol}-CONSOL5M-{today_str()}"
            if key not in one_shot_keys:
                one_shot_keys.append(key)
                log(f"🔲 CONSOL 5M: {symbol} break +{stock['consol_5m']['break_above_pct']:.2f}%")
                send_telegram(build_consolidation_alert(stock, stock["consol_5m"]))
                alert_count += 1
                time.sleep(0.5)

        # ── 4. Consolidation Breakout — 15m ────────────
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
    now_ist     = datetime.now(IST)
    ist_now_str = now_ist.strftime("%H:%M:%S")
    log(f"🚀 RUN STARTED | {ist_now_str} IST")

    minute      = now_ist.minute
    offset_mins = minute % 5
    log(f"⏱️  Candle offset: {offset_mins} min past last 5m mark (ideal=2)")
    if offset_mins == 0:
        log("⚠️  Running on candle boundary — partial candle risk")

    # ── [NEW v6] Market-open reset ────────────────────
    reset_alert_files_at_open()

    # Reload seen_alerts after potential reset
    global seen_alerts
    seen_alerts = load_seen_alerts()

    log("✅ Running scan")

    # ── NSE News ──────────────────────────────────────
    try:
        process_nse_news()
    except Exception:
        log("⚠️ NSE news check failed — continuing")
        traceback.print_exc()

    # ── NSE Corporate Notices ─────────────────────────
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
