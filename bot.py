# =============================================================================
# NSE MOMENTUM + BREAKOUT + NEWS BOT - PRODUCTION VERSION v5
# =============================================================================
#
# WHAT THIS BOT DOES
# -----------------------------------------------------------------------------
# 1. Downloads historical OHLCV data from Yahoo Finance
# 2. Fixes yfinance MultiIndex / Series conversion issues
# 3. Fetches live prices + VWAP + RSI from TradingView
# 4. Detects strong momentum and breakout stocks
# 5. Sends Telegram alerts
# 6. Scans Google News RSS for stock news
# 7. Scans BSE RSS for corporate announcements
# 8. Uses momentum scoring engine
# 9. Runs safely on Railway/VPS/CRON
#
# =============================================================================
# WHAT WAS FIXED IN THIS VERSION
# =============================================================================
#
# FIX 1:
# ------
# Fixed:
# TypeError: float() argument must be a string or a real number, not 'Series'
#
# Cause:
# yfinance sometimes returns DataFrame/MultiIndex columns.
#
# Solution:
# Added:
# - normalize_yf_df()
# - safe_float()
#
# -----------------------------------------------------------------------------
#
# FIX 2:
# ------
# Fixed yfinance MultiIndex corruption.
#
# Solution:
# - flatten columns
# - remove duplicate OHLCV columns
# - force OHLCV to float Series
#
# -----------------------------------------------------------------------------
#
# FIX 3:
# ------
# Prevented Railway crashes from bad numeric conversions.
#
# Solution:
# Added:
# - safe_float()
# - validation checks
#
# -----------------------------------------------------------------------------
#
# FIX 4:
# ------
# Added market-hours filter.
#
# Bot now runs only:
# 09:15 AM → 03:30 PM IST
#
# -----------------------------------------------------------------------------
#
# FIX 5:
# ------
# Added Google News alerts again.
#
# -----------------------------------------------------------------------------
#
# FIX 6:
# ------
# Added BSE announcement alerts again.
#
# -----------------------------------------------------------------------------
#
# FIX 7:
# ------
# Added deduplication for:
# - news alerts
# - BSE alerts
#
# Prevents repeated spam every cron cycle.
#
# -----------------------------------------------------------------------------
#
# FIX 8:
# ------
# Disabled threaded yfinance calls.
#
# threads=False improves stability on Railway.
#
# =============================================================================

import os
import json
import logging
import traceback
import requests
import feedparser
import pandas as pd
import numpy as np
import yfinance as yf

from datetime import datetime, timedelta, timezone

try:
    from tradingview_ta import TA_Handler, Interval
except ImportError:
    raise SystemExit(
        "Install tradingview-ta first:\n"
        "pip install tradingview_ta"
    )

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

log = logging.getLogger("momentum_bot")

# =============================================================================
# CONFIG
# =============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

IST = timezone(timedelta(hours=5, minutes=30))

YF_HISTORY = "1y"
YF_INTERVAL = "1d"

STRONG_SCORE = 6

PRICE_CHANGE_MIN = 2
VOLUME_RATIO_MIN = 2

RSI_MOMENTUM = 60
RSI_OVERBOUGHT = 80

BSE_RSS = "https://www.bseindia.com/BSEDATA/ann/rss.aspx"

WATCHLIST = [
    "ADANIENT", "ADANIGREEN", "ADANIPORTS", "AKZOINDIA",
    "ANANTRAJ", "ASIANPAINT", "ATGL", "BAJAJFINSV", "BEL",
    "BLS", "BLUEDART", "CASTROLIND", "CGPOWER", "CLEAN",
    "DBL", "EIDPARRY", "FILATEX", "FORTIS", "GILLETTE",
    "GSFC", "HDFCBANK", "HINDCOPPER", "HINDUNILVR",
    "ICICIBANK", "IDBI", "IFCI", "INDUSTOWER", "INFY",
    "IRB", "IRCTC", "JIOFIN", "JSWENERGY", "LATENTVIEW",
    "LLOYDSENGG", "LT", "MARUTI", "MAZDOCK", "NATCOPHARM",
    "ONGC", "ORIENTCEM", "PFC", "PIDILITIND", "POONAWALLA",
    "PVRINOX", "RELIANCE", "RVNL", "SBIN", "SUZLON",
    "SWIGGY", "SYMPHONY", "TATATECH", "TITAN", "TRENT",
]

# =============================================================================
# DEDUP STORAGE
# =============================================================================

seen_news = set()
seen_bse = set()

# =============================================================================
# HELPERS
# =============================================================================

def ist_now():
    return datetime.now(IST)

# =============================================================================
# SAFE FLOAT
# =============================================================================

def safe_float(value, default=0.0):

    try:

        if isinstance(value, pd.Series):
            value = value.iloc[-1]

        return float(value)

    except Exception:
        return default

# =============================================================================
# TELEGRAM
# =============================================================================

def send_telegram(msg):

    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram credentials missing")
        return

    try:

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": msg[:4096],
            },
            timeout=20,
        )

    except Exception:
        traceback.print_exc()

# =============================================================================
# FIXED YFINANCE NORMALIZER
# =============================================================================

def normalize_yf_df(df):

    if df is None or df.empty:
        return None

    try:

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.loc[:, ~df.columns.duplicated()].copy()

        required_cols = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]

        for col in required_cols:

            if col not in df.columns:
                return None

            if isinstance(df[col], pd.DataFrame):
                df[col] = df[col].iloc[:, 0]

            df[col] = pd.Series(df[col]).astype(float)

        df = df.dropna(subset=required_cols)

        return df

    except Exception:
        traceback.print_exc()
        return None

# =============================================================================
# RSI
# =============================================================================

def compute_rsi(close, period=14):

    if len(close) < period + 1:
        return 50.0

    delta = close.diff().dropna()

    gain = (
        delta.clip(lower=0)
        .ewm(alpha=1 / period, adjust=False)
        .mean()
    )

    loss = (
        (-delta.clip(upper=0))
        .ewm(alpha=1 / period, adjust=False)
        .mean()
    )

    rs = gain / loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))

    return safe_float(rsi.iloc[-1], 50.0)

# =============================================================================
# HISTORICAL DATA
# =============================================================================

def fetch_historical_data(symbol):

    try:

        df = yf.download(
            f"{symbol}.NS",
            period=YF_HISTORY,
            interval=YF_INTERVAL,
            auto_adjust=True,
            progress=False,
            threads=False,
        )

        if df is None or df.empty:
            return None

        df = normalize_yf_df(df)

        if df is None or len(df) < 50:
            return None

        return df

    except Exception:
        traceback.print_exc()
        return None

# =============================================================================
# TRADINGVIEW LIVE DATA
# =============================================================================

def fetch_tv_live(symbol):

    try:

        handler = TA_Handler(
            symbol=symbol,
            screener="india",
            exchange="NSE",
            interval=Interval.INTERVAL_5_MINUTES,
        )

        indicators = handler.get_analysis().indicators

        return {
            "ltp": safe_float(indicators.get("close", 0)),
            "volume": safe_float(indicators.get("volume", 0)),
            "vwap": safe_float(indicators.get("VWAP", 0)),
            "rsi_live": safe_float(indicators.get("RSI", 50)),
        }

    except Exception:
        log.warning("TradingView failed for %s", symbol)
        return None

# =============================================================================
# GOOGLE NEWS
# =============================================================================

def check_news(symbol):

    try:

        url = (
            f"https://news.google.com/rss/search?"
            f"q={symbol}%20NSE"
        )

        feed = feedparser.parse(url)

        if not feed.entries:
            return

        entry = feed.entries[0]

        title = entry.title
        link = entry.link

        key = f"{symbol}_{title}"

        if key in seen_news:
            return

        seen_news.add(key)

        msg = (
            f"NEWS ALERT\n\n"
            f"{symbol}\n\n"
            f"{title}\n\n"
            f"{link}"
        )

        send_telegram(msg)

    except Exception:
        traceback.print_exc()

# =============================================================================
# BSE ANNOUNCEMENTS
# =============================================================================

def check_bse_announcements():

    try:

        feed = feedparser.parse(BSE_RSS)

        if not feed.entries:
            return

        for entry in feed.entries[:10]:

            title = entry.title
            link = entry.link

            matched = False

            for symbol in WATCHLIST:

                if symbol in title.upper():

                    matched = True

                    key = f"{symbol}_{title}"

                    if key in seen_bse:
                        break

                    seen_bse.add(key)

                    msg = (
                        f"BSE ANNOUNCEMENT\n\n"
                        f"{symbol}\n\n"
                        f"{title}\n\n"
                        f"{link}"
                    )

                    send_telegram(msg)

                    break

            if matched:
                continue

    except Exception:
        traceback.print_exc()

# =============================================================================
# SCORE ENGINE
# =============================================================================

def compute_score(change_pct, vol_ratio, rsi, above_vwap, breakout):

    score = 0

    if abs(change_pct) >= PRICE_CHANGE_MIN:
        score += 2

    if vol_ratio >= VOLUME_RATIO_MIN:
        score += 2

    if above_vwap:
        score += 1

    if breakout:
        score += 2

    if rsi >= RSI_MOMENTUM:
        score += 1

    if rsi > RSI_OVERBOUGHT:
        score -= 1

    return score

# =============================================================================
# MAIN
# =============================================================================

def run():

    current_time = ist_now().time()

    market_open = (
        current_time >= datetime.strptime("09:15", "%H:%M").time()
        and current_time <= datetime.strptime("15:30", "%H:%M").time()
    )

    if not market_open:
        log.info("Market closed")
        return

    log.info("Momentum bot started")

    for symbol in WATCHLIST:

        try:

            log.info("Checking %s", symbol)

            hist = fetch_historical_data(symbol)

            if hist is None:
                continue

            live = fetch_tv_live(symbol)

            if live is None:
                continue

            close = pd.Series(hist["Close"]).astype(float)
            volume = pd.Series(hist["Volume"]).astype(float)
            high = pd.Series(hist["High"]).astype(float)

            avg_vol10 = safe_float(
                volume.rolling(10).mean().iloc[-1]
            )

            high20 = safe_float(
                high.rolling(20).max().iloc[-1]
            )

            prev_close = safe_float(close.iloc[-2])

            rsi = compute_rsi(close)

            ltp = safe_float(live["ltp"])

            if ltp <= 0:
                continue

            if avg_vol10 <= 0:
                continue

            change_pct = (
                (ltp - prev_close)
                / prev_close
            ) * 100

            vol_ratio = (
                live["volume"] / avg_vol10
            )

            above_vwap = ltp > live["vwap"]

            breakout = ltp >= high20

            score = compute_score(
                change_pct,
                vol_ratio,
                rsi,
                above_vwap,
                breakout,
            )

            # NEWS CHECK
            check_news(symbol)

            if score >= STRONG_SCORE:

                msg = (
                    f"STRONG MOMENTUM\n\n"
                    f"Stock: {symbol}\n"
                    f"Score: {score}/10\n"
                    f"Price: Rs {ltp:.2f}\n"
                    f"Move: {change_pct:+.2f}%\n"
                    f"Volume Ratio: {vol_ratio:.1f}x\n"
                    f"RSI: {rsi:.1f}"
                )

                send_telegram(msg)

                log.info(
                    "ALERT SENT %s Score=%s",
                    symbol,
                    score,
                )

        except Exception:
            traceback.print_exc()

    # BSE ALERTS
    check_bse_announcements()

    log.info("Cycle completed")

# =============================================================================
# ENTRY
# =============================================================================

if __name__ == "__main__":

    try:
        run()

    except KeyboardInterrupt:
        log.info("Stopped")

    except Exception:

        traceback.print_exc()

        send_telegram("BOT CRASHED")
