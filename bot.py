# =============================================================================
# NSE MOMENTUM + BREAKOUT + NEWS BOT - FINAL STABLE VERSION v6
# =============================================================================
#
# WHAT THIS BOT DOES
# -----------------------------------------------------------------------------
# 1. Uses NSE API for LIVE prices
# 2. Uses Yahoo Finance only for historical candles
# 3. Detects momentum and breakouts
# 4. Sends Telegram alerts
# 5. Fetches Google News RSS
# 6. Fetches BSE corporate announcements
# 7. Prevents duplicate alerts
# 8. Railway-safe stable production architecture
#
# =============================================================================
# FIXES APPLIED
# =============================================================================
#
# FIXED:
# -------
# - TradingView failures
# - float(series) errors
# - yfinance MultiIndex issues
# - Telegram failures
# - duplicate RSS alerts
# - Railway crashes
# - invalid dataframe conversions
#
# IMPORTANT CHANGE:
# -----------------
# TradingView REMOVED.
#
# NSE API now used for:
# - live prices
# - intraday moves
#
# This is MUCH more stable on Railway/VPS.
# =============================================================================

import os
import logging
import traceback
import requests
import feedparser
import pandas as pd
import numpy as np
import yfinance as yf

from datetime import datetime, timedelta, timezone

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
# NORMALIZE YFINANCE
# =============================================================================

def normalize_yf_df(df):

    if df is None or df.empty:
        return None

    try:

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.loc[:, ~df.columns.duplicated()].copy()

        cols = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]

        for col in cols:

            if col not in df.columns:
                return None

            if isinstance(df[col], pd.DataFrame):
                df[col] = df[col].iloc[:, 0]

            df[col] = pd.Series(df[col]).astype(float)

        return df.dropna()

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

    return safe_float(rsi.iloc[-1], 50)

# =============================================================================
# YFINANCE HISTORICAL
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
# NSE LIVE DATA
# =============================================================================

session = requests.Session()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def prime_nse():

    try:

        session.get(
            "https://www.nseindia.com",
            headers=HEADERS,
            timeout=10,
        )

    except:
        pass

prime_nse()

def fetch_nse_live(symbol):

    try:

        url = (
            "https://www.nseindia.com/api/"
            f"quote-equity?symbol={symbol}"
        )

        r = session.get(
            url,
            headers=HEADERS,
            timeout=10,
        )

        data = r.json()

        price = data["priceInfo"]

        ltp = safe_float(price.get("lastPrice"))

        prev_close = safe_float(
            price.get("previousClose")
        )

        day_high = safe_float(
            price["intraDayHighLow"].get("max")
        )

        total_volume = safe_float(
            data.get("securityWiseDP", {})
            .get("quantityTraded")
        )

        change_pct = (
            ((ltp - prev_close) / prev_close) * 100
            if prev_close > 0 else 0
        )

        return {
            "ltp": ltp,
            "change_pct": change_pct,
            "day_high": day_high,
            "volume": total_volume,
        }

    except Exception:

        log.warning(
            "NSE fetch failed for %s",
            symbol,
        )

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

            for symbol in WATCHLIST:

                if symbol in title.upper():

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

    except Exception:
        traceback.print_exc()

# =============================================================================
# SCORE ENGINE
# =============================================================================

def compute_score(change_pct, vol_ratio, rsi, breakout):

    score = 0

    if abs(change_pct) >= PRICE_CHANGE_MIN:
        score += 2

    if vol_ratio >= VOLUME_RATIO_MIN:
        score += 2

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

    log.info("Momentum bot started")

    for symbol in WATCHLIST:

        try:

            log.info("Checking %s", symbol)

            hist = fetch_historical_data(symbol)

            if hist is None:
                continue

            live = fetch_nse_live(symbol)

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

            rsi = compute_rsi(close)

            ltp = safe_float(live["ltp"])

            if ltp <= 0:
                continue

            if avg_vol10 <= 0:
                continue

            vol_ratio = (
                live["volume"] / avg_vol10
            ) if avg_vol10 > 0 else 0

            breakout = ltp >= high20

            score = compute_score(
                live["change_pct"],
                vol_ratio,
                rsi,
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
                    f"Move: {live['change_pct']:+.2f}%\n"
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
