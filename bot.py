# =============================================================================
# ENHANCED NSE MOMENTUM + BREAKOUT + NEWS BOT - FINAL VERSION v8
# =============================================================================
#
# FEATURES
# -----------------------------------------------------------------------------
# ✅ NSE live price fetch
# ✅ Yahoo Finance historical candles
# ✅ TradingView screener integration
# ✅ RSI using ta library
# ✅ EMA trend detection
# ✅ Breakout detection
# ✅ Volume spike detection
# ✅ Google News alerts
# ✅ BSE corporate announcements
# ✅ Telegram alerts
# ✅ Progress tracking with tqdm
# ✅ Parquet export using pyarrow
# ✅ Excel export using openpyxl
# ✅ Railway/VPS stable architecture
#
# =============================================================================
# REQUIRED LIBRARIES
# =============================================================================
# pandas
# numpy
# yfinance
# tradingview_screener
# ta
# pyarrow
# requests
# tqdm
# openpyxl
# =============================================================================

import os
import time
import logging
import traceback
import requests
import feedparser
import pandas as pd
import numpy as np
import yfinance as yf

from tqdm import tqdm
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from tradingview_screener import Query
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

EXPORT_FOLDER = "exports"
os.makedirs(EXPORT_FOLDER, exist_ok=True)

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
# TECHNICAL INDICATORS USING ta LIBRARY
# =============================================================================

def compute_rsi(close, period=14):

    try:

        rsi_indicator = RSIIndicator(close=close, window=period)
        rsi = rsi_indicator.rsi()

        return safe_float(rsi.iloc[-1], 50)

    except Exception:
        return 50.0


def compute_ema(close, period=20):

    try:

        ema_indicator = EMAIndicator(close=close, window=period)
        ema = ema_indicator.ema_indicator()

        return safe_float(ema.iloc[-1], 0)

    except Exception:
        return 0.0

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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}


def refresh_nse_session():

    global session

    try:

        session = requests.Session()

        session.get(
            "https://www.nseindia.com",
            headers=HEADERS,
            timeout=15,
        )

        log.info("NSE session refreshed")

    except Exception:
        traceback.print_exc()


refresh_nse_session()


def fetch_nse_live(symbol):

    global session

    url = (
        "https://www.nseindia.com/api/"
        f"quote-equity?symbol={symbol}"
    )

    for attempt in range(3):

        try:

            response = session.get(
                url,
                headers=HEADERS,
                timeout=15,
            )

            if response.status_code in [401, 403]:

                log.warning(
                    "NSE blocked session. Refreshing..."
                )

                refresh_nse_session()
                continue

            if response.status_code != 200:
                continue

            data = response.json()

            if "priceInfo" not in data:
                continue

            price = data["priceInfo"]

            ltp = safe_float(
                price.get("lastPrice")
            )

            prev_close = safe_float(
                price.get("previousClose")
            )

            volume = safe_float(
                data.get(
                    "securityWiseDP",
                    {}
                ).get("quantityTraded")
            )

            change_pct = (
                ((ltp - prev_close) / prev_close) * 100
                if prev_close > 0 else 0
            )

            return {
                "ltp": ltp,
                "change_pct": change_pct,
                "volume": volume,
            }

        except Exception:

            log.warning(
                "Retry %s failed for %s",
                attempt + 1,
                symbol,
            )

            time.sleep(2)

    return None

# =============================================================================
# TRADINGVIEW SCREENER
# =============================================================================

def get_tradingview_momentum_stocks():

    try:

        _, df = (
            Query()
            .select(
                'name',
                'close',
                'volume',
                'RSI',
                'change'
            )
            .where(
                'exchange == "NSE"',
                'RSI > 55',
                'change > 1'
            )
            .limit(20)
            .get_scanner_data()
        )

        if df is not None and not df.empty:
            log.info("TradingView screener fetched")
            return df

    except Exception:
        traceback.print_exc()

    return pd.DataFrame()

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

def compute_score(change_pct, vol_ratio, rsi, breakout, ema_bullish):

    score = 0

    if abs(change_pct) >= PRICE_CHANGE_MIN:
        score += 2

    if vol_ratio >= VOLUME_RATIO_MIN:
        score += 2

    if breakout:
        score += 2

    if rsi >= RSI_MOMENTUM:
        score += 1

    if ema_bullish:
        score += 2

    if rsi > RSI_OVERBOUGHT:
        score -= 1

    return score

# =============================================================================
# EXPORT RESULTS
# =============================================================================

def export_results(results_df):

    try:

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        parquet_file = os.path.join(
            EXPORT_FOLDER,
            f"momentum_results_{timestamp}.parquet"
        )

        excel_file = os.path.join(
            EXPORT_FOLDER,
            f"momentum_results_{timestamp}.xlsx"
        )

        results_df.to_parquet(
            parquet_file,
            engine="pyarrow",
            index=False,
        )

        results_df.to_excel(
            excel_file,
            engine="openpyxl",
            index=False,
        )

        log.info("Results exported")

    except Exception:
        traceback.print_exc()

# =============================================================================
# MAIN
# =============================================================================

def run():

    log.info("Momentum bot started")

    results = []

    tv_df = get_tradingview_momentum_stocks()

    if not tv_df.empty:
        log.info("TradingView Top Momentum Stocks:")
        log.info(tv_df.head())

    for symbol in tqdm(WATCHLIST, desc="Scanning Stocks"):

        try:

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

            ema20 = compute_ema(close, 20)
            ema50 = compute_ema(close, 50)

            ema_bullish = ema20 > ema50

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
                ema_bullish,
            )

            check_news(symbol)

            results.append({
                "symbol": symbol,
                "ltp": round(ltp, 2),
                "change_pct": round(live["change_pct"], 2),
                "volume_ratio": round(vol_ratio, 2),
                "rsi": round(rsi, 2),
                "ema20": round(ema20, 2),
                "ema50": round(ema50, 2),
                "breakout": breakout,
                "score": score,
            })

            if score >= STRONG_SCORE:

                msg = (
                    f"STRONG MOMENTUM\n\n"
                    f"Stock: {symbol}\n"
                    f"Score: {score}/10\n"
                    f"Price: Rs {ltp:.2f}\n"
                    f"Move: {live['change_pct']:+.2f}%\n"
                    f"Volume Ratio: {vol_ratio:.1f}x\n"
                    f"RSI: {rsi:.1f}\n"
                    f"EMA20 > EMA50: {ema_bullish}"
                )

                send_telegram(msg)

                log.info(
                    "ALERT SENT %s Score=%s",
                    symbol,
                    score,
                )

        except Exception:
            traceback.print_exc()

    check_bse_announcements()

    if results:

        results_df = pd.DataFrame(results)

        results_df = results_df.sort_values(
            by="score",
            ascending=False,
        )

        export_results(results_df)

        print("\nTOP MOMENTUM STOCKS\n")
        print(results_df.head(10))

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
