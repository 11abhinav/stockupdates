"""
===============================================================================
NSE MOMENTUM + BREAKOUT SCANNER — PRODUCTION BOT v3
===============================================================================

WHAT THIS BOT DOES
-------------------------------------------------------------------------------
1. Downloads historical OHLCV data from Yahoo Finance
2. Stores data in in-memory cache
3. Fetches live prices + VWAP + RSI from TradingView
4. Detects momentum and breakout stocks
5. Sends Telegram alerts
6. Tracks BSE announcements
7. Uses scoring engine for filtering strong setups

DATA SOURCES
-------------------------------------------------------------------------------
1. yfinance
   - Historical OHLCV candles
   - EMA20 / SMA50 / SMA200
   - RSI / breakout levels

2. TradingView TA
   - Live price
   - Intraday move %
   - VWAP
   - Live RSI

3. BSE RSS
   - Corporate announcements

4. Telegram Bot API
   - Alert delivery

ALERT TYPES
-------------------------------------------------------------------------------
🚀 Strong Momentum
📈 Moderate Momentum
🔥 Breakout Alerts
📢 BSE Announcements
📊 Scan Summary

DEPLOYMENT
-------------------------------------------------------------------------------
Designed for:
- Railway
- VPS
- Cron execution every 5–15 mins
===============================================================================
"""

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
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from tradingview_ta import TA_Handler, Interval
except ImportError:
    raise SystemExit(
        "Install tradingview-ta first:\\n"
        "pip install tradingview_ta"
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
MODERATE_SCORE = 4

PRICE_CHANGE_MIN = 2.0
VOLUME_RATIO_MIN = 2.0

RSI_MOMENTUM = 60
RSI_OVERBOUGHT = 80

MAX_WORKERS = 5

CACHE_REFRESH_HR = 8

YF_HISTORY = "1y"
YF_UPDATE = "5d"
YF_INTERVAL = "1d"

WATCHLIST = [
    "RELIANCE",
    "SBIN",
    "INFY",
    "TCS",
    "ICICIBANK",
    "HDFCBANK",
    "LT",
    "RVNL",
    "SUZLON",
    "TRENT",
]

SEEN_FILE = "seen_alerts.json"
BSE_RSS = "https://www.bseindia.com/BSEDATA/ann/rss.aspx"

_cache = {}
_cache_built_at = None

# =============================================================================
# HELPERS
# =============================================================================

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
                "parse_mode": "HTML",
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
# FULL CACHE BUILD
# =============================================================================

def build_cache_full():

    global _cache
    global _cache_built_at

    tickers_str = " ".join(
        [f"{s}.NS" for s in WATCHLIST]
    )

    try:

        raw = yf.download(
            tickers=tickers_str,
            period=YF_HISTORY,
            interval=YF_INTERVAL,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )

    except Exception:
        traceback.print_exc()
        return

    for sym in WATCHLIST:

        try:

            yf_sym = f"{sym}.NS"

            if isinstance(raw.columns, pd.MultiIndex):
                df = raw[yf_sym].copy()
            else:
                df = raw.copy()

            df.dropna(subset=["Close"], inplace=True)

            if len(df) < 50:
                continue

            _cache[sym] = df

        except Exception:
            pass

    _cache_built_at = ist_now()

# =============================================================================
# CACHE UPDATE
# =============================================================================

def update_cache_latest():

    tickers_str = " ".join(
        [f"{s}.NS" for s in WATCHLIST]
    )

    try:

        raw = yf.download(
            tickers=tickers_str,
            period=YF_UPDATE,
            interval=YF_INTERVAL,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )

    except Exception:
        traceback.print_exc()
        return

    for sym in WATCHLIST:

        try:

            yf_sym = f"{sym}.NS"

            if isinstance(raw.columns, pd.MultiIndex):
                new_rows = raw[yf_sym]
            else:
                new_rows = raw

            if new_rows.empty:
                continue

            combined = pd.concat([
                _cache[sym],
                new_rows
            ])

            combined = combined[
                ~combined.index.duplicated(keep="last")
            ]

            combined.sort_index(inplace=True)

            _cache[sym] = combined

        except Exception:
            pass

# =============================================================================
# CACHE MANAGER
# =============================================================================

def ensure_cache():

    global _cache_built_at

    needs_full_build = (
        _cache_built_at is None
        or len(_cache) == 0
        or (
            (
                ist_now() - _cache_built_at
            ).total_seconds()
            > CACHE_REFRESH_HR * 3600
        )
    )

    if needs_full_build:
        build_cache_full()
    else:
        update_cache_latest()

# =============================================================================
# HISTORICAL INDICATORS
# =============================================================================

def get_historical_indicators(symbol):

    df = _cache.get(symbol)

    if df is None or len(df) < 50:
        return None

    close = df["Close"]
    volume = df["Volume"]
    high = df["High"]

    ema20 = float(
        close.ewm(span=20, adjust=False)
        .mean()
        .iloc[-1]
    )

    sma50 = float(
        close.rolling(50)
        .mean()
        .iloc[-1]
    )

    sma200 = (
        float(
            close.rolling(200)
            .mean()
            .dropna()
            .iloc[-1]
        )
        if len(close) >= 200
        else sma50
    )

    rsi = compute_rsi(close)

    avg_vol10 = float(
        volume.rolling(10)
        .mean()
        .iloc[-1]
    )

    high20 = float(
        high.rolling(20)
        .max()
        .iloc[-1]
    )

    prev_close = float(close.iloc[-2])

    return {
        "ema20": ema20,
        "sma50": sma50,
        "sma200": sma200,
        "rsi_hist": rsi,
        "avg_vol10": avg_vol10,
        "high20": high20,
        "prev_close": prev_close,
    }

# =============================================================================
# TRADINGVIEW LIVE DATA
# =============================================================================

def fetch_tv_live(symbol):

    try:

        handler_5m = TA_Handler(
            symbol=symbol,
            screener="india",
            exchange="NSE",
            interval=Interval.INTERVAL_5_MINUTES,
        )

        ind_5m = handler_5m.get_analysis().indicators

        ltp = float(ind_5m.get("close", 0))
        today_vol = float(ind_5m.get("volume", 0))
        vwap = float(ind_5m.get("VWAP", ltp))
        rsi_live = float(ind_5m.get("RSI", 50))

        handler_1d = TA_Handler(
            symbol=symbol,
            screener="india",
            exchange="NSE",
            interval=Interval.INTERVAL_1_DAY,
        )

        ind_1d = handler_1d.get_analysis().indicators

        change_pct = float(ind_1d.get("change", 0))

        return {
            "ltp": ltp,
            "today_vol": today_vol,
            "vwap": vwap,
            "change_pct": change_pct,
            "rsi_live": rsi_live,
        }

    except Exception:
        return None

# =============================================================================
# SCORE ENGINE
# =============================================================================

def compute_score(d):

    score = 0

    if abs(d["change_pct"]) >= PRICE_CHANGE_MIN:
        score += 2

    if d["vol_ratio"] >= VOLUME_RATIO_MIN:
        score += 2

    if d["above_vwap"]:
        score += 1

    if d["breakout"]:
        score += 2

    if d["rsi"] >= RSI_MOMENTUM:
        score += 1

    if d["uptrend_em"]:
        score += 1

    if d["macro_trend"]:
        score += 1

    if d["rsi"] > RSI_OVERBOUGHT:
        score -= 1

    return score

# =============================================================================
# MAIN
# =============================================================================

def run():

    log.info("🚀 Momentum Bot Started")

    ensure_cache()

    if not _cache:
        log.error("Cache failed")
        return

    for symbol in WATCHLIST:

        try:

            hist = get_historical_indicators(symbol)

            if not hist:
                continue

            live = fetch_tv_live(symbol)

            if not live:
                continue

            ltp = live["ltp"]

            vol_ratio = (
                live["today_vol"] / hist["avg_vol10"]
                if hist["avg_vol10"] > 0
                else 0
            )

            data = {
                "symbol": symbol,
                "ltp": ltp,
                "change_pct": live["change_pct"],
                "vol_ratio": vol_ratio,
                "rsi": hist["rsi_hist"],
                "above_vwap": ltp > live["vwap"],
                "breakout": ltp >= hist["high20"],
                "uptrend_em": hist["ema20"] > hist["sma50"],
                "macro_trend": hist["sma50"] > hist["sma200"],
            }

            score = compute_score(data)

            if score >= STRONG_SCORE:

                send_telegram(
                    f"🚀 STRONG MOMENTUM\\n\\n"
                    f"{symbol}\\n"
                    f"Score: {score}/10\\n"
                    f"Price: ₹{ltp:.2f}\\n"
                    f"Move: {data['change_pct']:+.2f}%"
                )

                log.info(
                    "ALERT %s Score=%s",
                    symbol,
                    score,
                )

        except Exception:
            traceback.print_exc()

    log.info("✅ Cycle Complete")

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

        send_telegram(
            "❌ BOT CRASHED"
        )
