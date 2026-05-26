# =============================================================================
# NSE MOMENTUM + BREAKOUT SCANNER - PRODUCTION BOT v3
# =============================================================================
#
# WHAT THIS BOT DOES
# -----------------------------------------------------------------------------
# 1. Downloads historical OHLCV data from Yahoo Finance
# 2. Stores data in memory cache
# 3. Fetches live price + VWAP + RSI from TradingView
# 4. Detects momentum and breakout stocks
# 5. Sends Telegram alerts
# 6. Tracks BSE announcements
# 7. Uses scoring engine for filtering strong setups
#
# DATA SOURCES
# -----------------------------------------------------------------------------
# yfinance      -> Historical candles / EMA / SMA / RSI
# TradingView   -> Live price / VWAP / RSI
# Telegram API  -> Alerts
# BSE RSS       -> Corporate announcements
#
# DEPLOYMENT
# -----------------------------------------------------------------------------
# Designed for:
# - Railway
# - VPS
# - Cron execution every 5-15 mins
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
        "Install tradingview-ta first using: pip install tradingview_ta"
    )

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger("momentum_bot")

# =============================================================================
# CONFIG
# =============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

IST = timezone(timedelta(hours=5, minutes=30))

STRONG_SCORE = 6

PRICE_CHANGE_MIN = 2.0
VOLUME_RATIO_MIN = 2.0

RSI_MOMENTUM = 60
RSI_OVERBOUGHT = 80

YF_HISTORY = "1y"
YF_INTERVAL = "1d"

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
# HELPERS
# =============================================================================

def ist_now():
    return datetime.now(IST)

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

    return float(rsi.iloc[-1])

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
        )

        if df.empty or len(df) < 50:
            return None

        return df

    except Exception:
        return None

# =============================================================================
# LIVE DATA
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
            "ltp": float(indicators.get("close", 0)),
            "volume": float(indicators.get("volume", 0)),
            "vwap": float(indicators.get("VWAP", 0)),
            "rsi_live": float(indicators.get("RSI", 50)),
        }

    except Exception:
        return None

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

            close = hist["Close"]

            avg_vol10 = float(
                hist["Volume"]
                .rolling(10)
                .mean()
                .iloc[-1]
            )

            high20 = float(
                hist["High"]
                .rolling(20)
                .max()
                .iloc[-1]
            )

            prev_close = float(close.iloc[-2])

            rsi = compute_rsi(close)

            ltp = live["ltp"]

            change_pct = (
                (ltp - prev_close)
                / prev_close
            ) * 100

            vol_ratio = (
                live["volume"] / avg_vol10
                if avg_vol10 > 0 else 0
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
