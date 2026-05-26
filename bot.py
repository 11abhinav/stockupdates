# =============================================================================
# PRODUCTION NSE MOMENTUM BOT - RAILWAY SAFE VERSION
# =============================================================================
#
# WHAT THIS BOT DOES
# -----------------------------------------------------------------------------
#
# ✅ Uses TradingView Screener as PRIMARY data source
# ✅ Uses your custom watchlist only
# ✅ Avoids NSE direct scraping completely
# ✅ Uses lightweight yfinance confirmation only
# ✅ Detects momentum breakout stocks
# ✅ Calculates RSI using ta library
# ✅ EMA trend confirmation
# ✅ Volume spike detection
# ✅ Telegram alerts
# ✅ Excel export using openpyxl
# ✅ Parquet export using pyarrow
# ✅ Progress tracking using tqdm
# ✅ Railway/VPS optimized
# ✅ Retry-safe architecture
# ✅ Cron-safe execution
# ✅ Minimal API calls
#
# =============================================================================
# WHY THIS VERSION IS STABLE
# =============================================================================
#
# ❌ NO NSE scraping
# ❌ NO session refresh loops
# ❌ NO cookie handling
# ❌ NO browser emulation
# ❌ NO repeated quote API hits
#
# ✅ TradingView handles screening
# ✅ yfinance used only for confirmation
# ✅ Lower API traffic
# ✅ Safer for Railway shared IPs
#
# =============================================================================

import os
import time
import traceback
import logging
import requests
import pandas as pd
import numpy as np
import yfinance as yf

from tqdm import tqdm
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from tradingview_screener import Query
from datetime import datetime

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

log = logging.getLogger("momentum_bot")

# =============================================================================
# ENV VARIABLES
# =============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# =============================================================================
# CONFIG
# =============================================================================

EXPORT_FOLDER = "exports"

os.makedirs(EXPORT_FOLDER, exist_ok=True)

RSI_MIN = 60
PRICE_CHANGE_MIN = 2
VOLUME_RATIO_MIN = 1.5

EMA_FAST = 20
EMA_SLOW = 50

STRONG_SCORE = 6

# =============================================================================
# CUSTOM WATCHLIST
# =============================================================================

WATCHLIST = [
    "ADANIENT",
    "ADANIGREEN",
    "ADANIPORTS",
    "AKZOINDIA",
    "ANANTRAJ",
    "ASIANPAINT",
    "ATGL",
    "BAJAJFINSV",
    "BEL",
    "BLS",
    "BLUEDART",
    "CASTROLIND",
    "CGPOWER",
    "CLEAN",
    "COALINDIA",
    "DBL",
    "EIDPARRY",
    "FILATEX",
    "FORTIS",
    "GILLETTE",
    "GSFC",
    "HDFCBANK",
    "HINDCOPPER",
    "HINDUNILVR",
    "ICICIBANK",
    "IDBI",
    "IFCI",
    "INDUSTOWER",
    "INFY",
    "IRB",
    "IRCTC",
    "JIOFIN",
    "JSWENERGY",
    "LATENTVIEW",
    "LLOYDSENGG",
    "LT",
    "MARUTI",
    "MAZDOCK",
    "NATCOPHARM",
    "ONGC",
    "ORIENTCEM",
    "PFC",
    "PIDILITIND",
    "POONAWALLA",
    "PVRINOX",
    "RELIANCE",
    "RVNL",
    "SBIN",
    "SUZLON",
    "SWIGGY",
    "SYMPHONY",
    "TATATECH",
    "TITAN",
    "TRENT",
]

# =============================================================================
# TELEGRAM
# =============================================================================

def send_telegram(message):

    if not BOT_TOKEN or not CHAT_ID:
        return

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message[:4096],
            },
            timeout=20,
        )

    except Exception:
        traceback.print_exc()

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
# TRADINGVIEW SCREENER
# =============================================================================

def fetch_tradingview_stocks():

    try:

        log.info("Fetching TradingView screener data")

        _, df = (
            Query()
            .select(
                "name",
                "close",
                "volume",
                "change",
                "RSI",
            )
            .where(
                "exchange == 'NSE'",
                "change > 1",
                "RSI > 55",
            )
            .limit(200)
            .get_scanner_data()
        )

        if df is None or df.empty:
            return pd.DataFrame()

        return df

    except Exception:

        traceback.print_exc()

        return pd.DataFrame()

# =============================================================================
# YFINANCE CONFIRMATION
# =============================================================================

def fetch_confirmation_data(symbol):

    try:

        df = yf.download(
            f"{symbol}.NS",
            period="6mo",
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna()

        if len(df) < 60:
            return None

        return df

    except Exception:

        traceback.print_exc()

        return None

# =============================================================================
# TECHNICALS
# =============================================================================

def calculate_rsi(close):

    try:

        indicator = RSIIndicator(close=close, window=14)

        return safe_float(
            indicator.rsi().iloc[-1],
            50,
        )

    except Exception:
        return 50.0

def calculate_ema(close, period):

    try:

        indicator = EMAIndicator(
            close=close,
            window=period,
        )

        return safe_float(
            indicator.ema_indicator().iloc[-1],
            0,
        )

    except Exception:
        return 0.0

# =============================================================================
# SCORE ENGINE
# =============================================================================

def compute_score(
    change_pct,
    volume_ratio,
    rsi,
    breakout,
    ema_bullish,
):

    score = 0

    if change_pct >= PRICE_CHANGE_MIN:
        score += 2

    if volume_ratio >= VOLUME_RATIO_MIN:
        score += 2

    if breakout:
        score += 2

    if rsi >= RSI_MIN:
        score += 2

    if ema_bullish:
        score += 2

    return score

# =============================================================================
# EXPORT RESULTS
# =============================================================================

def export_results(df):

    try:

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        parquet_file = (
            f"{EXPORT_FOLDER}/"
            f"momentum_{timestamp}.parquet"
        )

        excel_file = (
            f"{EXPORT_FOLDER}/"
            f"momentum_{timestamp}.xlsx"
        )

        df.to_parquet(
            parquet_file,
            engine="pyarrow",
            index=False,
        )

        df.to_excel(
            excel_file,
            engine="openpyxl",
            index=False,
        )

        log.info("Exports completed")

    except Exception:

        traceback.print_exc()

# =============================================================================
# MAIN ENGINE
# =============================================================================

def run():

    log.info("Momentum scan started")

    tv_df = fetch_tradingview_stocks()

    if tv_df.empty:

        log.warning("No TradingView data")

        return

    tv_symbols = set(tv_df["name"].tolist())

    filtered_watchlist = [
        s for s in WATCHLIST
        if s in tv_symbols
    ]

    log.info(
        "Filtered watchlist size: %s",
        len(filtered_watchlist),
    )

    results = []

    for symbol in tqdm(
        filtered_watchlist,
        desc="Scanning",
    ):

        try:

            row = tv_df[
                tv_df["name"] == symbol
            ].iloc[0]

            change_pct = safe_float(
                row["change"]
            )

            tv_volume = safe_float(
                row["volume"]
            )

            tv_rsi = safe_float(
                row["RSI"]
            )

            hist = fetch_confirmation_data(symbol)

            if hist is None:
                continue

            close = hist["Close"].astype(float)
            high = hist["High"].astype(float)
            volume = hist["Volume"].astype(float)

            avg_volume = safe_float(
                volume.rolling(20).mean().iloc[-1]
            )

            high20 = safe_float(
                high.rolling(20).max().iloc[-1]
            )

            current_price = safe_float(
                close.iloc[-1]
            )

            rsi = calculate_rsi(close)

            ema20 = calculate_ema(
                close,
                EMA_FAST,
            )

            ema50 = calculate_ema(
                close,
                EMA_SLOW,
            )

            ema_bullish = ema20 > ema50

            breakout = current_price >= high20

            volume_ratio = (
                tv_volume / avg_volume
            ) if avg_volume > 0 else 0

            score = compute_score(
                change_pct,
                volume_ratio,
                rsi,
                breakout,
                ema_bullish,
            )

            result = {
                "symbol": symbol,
                "price": round(current_price, 2),
                "change_pct": round(change_pct, 2),
                "rsi": round(rsi, 2),
                "volume_ratio": round(volume_ratio, 2),
                "ema20": round(ema20, 2),
                "ema50": round(ema50, 2),
                "breakout": breakout,
                "score": score,
            }

            results.append(result)

            if score >= STRONG_SCORE:

                msg = (
                    f"🚀 STRONG MOMENTUM\n\n"
                    f"Stock: {symbol}\n"
                    f"Score: {score}/10\n"
                    f"Price: ₹{current_price:.2f}\n"
                    f"Move: {change_pct:+.2f}%\n"
                    f"RSI: {rsi:.1f}\n"
                    f"Volume Ratio: {volume_ratio:.1f}x\n"
                    f"EMA20 > EMA50: {ema_bullish}\n"
                    f"Breakout: {breakout}"
                )

                send_telegram(msg)

                log.info(
                    "ALERT SENT %s Score=%s",
                    symbol,
                    score,
                )

            time.sleep(1)

        except Exception:

            traceback.print_exc()

    if results:

        df = pd.DataFrame(results)

        df = df.sort_values(
            by="score",
            ascending=False,
        )

        export_results(df)

        print("\nTOP MOMENTUM STOCKS\n")

        print(df.head(15))

    log.info("Scan completed")

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
            "BOT CRASHED"
        )
