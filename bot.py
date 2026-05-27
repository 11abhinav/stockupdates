# =============================================================================
# MOMENTUM BOT — PRODUCTION v3
# All failures logged explicitly. No silent swallowing.
# =============================================================================

import os
import sys
import time
import json
import traceback
import logging
import requests
import feedparser
import pandas as pd
import numpy as np
import yfinance as yf
import email.utils

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange
from datetime import datetime, timezone, timedelta

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
log = logging.getLogger("momentum_bot")

# =============================================================================
# ENV
# =============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")

if not BOT_TOKEN:
    log.warning("ENV: BOT_TOKEN is not set — Telegram alerts disabled")
if not CHAT_ID:
    log.warning("ENV: CHAT_ID is not set — Telegram alerts disabled")

# =============================================================================
# CONFIG
# =============================================================================

EXPORT_FOLDER    = "exports"
ALERTS_FILE      = "alerts_sent.json"
BSE_ALERTS_FILE  = "bse_alerts.json"
NEWS_ALERTS_FILE = "news_alerts.json"

BSE_API_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    "?strCat=-1&strPrevDate=&strScrip=&strSearch=P&strToDate=&strType=C&subcategory=-1"
)
BSE_RSS_URLS = [
    "https://www.bseindia.com/BSEDATA/ann/20/rss.aspx",
    "https://www.bseindia.com/BSEDATA/ann/rss20.aspx",
]
BSE_HEADERS = {
    "User-Agent"     : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept"         : "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin"         : "https://www.bseindia.com",
    "Referer"        : "https://www.bseindia.com/",
}

NIFTY_TICKERS    = ["^NSEI", "NIFTYBEES.NS", "%5ENSEI"]

RSI_MIN          = 55
PRICE_CHANGE_MIN = 1.5
VOLUME_RATIO_MIN = 1.5
EMA_FAST         = 20
EMA_SLOW         = 50
EMA_TREND        = 200
STRONG_SCORE     = 8
FRESH_HOURS      = 12   # max age for news/BSE alerts

os.makedirs(EXPORT_FOLDER, exist_ok=True)

# =============================================================================
# WATCHLIST
# =============================================================================

WATCHLIST = [
    "ADANIENT", "ADANIGREEN", "ADANIPORTS", "AKZOINDIA", "ANANTRAJ",
    "ASIANPAINT", "ATGL", "BAJAJFINSV", "BEL", "BLS", "BLUEDART",
    "CASTROLIND", "CGPOWER", "CLEAN", "COALINDIA", "DBL", "EIDPARRY",
    "FILATEX", "FORTIS", "GILLETTE", "GSFC", "HDFCBANK", "HINDCOPPER",
    "HINDUNILVR", "ICICIBANK", "IDBI", "IFCI", "INDUSTOWER", "INFY",
    "IRB", "IRCTC", "JIOFIN", "JSWENERGY", "LATENTVIEW", "LLOYDSENGG",
    "LT", "MARUTI", "MAZDOCK", "NATCOPHARM", "ONGC", "ORIENTCEM",
    "PFC", "PIDILITIND", "POONAWALLA", "PVRINOX", "RELIANCE", "RVNL",
    "SBIN", "SUZLON", "SWIGGY", "SYMPHONY", "TATATECH", "TITAN", "TRENT",
]

# =============================================================================
# BSE CODE → NSE SYMBOL MAP
# Match on SCRIP_CD from BSE API — never substring-match headline text.
# This prevents false positives like "LT" hitting "resuLTs" or "RESULTS".
# =============================================================================

BSE_CODE_TO_NSE = {
    "500410": "ADANIENT",
    "541450": "ADANIGREEN",
    "532921": "ADANIPORTS",
    "500710": "AKZOINDIA",
    "541523": "ANANTRAJ",
    "500820": "ASIANPAINT",
    "543529": "ATGL",
    "532978": "BAJAJFINSV",
    "500049": "BEL",
    "543579": "BLS",
    "526612": "BLUEDART",
    "500870": "CASTROLIND",
    "541137": "CGPOWER",
    "590061": "CLEAN",
    "533278": "COALINDIA",
    "534816": "DBL",
    "500116": "EIDPARRY",
    "526227": "FILATEX",
    "532779": "FORTIS",
    "507815": "GILLETTE",
    "500690": "GSFC",
    "500180": "HDFCBANK",
    "513599": "HINDCOPPER",
    "500696": "HINDUNILVR",
    "532174": "ICICIBANK",
    "500116": "IDBI",
    "500106": "IFCI",
    "534816": "INDUSTOWER",
    "500209": "INFY",
    "532947": "IRB",
    "542830": "IRCTC",
    "543940": "JIOFIN",
    "533148": "JSWENERGY",
    "540005": "LATENTVIEW",
    "539275": "LLOYDSENGG",
    "500510": "LT",
    "532500": "MARUTI",
    "543237": "MAZDOCK",
    "524816": "NATCOPHARM",
    "500312": "ONGC",
    "502165": "ORIENTCEM",
    "532810": "PFC",
    "500331": "PIDILITIND",
    "543277": "POONAWALLA",
    "532344": "PVRINOX",
    "500325": "RELIANCE",
    "542649": "RVNL",
    "500112": "SBIN",
    "532667": "SUZLON",
    "543288": "SWIGGY",
    "517385": "SYMPHONY",
    "544028": "TATATECH",
    "500114": "TITAN",
    "500251": "TRENT",
}

# =============================================================================
# TELEGRAM
# =============================================================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("TELEGRAM: skipped — BOT_TOKEN or CHAT_ID missing")
        return
    try:
        url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": message[:4096]},
            timeout=20,
        )
        if resp.ok:
            log.info("TELEGRAM: message sent OK")
        else:
            log.error("TELEGRAM: send failed — HTTP %s | %s", resp.status_code, resp.text[:300])
    except Exception as exc:
        log.error("TELEGRAM: exception — %s", exc)
        traceback.print_exc()

# =============================================================================
# JSON HELPERS
# =============================================================================

def load_json_file(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as exc:
        log.error("JSON load failed [%s]: %s", path, exc)
        return {}

def save_json_file(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        log.error("JSON save failed [%s]: %s", path, exc)
        traceback.print_exc()

# =============================================================================
# ALERT DEDUP
# =============================================================================

def already_alerted(symbol):
    alerts = load_json_file(ALERTS_FILE)
    today  = datetime.now().strftime("%Y-%m-%d")
    return alerts.get(symbol) == today

def mark_alert_sent(symbol):
    alerts        = load_json_file(ALERTS_FILE)
    alerts[symbol] = datetime.now().strftime("%Y-%m-%d")
    save_json_file(ALERTS_FILE, alerts)

# =============================================================================
# HELPERS
# =============================================================================

def safe_float(value, default=0.0):
    try:
        if isinstance(value, pd.Series):
            value = value.iloc[-1]
        return float(value)
    except Exception as exc:
        log.debug("safe_float failed: %s — returning default %s", exc, default)
        return default

# =============================================================================
# FRESHNESS CHECK  (news + BSE)
# =============================================================================

def is_within_hours(dt_or_str, hours=FRESH_HOURS, label="entry"):
    """
    Returns True if the datetime is within the last N hours.
    Accepts a datetime object, ISO string, or RFC 2822 string.
    Returns False (block) if date cannot be determined.
    """
    import time as _time
    now = datetime.now(timezone.utc)

    # Already a datetime
    if isinstance(dt_or_str, datetime):
        dt = dt_or_str
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (now - dt).total_seconds()
        log.debug("FRESHNESS [%s]: age=%.1fh limit=%sh", label, age/3600, hours)
        return age <= hours * 3600

    # feedparser struct_time tuple
    if isinstance(dt_or_str, tuple):
        try:
            dt = datetime.fromtimestamp(_time.mktime(dt_or_str), tz=timezone.utc)
            age = (now - dt).total_seconds()
            log.debug("FRESHNESS [%s]: age=%.1fh limit=%sh", label, age/3600, hours)
            return age <= hours * 3600
        except Exception as exc:
            log.warning("FRESHNESS [%s]: struct_time parse failed — %s — BLOCKING", label, exc)
            return False

    # String
    s = str(dt_or_str).strip()
    if not s:
        log.warning("FRESHNESS [%s]: empty date string — BLOCKING", label)
        return False

    # Try ISO format first (BSE API: "2024-05-27T10:30:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (now - dt).total_seconds()
        log.debug("FRESHNESS [%s]: ISO age=%.1fh limit=%sh", label, age/3600, hours)
        return age <= hours * 3600
    except ValueError:
        pass

    # Try RFC 2822 (RSS: "Tue, 27 May 2026 10:30:00 +0530")
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (now - dt).total_seconds()
        log.debug("FRESHNESS [%s]: RFC2822 age=%.1fh limit=%sh", label, age/3600, hours)
        return age <= hours * 3600
    except Exception as exc:
        log.warning("FRESHNESS [%s]: all date parsers failed for %r — %s — BLOCKING", label, s, exc)
        return False

def feed_entry_fresh(entry, label="news"):
    """Extract date from feedparser entry and check freshness."""
    # feedparser pre-parsed tuple is most reliable
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return is_within_hours(parsed, label=label)
    # Fall back to raw string
    raw = entry.get("published", "") or entry.get("updated", "")
    return is_within_hours(raw, label=label)

# =============================================================================
# NEWS ALERTS
# =============================================================================

def check_news(symbol):
    try:
        alerts = load_json_file(NEWS_ALERTS_FILE)
        today  = datetime.now().strftime("%Y-%m-%d")
        url    = f"https://news.google.com/rss/search?q={symbol}+NSE+stock"

        feed = feedparser.parse(url)
        if not feed.entries:
            log.debug("NEWS [%s]: no entries in feed", symbol)
            return

        entry = feed.entries[0]
        pub   = entry.get("published", "no-date")

        if not feed_entry_fresh(entry, label=f"news/{symbol}"):
            log.info("NEWS [%s]: skipped — older than %sh (published: %s)", symbol, FRESH_HOURS, pub)
            return

        title = entry.get("title", "")
        link  = entry.get("link", "")
        key   = f"{symbol}_{title}"

        if alerts.get(key) == today:
            log.debug("NEWS [%s]: already alerted today", symbol)
            return

        msg = (
            f"📰 NEWS ALERT\n\n"
            f"Stock    : {symbol}\n"
            f"Published: {pub}\n\n"
            f"{title}\n\n{link}"
        )
        send_telegram(msg)
        alerts[key] = today
        save_json_file(NEWS_ALERTS_FILE, alerts)
        log.info("NEWS [%s]: alert sent", symbol)

    except Exception as exc:
        log.error("NEWS [%s]: unexpected error — %s", symbol, exc)
        traceback.print_exc()

# =============================================================================
# BSE ANNOUNCEMENTS
# =============================================================================

def fetch_bse_via_api():
    """BSE JSON API with session warmup. Returns list of {title,link,published} or None."""
    try:
        session = requests.Session()
        session.headers.update(BSE_HEADERS)

        log.info("BSE API: warming up session via homepage")
        warmup = session.get("https://www.bseindia.com", timeout=10)
        log.info("BSE API: warmup → HTTP %s", warmup.status_code)

        resp = session.get(BSE_API_URL, timeout=15)
        log.info("BSE API: data → HTTP %s | %d bytes", resp.status_code, len(resp.content))

        if resp.status_code != 200:
            log.error("BSE API: bad status %s — body: %s", resp.status_code, resp.text[:300])
            return None

        data = resp.json()
        rows = data.get("Table", [])
        if not rows:
            log.warning("BSE API: Table is empty. Response keys: %s", list(data.keys()))
            return None

        entries = [
            {
                "title"     : row.get("HEADLINE", ""),
                "link"      : row.get("NSURL", ""),
                "published" : row.get("NEWS_DT", ""),
                "scrip_cd"  : str(row.get("SCRIP_CD", "")).strip(),
                "scrip_name": row.get("SCRIP_NAME", ""),
            }
            for row in rows
        ]
        log.info("BSE API: OK — %d entries, latest: %s | sample scrip_cd: %s",
                 len(entries), entries[0].get("published"), entries[0].get("scrip_cd"))
        return entries

    except Exception as exc:
        log.error("BSE API: exception — %s", exc)
        traceback.print_exc()
        return None

def fetch_bse_via_rss():
    """RSS fallback. Returns same shape as API, or None."""
    for url in BSE_RSS_URLS:
        try:
            log.info("BSE RSS: trying %s", url)
            resp = requests.get(url, headers=BSE_HEADERS, timeout=15)
            log.info("BSE RSS: HTTP %s | %d bytes", resp.status_code, len(resp.content))

            if resp.status_code != 200:
                log.warning("BSE RSS: HTTP %s for %s", resp.status_code, url)
                continue

            feed = feedparser.parse(resp.content)
            if not feed.entries:
                log.warning("BSE RSS: 0 entries from %s", url)
                continue

            entries = [
                {
                    "title"    : e.get("title", ""),
                    "link"     : e.get("link", ""),
                    "published": e.get("published", "") or e.get("updated", ""),
                }
                for e in feed.entries
            ]
            log.info("BSE RSS: OK — %d entries from %s", len(entries), url)
            return entries

        except Exception as exc:
            log.error("BSE RSS: exception for %s — %s", url, exc)
            traceback.print_exc()

    log.error("BSE RSS: all URLs failed")
    return None

def check_bse_announcements():
    try:
        log.info("BSE: starting announcement check")
        alerts = load_json_file(BSE_ALERTS_FILE)
        today  = datetime.now().strftime("%Y-%m-%d")

        entries = fetch_bse_via_api() or fetch_bse_via_rss()

        if not entries:
            log.error("BSE: all sources failed — no announcements this run")
            return

        matched = skipped_old = skipped_dup = skipped_nomatch = 0

        for entry in entries[:60]:
            raw_title  = entry.get("title", "")
            link       = entry.get("link", "")
            pub_str    = entry.get("published", "")
            scrip_cd   = entry.get("scrip_cd", "")
            scrip_name = entry.get("scrip_name", "")

            if not is_within_hours(pub_str, label=f"BSE/{raw_title[:40]}"):
                skipped_old += 1
                continue

            # PRIMARY: match via BSE scrip code — exact, no false positives
            symbol = BSE_CODE_TO_NSE.get(scrip_cd)

            # FALLBACK (RSS has no scrip_cd): whole-word match on scrip_name or title
            # Use \b word boundaries to prevent "LT" matching "RESULTS"
            if symbol is None:
                import re
                for s in WATCHLIST:
                    pattern = rf"\b{re.escape(s)}\b"
                    if re.search(pattern, scrip_name.upper()) or \
                       re.search(pattern, raw_title.upper()):
                        symbol = s
                        break

            if symbol is None:
                log.debug("BSE: no watchlist match — scrip_cd=%s scrip_name=%s title=%s",
                          scrip_cd, scrip_name, raw_title[:60])
                skipped_nomatch += 1
                continue

            key = f"{symbol}_{raw_title[:120]}"
            if alerts.get(key) == today:
                skipped_dup += 1
                continue

            msg = (
                f"📢 BSE ANNOUNCEMENT\n\n"
                f"Stock    : {symbol}\n"
                f"Company  : {scrip_name}\n"
                f"Published: {pub_str}\n"
                f"Notice   : {raw_title}\n\n"
                f"{link}"
            )
            send_telegram(msg)
            alerts[key] = today
            matched += 1
            log.info("BSE ALERT: %s | %s | scrip_cd=%s", symbol, raw_title[:60], scrip_cd)

        save_json_file(BSE_ALERTS_FILE, alerts)
        log.info(
            "BSE: done — %d sent | %d old | %d dup | %d no-match",
            matched, skipped_old, skipped_dup, skipped_nomatch,
        )

    except Exception as exc:
        log.error("BSE: unexpected error — %s", exc)
        traceback.print_exc()

# =============================================================================
# YFINANCE
# =============================================================================

def fetch_stock_data(symbol):
    for attempt in range(3):
        try:
            df = yf.download(
                f"{symbol}.NS",
                period="1y",
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            if df is None or df.empty:
                log.warning("STOCK [%s]: empty download (attempt %d)", symbol, attempt + 1)
                time.sleep(3)
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.dropna()

            if len(df) < 60:
                log.warning("STOCK [%s]: only %d rows after dropna — need 60, skipping", symbol, len(df))
                return None

            return df

        except Exception as exc:
            log.error("STOCK [%s]: download error (attempt %d) — %s", symbol, attempt + 1, exc)
            traceback.print_exc()
            time.sleep(3)

    log.error("STOCK [%s]: all 3 download attempts failed", symbol)
    return None

def fetch_nifty_returns(period_days=20):
    """Return Nifty50 % change over last N trading days."""
    for ticker in NIFTY_TICKERS:
        try:
            log.info("NIFTY: downloading %s", ticker)
            df = yf.download(
                ticker,
                period="3mo",
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            if df is None or df.empty:
                log.warning("NIFTY [%s]: empty download", ticker)
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.dropna()
            log.info("NIFTY [%s]: %d rows downloaded", ticker, len(df))

            if len(df) < period_days + 1:
                log.warning("NIFTY [%s]: only %d rows, need %d", ticker, len(df), period_days + 1)
                continue

            close = df["Close"].astype(float)
            ret   = (close.iloc[-1] - close.iloc[-period_days]) / close.iloc[-period_days] * 100
            log.info("NIFTY [%s]: %d-day return = %.2f%%", ticker, period_days, float(ret))
            return float(ret)

        except Exception as exc:
            log.error("NIFTY [%s]: exception — %s", ticker, exc)
            traceback.print_exc()

    log.error("NIFTY: all tickers failed — relative strength will be 0.0")
    return 0.0

# =============================================================================
# TECHNICALS
# =============================================================================

def calculate_rsi(close, symbol="?"):
    try:
        val = safe_float(RSIIndicator(close=close, window=14).rsi().iloc[-1], 50)
        return val
    except Exception as exc:
        log.error("RSI [%s]: %s", symbol, exc)
        return 50.0

def calculate_ema(close, period, symbol="?"):
    try:
        return EMAIndicator(close=close, window=period).ema_indicator()
    except Exception as exc:
        log.error("EMA%d [%s]: %s", period, symbol, exc)
        return pd.Series(dtype=float)

def calculate_macd_crossover(close, symbol="?"):
    try:
        m          = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
        macd_line  = m.macd()
        signal_line= m.macd_signal()
        for i in range(-1, -4, -1):
            if macd_line.iloc[i] > signal_line.iloc[i] and macd_line.iloc[i-1] <= signal_line.iloc[i-1]:
                return True
        return False
    except Exception as exc:
        log.error("MACD [%s]: %s", symbol, exc)
        return False

def candle_strength(open_s, close_s, high_s, low_s, symbol="?"):
    try:
        o = float(open_s.iloc[-1])
        c = float(close_s.iloc[-1])
        h = float(high_s.iloc[-1])
        l = float(low_s.iloc[-1])
        total_range = h - l
        if total_range == 0:
            return 0.0
        return max(0.0, (c - o) / total_range)
    except Exception as exc:
        log.error("CANDLE [%s]: %s", symbol, exc)
        return 0.0

def is_consolidation_breakout(high, close, symbol="?", lookback=15):
    try:
        prior_high   = float(high.iloc[-lookback:-1].max())
        recent_close = close.iloc[-lookback:-1]
        std_pct      = float(recent_close.std() / recent_close.mean() * 100)
        current      = float(close.iloc[-1])
        return std_pct < 3.0 and current > prior_high
    except Exception as exc:
        log.error("CONSOL [%s]: %s", symbol, exc)
        return False

def ath_proximity_pct(high, symbol="?"):
    try:
        ath     = float(high.iloc[-252:].max()) if len(high) >= 252 else float(high.max())
        current = float(high.iloc[-1])
        return ((ath - current) / ath) * 100
    except Exception as exc:
        log.error("ATH [%s]: %s", symbol, exc)
        return 100.0

# =============================================================================
# SCORE ENGINE  (max = 14)
# =============================================================================

def compute_score(signals):
    score = 0
    if signals["price_change"]          >= PRICE_CHANGE_MIN: score += 2
    if signals["volume_ratio"]          >= VOLUME_RATIO_MIN: score += 2
    if signals["rsi"]                   >= RSI_MIN:          score += 2
    if signals["breakout_20d"]:                               score += 2
    if signals["golden_cross"]:                               score += 1
    if signals["macd_crossover"]:                             score += 1
    if signals["consolidation_breakout"]:                     score += 2
    if signals["candle_strength"]       > 0.6:               score += 1
    if signals["ath_proximity_pct"]     < 5:                  score += 1
    return score

# =============================================================================
# EXPORT
# =============================================================================

def export_results(df):
    try:
        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        parquet_path = f"{EXPORT_FOLDER}/momentum_{ts}.parquet"
        excel_path   = f"{EXPORT_FOLDER}/momentum_{ts}.xlsx"
        df.to_parquet(parquet_path, engine="pyarrow", index=False)
        df.to_excel(excel_path, engine="openpyxl", index=False)
        log.info("EXPORT: saved → %s", excel_path)
    except Exception as exc:
        log.error("EXPORT: failed — %s", exc)
        traceback.print_exc()

# =============================================================================
# MAIN SCAN
# =============================================================================

def run():
    log.info("=" * 60)
    log.info("SCAN START")
    log.info("=" * 60)

    nifty_20d    = fetch_nifty_returns(20)
    results      = []
    total        = len(WATCHLIST)
    skipped      = 0

    for index, symbol in enumerate(WATCHLIST, start=1):
        try:
            log.info("─── [%d/%d] %s", index, total, symbol)

            hist = fetch_stock_data(symbol)
            if hist is None:
                skipped += 1
                continue

            close  = hist["Close"].astype(float)
            high   = hist["High"].astype(float)
            low    = hist["Low"].astype(float)
            open_  = hist["Open"].astype(float)
            volume = hist["Volume"].astype(float)

            current_price = safe_float(close.iloc[-1])
            prev_close    = safe_float(close.iloc[-2])

            if prev_close == 0:
                log.warning("STOCK [%s]: prev_close=0, skipping", symbol)
                skipped += 1
                continue

            change_pct   = (current_price - prev_close) / prev_close * 100
            avg_volume   = safe_float(volume.rolling(20).mean().iloc[-1])
            volume_ratio = (float(volume.iloc[-1]) / avg_volume) if avg_volume > 0 else 0

            high20       = safe_float(high.rolling(20).max().iloc[-2])
            breakout_20d = current_price > high20

            rsi      = calculate_rsi(close, symbol)
            ema20_s  = calculate_ema(close, EMA_FAST, symbol)
            ema50_s  = calculate_ema(close, EMA_SLOW, symbol)
            ema200_s = calculate_ema(close, EMA_TREND, symbol)

            if ema20_s.empty or ema50_s.empty:
                log.warning("STOCK [%s]: EMA calculation returned empty — skipping", symbol)
                skipped += 1
                continue

            ema20      = safe_float(ema20_s.iloc[-1])
            ema50      = safe_float(ema50_s.iloc[-1])
            ema20_prev = safe_float(ema20_s.iloc[-2])
            ema50_prev = safe_float(ema50_s.iloc[-2])
            ema200     = safe_float(ema200_s.iloc[-1]) if not ema200_s.empty else 0

            golden_cross = ema20 > ema50 and ema20_prev <= ema50_prev
            above_200    = current_price > ema200 if ema200 > 0 else True

            macd_x   = calculate_macd_crossover(close, symbol)
            consol_x = is_consolidation_breakout(high, close, symbol)
            cstrength = candle_strength(open_, close, high, low, symbol)
            ath_pct  = ath_proximity_pct(high, symbol)

            close_20d    = safe_float(close.iloc[-20])
            stock_20d    = ((current_price - close_20d) / close_20d * 100) if close_20d > 0 else 0
            rel_strength = stock_20d - nifty_20d

            signals = {
                "price_change"          : change_pct,
                "volume_ratio"          : volume_ratio,
                "rsi"                   : rsi,
                "breakout_20d"          : breakout_20d,
                "golden_cross"          : golden_cross,
                "macd_crossover"        : macd_x,
                "consolidation_breakout": consol_x,
                "candle_strength"       : cstrength,
                "ath_proximity_pct"     : ath_pct,
                "above_200ema"          : above_200,
                "rel_strength_vs_nifty" : rel_strength,
            }

            score = compute_score(signals)

            log.info(
                "STOCK [%s]: price=%.2f chg=%.2f%% rsi=%.1f vol=%.1fx score=%d/14",
                symbol, current_price, change_pct, rsi, volume_ratio, score,
            )

            results.append({
                "symbol"        : symbol,
                "price"         : round(current_price, 2),
                "change_pct"    : round(change_pct, 2),
                "rsi"           : round(rsi, 2),
                "volume_ratio"  : round(volume_ratio, 2),
                "ema20"         : round(ema20, 2),
                "ema50"         : round(ema50, 2),
                "ema200"        : round(ema200, 2),
                "golden_cross"  : golden_cross,
                "macd_crossover": macd_x,
                "breakout_20d"  : breakout_20d,
                "consol_breakout": consol_x,
                "candle_str"    : round(cstrength, 2),
                "ath_prox_pct"  : round(ath_pct, 2),
                "rel_str_nifty" : round(rel_strength, 2),
                "above_200ema"  : above_200,
                "score"         : score,
            })

            check_news(symbol)

            if score >= STRONG_SCORE and not already_alerted(symbol):
                fired = []
                if change_pct   >= PRICE_CHANGE_MIN: fired.append(f"📈 Price +{change_pct:.1f}%")
                if volume_ratio >= VOLUME_RATIO_MIN:  fired.append(f"🔊 Volume {volume_ratio:.1f}x avg")
                if rsi          >= RSI_MIN:           fired.append(f"⚡ RSI {rsi:.0f}")
                if breakout_20d:                      fired.append("🚀 20-day Breakout")
                if consol_x:                          fired.append("📦 Consolidation Breakout")
                if golden_cross:                      fired.append("✨ Golden Cross")
                if macd_x:                            fired.append("🔁 MACD Crossover")
                if cstrength > 0.6:                   fired.append(f"🕯 Strong Candle ({cstrength:.0%})")
                if ath_pct   < 5:                     fired.append(f"🏔 Near ATH ({ath_pct:.1f}% away)")
                if above_200:                         fired.append("📊 Above 200 EMA")
                if rel_strength > 3:                  fired.append(f"💪 RS vs Nifty +{rel_strength:.1f}%")

                msg = (
                    f"🚀 STRONG BREAKOUT SETUP\n"
                    f"{'─'*28}\n"
                    f"Stock : {symbol}\n"
                    f"Score : {score}/14\n"
                    f"Price : ₹{current_price:.2f}\n\n"
                    f"Signals fired:\n"
                    + "\n".join(f"  {s}" for s in fired)
                )
                send_telegram(msg)
                mark_alert_sent(symbol)
                log.info("ALERT [%s]: sent score=%d/14", symbol, score)

            time.sleep(1)

        except Exception as exc:
            log.error("STOCK [%s]: unhandled error — %s", symbol, exc)
            traceback.print_exc()
            skipped += 1

    if results:
        df = pd.DataFrame(results).sort_values("score", ascending=False)
        export_results(df)
        print("\n── TOP MOMENTUM STOCKS ──")
        print(
            df[["symbol", "score", "price", "change_pct", "rsi",
                "volume_ratio", "breakout_20d", "consol_breakout",
                "golden_cross", "macd_crossover", "ath_prox_pct",
                "rel_str_nifty"]].head(15).to_string(index=False)
        )
    else:
        log.error("SCAN: no results produced — check download errors above")

    check_bse_announcements()

    log.info("=" * 60)
    log.info("SCAN DONE — %d processed | %d skipped", total - skipped, skipped)
    log.info("=" * 60)

# =============================================================================
# ENTRY — cron-safe, single-run
# =============================================================================
#
# Crontab (IST = UTC+5:30):
#   # Market open 09:20 IST
#   50 3 * * 1-5  python3 /app/bot.py >> /var/log/bot.log 2>&1
#   # Mid-session 12:00 IST
#   30 6 * * 1-5  python3 /app/bot.py >> /var/log/bot.log 2>&1
#   # Market close 15:35 IST
#   5 10 * * 1-5  python3 /app/bot.py >> /var/log/bot.log 2>&1
#   # BSE only every 30 min during market hours
#   */30 3-10 * * 1-5  python3 /app/bot.py --bse-only >> /var/log/bot.log 2>&1
#
# Flags:
#   --dry-run   full scan, no Telegram sends
#   --bse-only  BSE announcements only, skip stock scan
#
# =============================================================================

if __name__ == "__main__":
    dry_run  = "--dry-run"  in sys.argv
    bse_only = "--bse-only" in sys.argv

    if dry_run:
        log.info("MODE: DRY-RUN — Telegram suppressed")
        def send_telegram(msg):
            log.info("[DRY-RUN MSG] %s", msg[:200])

    IST = timezone(timedelta(hours=5, minutes=30))
    log.info(
        "BOT START | IST=%s | dry_run=%s | bse_only=%s",
        datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), dry_run, bse_only,
    )

    try:
        if bse_only:
            check_bse_announcements()
        else:
            run()
    except KeyboardInterrupt:
        log.info("BOT: stopped by user")
    except Exception as exc:
        log.critical("BOT: fatal crash — %s", exc)
        traceback.print_exc()
        send_telegram("❌ BOT CRASHED — check logs")

    log.info(
        "BOT EXIT | IST=%s",
        datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
    )
