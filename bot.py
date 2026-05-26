# =============================================================================
# FINAL PRODUCTION MOMENTUM BOT - ULTRA STABLE VERSION
# =============================================================================
#
# FEATURES
# -----------------------------------------------------------------------------
#
# ✅ Uses ONLY yfinance
# ✅ Uses ONLY your custom watchlist
# ✅ NO NSE scraping
# ✅ NO TradingView dependency
# ✅ Railway-safe architecture
# ✅ RSI confirmation using ta library
# ✅ EMA trend confirmation
# ✅ Golden Cross detection
# ✅ Breakout detection
# ✅ Volume spike detection
# ✅ Duplicate alert prevention
# ✅ Telegram alerts
# ✅ BSE announcement alerts
# ✅ Excel export using openpyxl
# ✅ Parquet export using pyarrow
# ✅ Retry-safe structure
# ✅ Cron-safe execution
# ✅ Minimal API traffic
# ✅ Lightweight logs
#
# =============================================================================

import os
import time
import json
import traceback
import logging
import requests
import feedparser
import pandas as pd
import numpy as np
import yfinance as yf

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
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

ALERTS_FILE = "alerts_sent.json"
BSE_ALERTS_FILE = "bse_alerts.json"

BSE_RSS = "https://www.bseindia.com/BSEDATA/ann/rss.aspx"

os.makedirs(EXPORT_FOLDER, exist_ok=True)

RSI_MIN = 60
PRICE_CHANGE_MIN = 2
VOLUME_RATIO_MIN = 1.5

EMA_FAST = 20
EMA_SLOW = 50

STRONG_SCORE = 6

# =============================================================================
# WATCHLIST
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
# BSE NAME MAPPING
# =============================================================================

BSE_NAME_MAP = {
    "ADANIENT": ["ADANI ENTERPRISES"],
    "ADANIGREEN": ["ADANI GREEN ENERGY"],
    "ADANIPORTS": ["ADANI PORTS"],
    "AKZOINDIA": ["AKZO NOBEL INDIA"],
    "ANANTRAJ": ["ANANT RAJ"],
    "ASIANPAINT": ["ASIAN PAINTS"],
    "ATGL": ["ADANI TOTAL GAS"],
    "BAJAJFINSV": ["BAJAJ FINSERV"],
    "BEL": ["BHARAT ELECTRONICS"],
    "BLS": ["BLS INTERNATIONAL"],
    "BLUEDART": ["BLUE DART EXPRESS"],
    "CASTROLIND": ["CASTROL INDIA"],
    "CGPOWER": ["CG POWER AND INDUSTRIAL"],
    "CLEAN": ["CLEAN SCIENCE"],
    "COALINDIA": ["COAL INDIA"],
    "DBL": ["DILIP BUILDCON"],
    "EIDPARRY": ["E.I.D. PARRY"],
    "FILATEX": ["FILATEX INDIA"],
    "FORTIS": ["FORTIS HEALTHCARE"],
    "GILLETTE": ["GILLETTE INDIA"],
    "GSFC": ["GUJARAT STATE FERTILIZERS"],
    "HDFCBANK": ["HDFC BANK"],
    "HINDCOPPER": ["HINDUSTAN COPPER"],
    "HINDUNILVR": ["HINDUSTAN UNILEVER"],
    "ICICIBANK": ["ICICI BANK"],
    "IDBI": ["IDBI BANK"],
    "IFCI": ["IFCI LTD"],
    "INDUSTOWER": ["INDUS TOWERS"],
    "INFY": ["INFOSYS"],
    "IRB": ["IRB INFRASTRUCTURE"],
    "IRCTC": ["INDIAN RAILWAY CATERING"],
    "JIOFIN": ["JIO FINANCIAL SERVICES"],
    "JSWENERGY": ["JSW ENERGY"],
    "LATENTVIEW": ["LATENT VIEW ANALYTICS"],
    "LLOYDSENGG": ["LLOYDS ENGINEERING"],
    "LT": ["LARSEN AND TOUBRO"],
    "MARUTI": ["MARUTI SUZUKI"],
    "MAZDOCK": ["MAZAGON DOCK"],
    "NATCOPHARM": ["NATCO PHARMA"],
    "ONGC": ["OIL AND NATURAL GAS"],
    "ORIENTCEM": ["ORIENT CEMENT"],
    "PFC": ["POWER FINANCE CORPORATION"],
    "PIDILITIND": ["PIDILITE INDUSTRIES"],
    "POONAWALLA": ["POONAWALLA FINCORP"],
    "PVRINOX": ["PVR INOX"],
    "RELIANCE": ["RELIANCE INDUSTRIES"],
    "RVNL": ["RAIL VIKAS NIGAM"],
    "SBIN": ["STATE BANK OF INDIA"],
    "SUZLON": ["SUZLON ENERGY"],
    "SWIGGY": ["SWIGGY LTD"],
    "SYMPHONY": ["SYMPHONY LTD"],
    "TATATECH": ["TATA TECHNOLOGIES"],
    "TITAN": ["TITAN COMPANY"],
    "TRENT": ["TRENT LTD"],
}

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
# JSON HELPERS
# =============================================================================

def load_json_file(path):

    if not os.path.exists(path):
        return {}

    try:

        with open(path, "r") as f:
            return json.load(f)

    except Exception:
        return {}

def save_json_file(path, data):

    try:

        with open(path, "w") as f:
            json.dump(data, f)

    except Exception:
        traceback.print_exc()

# =============================================================================
# ALERT STORAGE
# =============================================================================

def already_alerted(symbol):

    alerts = load_json_file(ALERTS_FILE)

    today = datetime.now().strftime("%Y-%m-%d")

    return alerts.get(symbol) == today

def mark_alert_sent(symbol):

    alerts = load_json_file(ALERTS_FILE)

    today = datetime.now().strftime("%Y-%m-%d")

    alerts[symbol] = today

    save_json_file(ALERTS_FILE, alerts)

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
# BSE ANNOUNCEMENTS
# =============================================================================

def check_bse_announcements():

    try:

        log.info(
            "Checking BSE announcements"
        )

        alerts = load_json_file(
            BSE_ALERTS_FILE
        )

        today = datetime.now().strftime(
            "%Y-%m-%d"
        )

        feed = feedparser.parse(BSE_RSS)

        if not feed.entries:

            log.warning(
                "No BSE announcements found"
            )

            return

        for entry in feed.entries[:100]:

            title = entry.title.upper()
            link = entry.link

            for symbol in WATCHLIST:

                keywords = BSE_NAME_MAP.get(
                    symbol,
                    [symbol]
                )

                matched = any(
                    keyword in title
                    for keyword in keywords
                )

                if matched:

                    log.info(
                        "Matched BSE notice for %s",
                        symbol,
                    )

                    key = (
                        f"{symbol}_{title}"
                    )

                    if alerts.get(key) == today:
                        continue

                    msg = (
                        f"📢 BSE ANNOUNCEMENT\n\n"
                        f"Stock: {symbol}\n\n"
                        f"{entry.title}\n\n"
                        f"{link}"
                    )

                    send_telegram(msg)

                    alerts[key] = today

                    log.info(
                        "BSE alert sent for %s",
                        symbol,
                    )

        save_json_file(
            BSE_ALERTS_FILE,
            alerts,
        )

    except Exception:

        traceback.print_exc()

# =============================================================================
# YFINANCE DATA
# =============================================================================

def fetch_stock_data(symbol):

    for attempt in range(3):

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
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.dropna()

            if len(df) < 60:
                continue

            return df

        except Exception:

            traceback.print_exc()

            time.sleep(3)

    return None

# =============================================================================
# TECHNICALS
# =============================================================================

def calculate_rsi(close):

    try:

        indicator = RSIIndicator(
            close=close,
            window=14,
        )

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

        return indicator.ema_indicator()

    except Exception:
        return pd.Series(dtype=float)

# =============================================================================
# SCORE ENGINE
# =============================================================================

def compute_score(
    change_pct,
    volume_ratio,
    rsi,
    breakout,
    golden_cross,
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

    if golden_cross:
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

    results = []

    total_stocks = len(WATCHLIST)

    for index, symbol in enumerate(
        WATCHLIST,
        start=1,
    ):

        try:

            if index % 10 == 0:

                log.info(
                    "Processed %s/%s stocks",
                    index,
                    total_stocks,
                )

            hist = fetch_stock_data(symbol)

            if hist is None:
                continue

            close = hist["Close"].astype(float)
            high = hist["High"].astype(float)
            volume = hist["Volume"].astype(float)

            current_price = safe_float(
                close.iloc[-1]
            )

            prev_close = safe_float(
                close.iloc[-2]
            )

            change_pct = (
                (
                    current_price - prev_close
                )
                / prev_close
            ) * 100

            avg_volume = safe_float(
                volume.rolling(20).mean().iloc[-1]
            )

            volume_ratio = (
                volume.iloc[-1]
                / avg_volume
            ) if avg_volume > 0 else 0

            high20 = safe_float(
                high.rolling(20).max().iloc[-1]
            )

            breakout = current_price >= high20

            rsi = calculate_rsi(close)

            ema20_series = calculate_ema(
                close,
                EMA_FAST,
            )

            ema50_series = calculate_ema(
                close,
                EMA_SLOW,
            )

            if (
                ema20_series.empty
                or ema50_series.empty
            ):
                continue

            ema20 = safe_float(
                ema20_series.iloc[-1]
            )

            ema50 = safe_float(
                ema50_series.iloc[-1]
            )

            ema20_prev = safe_float(
                ema20_series.iloc[-2]
            )

            ema50_prev = safe_float(
                ema50_series.iloc[-2]
            )

            golden_cross = (
                ema20 > ema50
                and ema20_prev <= ema50_prev
            )

            score = compute_score(
                change_pct,
                volume_ratio,
                rsi,
                breakout,
                golden_cross,
            )

            result = {
                "symbol": symbol,
                "price": round(current_price, 2),
                "change_pct": round(change_pct, 2),
                "rsi": round(rsi, 2),
                "volume_ratio": round(volume_ratio, 2),
                "ema20": round(ema20, 2),
                "ema50": round(ema50, 2),
                "golden_cross": golden_cross,
                "breakout": breakout,
                "score": score,
            }

            results.append(result)

            if (
                score >= STRONG_SCORE
                and not already_alerted(symbol)
            ):

                msg = (
                    f"🚀 STRONG MOMENTUM\n\n"
                    f"Stock: {symbol}\n"
                    f"Score: {score}/10\n"
                    f"Price: ₹{current_price:.2f}\n"
                    f"Move: {change_pct:+.2f}%\n"
                    f"RSI: {rsi:.1f}\n"
                    f"Volume Ratio: {volume_ratio:.1f}x\n"
                    f"Golden Cross: {golden_cross}\n"
                    f"Breakout: {breakout}"
                )

                send_telegram(msg)

                mark_alert_sent(symbol)

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

    check_bse_announcements()

    log.info(
        "Completed scanning %s stocks",
        total_stocks,
    )

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

        send_telegram("BOT CRASHED")
