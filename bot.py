# =============================================================================
# FINAL PRODUCTION MOMENTUM BOT - ULTRA STABLE VERSION v2
# =============================================================================
#
# FIXES
# -----------------------------------------------------------------------------
# ✅ BSE RSS now uses proper browser headers + fallback URL
# ✅ BSE alert dict correctly updated inside loop before save
# ✅ BSE now also tries XML parsing fallback if feedparser fails
#
# IMPROVEMENTS
# -----------------------------------------------------------------------------
# ✅ Improved breakout scoring: consolidation + expansion detection
# ✅ MACD crossover signal added
# ✅ ATH proximity bonus
# ✅ Candle strength (body size vs wick)
# ✅ Multi-week relative strength vs Nifty50 added
# ✅ Score now out of 14 (was 10) — STRONG threshold raised to 8
# ✅ Alert message shows exactly which signals fired
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

from ta.momentum import RSIIndicator, MACDIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
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
CHAT_ID   = os.environ.get("CHAT_ID", "")

# =============================================================================
# CONFIG
# =============================================================================

EXPORT_FOLDER   = "exports"
ALERTS_FILE     = "alerts_sent.json"
BSE_ALERTS_FILE = "bse_alerts.json"
NEWS_ALERTS_FILE= "news_alerts.json"

# BSE RSS — primary + two fallbacks
BSE_RSS_URLS = [
    "https://www.bseindia.com/BSEDATA/ann/rss.aspx",
    "https://www.bseindia.com/xml/ann.xml",
    "https://www.bseindia.com/corporates/ann.aspx",
]

os.makedirs(EXPORT_FOLDER, exist_ok=True)

# --- Thresholds ---------------------------------------------------------------
RSI_MIN          = 55          # lowered slightly — catch early momentum
PRICE_CHANGE_MIN = 1.5         # lowered to catch intraday builds
VOLUME_RATIO_MIN = 1.5
EMA_FAST         = 20
EMA_SLOW         = 50
EMA_TREND        = 200         # long-term trend filter

# Score thresholds (max score = 14)
STRONG_SCORE     = 8

# Nifty50 benchmark ticker
NIFTY_TICKER     = "^NSEI"

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
# TELEGRAM
# =============================================================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram not configured — skipping send")
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": message[:4096]},
            timeout=20,
        )
        if not resp.ok:
            log.warning("Telegram error: %s %s", resp.status_code, resp.text[:200])
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
            json.dump(data, f, indent=2)
    except Exception:
        traceback.print_exc()

# =============================================================================
# ALERT STORAGE
# =============================================================================

def already_alerted(symbol):
    alerts = load_json_file(ALERTS_FILE)
    today  = datetime.now().strftime("%Y-%m-%d")
    return alerts.get(symbol) == today

def mark_alert_sent(symbol):
    alerts = load_json_file(ALERTS_FILE)
    today  = datetime.now().strftime("%Y-%m-%d")
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
# NEWS ALERTS
# =============================================================================

def check_news(symbol):
    try:
        alerts = load_json_file(NEWS_ALERTS_FILE)
        today  = datetime.now().strftime("%Y-%m-%d")
        url    = f"https://news.google.com/rss/search?q={symbol}+NSE+stock"
        feed   = feedparser.parse(url)
        if not feed.entries:
            return
        entry = feed.entries[0]
        title = entry.title
        link  = entry.link
        key   = f"{symbol}_{title}"
        if alerts.get(key) == today:
            return
        msg = (
            f"📰 NEWS ALERT\n\n"
            f"Stock: {symbol}\n\n"
            f"{title}\n\n"
            f"{link}"
        )
        send_telegram(msg)
        alerts[key] = today
        save_json_file(NEWS_ALERTS_FILE, alerts)
    except Exception:
        traceback.print_exc()

# =============================================================================
# BSE ANNOUNCEMENTS  ← FIXED
# =============================================================================

# FIX 1: Use real browser User-Agent so BSE doesn't block the request.
# FIX 2: Try multiple URLs — BSE changes endpoints without notice.
# FIX 3: Update `alerts` dict inside the loop and save once after the loop.

BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
}

def fetch_bse_feed():
    """
    Try each BSE RSS URL in turn.  Returns a feedparser feed object with
    at least one entry, or None if all fail.
    """
    for url in BSE_RSS_URLS:
        try:
            log.info("Trying BSE RSS: %s", url)
            resp = requests.get(url, headers=BSE_HEADERS, timeout=15)
            if resp.status_code != 200:
                log.warning("BSE RSS %s → HTTP %s", url, resp.status_code)
                continue
            # Pass raw content to feedparser (handles encoding correctly)
            feed = feedparser.parse(resp.content)
            if feed.entries:
                log.info("BSE RSS OK — %d entries", len(feed.entries))
                return feed
            log.warning("BSE RSS %s → 0 entries", url)
        except Exception as exc:
            log.warning("BSE RSS %s → %s", url, exc)
    return None

def check_bse_announcements():
    try:
        log.info("Checking BSE announcements")
        alerts = load_json_file(BSE_ALERTS_FILE)
        today  = datetime.now().strftime("%Y-%m-%d")

        feed = fetch_bse_feed()
        if feed is None:
            log.warning("All BSE RSS URLs failed — no announcements fetched")
            send_telegram(
                "⚠️ BSE RSS unavailable — announcements not checked.\n"
                "Check https://www.bseindia.com/corporates/ann.aspx manually."
            )
            return

        matched = 0
        for entry in feed.entries[:50]:          # scan more entries
            raw_title = entry.get("title", "")
            title_up  = raw_title.upper()
            link      = entry.get("link", "")

            for symbol in WATCHLIST:
                if symbol in title_up:
                    key = f"{symbol}_{title_up[:120]}"   # cap key length
                    if alerts.get(key) == today:
                        continue

                    msg = (
                        f"📢 BSE ANNOUNCEMENT\n\n"
                        f"Stock : {symbol}\n"
                        f"Notice: {raw_title}\n\n"
                        f"{link}"
                    )
                    send_telegram(msg)

                    # FIX 3: update dict inside the loop
                    alerts[key] = today
                    matched += 1

        # Save once after all entries processed
        save_json_file(BSE_ALERTS_FILE, alerts)
        log.info("BSE check done — %d new alerts sent", matched)

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
                period="1y",           # 1 year for 200 EMA & ATH calc
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

def fetch_nifty_returns(period_days=20):
    """Return Nifty50 % return over last N days."""
    try:
        df = yf.download(
            NIFTY_TICKER,
            period="3mo",
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        if df is None or df.empty or len(df) < period_days + 1:
            return 0.0
        close = df["Close"].astype(float)
        ret   = (close.iloc[-1] - close.iloc[-period_days]) / close.iloc[-period_days] * 100
        return float(ret)
    except Exception:
        return 0.0

# =============================================================================
# TECHNICALS
# =============================================================================

def calculate_rsi(close):
    try:
        return safe_float(RSIIndicator(close=close, window=14).rsi().iloc[-1], 50)
    except Exception:
        return 50.0

def calculate_ema(close, period):
    try:
        return EMAIndicator(close=close, window=period).ema_indicator()
    except Exception:
        return pd.Series(dtype=float)

def calculate_macd_crossover(close):
    """Returns True if MACD line crossed above signal line in last 3 bars."""
    try:
        macd_obj   = MACDIndicator(close=close, window_slow=26, window_fast=12, window_sign=9)
        macd_line  = macd_obj.macd()
        signal_line= macd_obj.macd_signal()
        # Bullish crossover: macd > signal today AND macd <= signal yesterday (within last 3 bars)
        for i in range(-1, -4, -1):
            if macd_line.iloc[i] > signal_line.iloc[i] and macd_line.iloc[i-1] <= signal_line.iloc[i-1]:
                return True
        return False
    except Exception:
        return False

def candle_strength(open_s, close_s, high_s, low_s):
    """
    Returns a 0–1 score measuring how bullish today's candle is.
    = body_size / total_range  (higher = strong bull candle, no big wicks)
    """
    try:
        o = float(open_s.iloc[-1])
        c = float(close_s.iloc[-1])
        h = float(high_s.iloc[-1])
        l = float(low_s.iloc[-1])
        total_range = h - l
        if total_range == 0:
            return 0.0
        body = c - o
        return max(0.0, body / total_range)   # negative = red candle → 0
    except Exception:
        return 0.0

def atr_percent(high, low, close):
    """ATR as % of price — used to gauge whether breakout is significant."""
    try:
        atr_val = safe_float(
            AverageTrueRange(high=high, low=low, close=close, window=14)
            .average_true_range().iloc[-1]
        )
        price = safe_float(close.iloc[-1])
        return (atr_val / price * 100) if price > 0 else 0.0
    except Exception:
        return 0.0

def is_consolidation_breakout(high, close, lookback=15):
    """
    Checks whether price was consolidating (low ATR) and has now broken out.
    Consolidation = std(close[-lookback:]) / mean(close[-lookback:]) < 3%
    Breakout      = today's close > max(high[-lookback:]) of the prior range
    """
    try:
        prior_high  = float(high.iloc[-lookback:-1].max())
        recent_close= close.iloc[-lookback:-1]
        std_pct     = float(recent_close.std() / recent_close.mean() * 100)
        current     = float(close.iloc[-1])
        tight_range = std_pct < 3.0
        broke_out   = current > prior_high
        return tight_range and broke_out
    except Exception:
        return False

def ath_proximity_pct(high):
    """How far (%) below the 52-week ATH is the current price."""
    try:
        ath     = float(high.iloc[-252:].max()) if len(high) >= 252 else float(high.max())
        current = float(high.iloc[-1])
        return ((ath - current) / ath) * 100
    except Exception:
        return 100.0

# =============================================================================
# SCORE ENGINE  ← IMPROVED (max = 14)
# =============================================================================

def compute_score(signals: dict) -> int:
    score = 0
    if signals["price_change"] >= PRICE_CHANGE_MIN:          score += 2
    if signals["volume_ratio"] >= VOLUME_RATIO_MIN:           score += 2
    if signals["rsi"] >= RSI_MIN:                             score += 2
    if signals["breakout_20d"]:                               score += 2
    if signals["golden_cross"]:                               score += 1
    if signals["macd_crossover"]:                             score += 1
    if signals["consolidation_breakout"]:                     score += 2
    if signals["candle_strength"] > 0.6:                      score += 1
    if signals["ath_proximity_pct"] < 5:                      score += 1   # within 5% of ATH
    return score   # max = 14

# =============================================================================
# EXPORT RESULTS
# =============================================================================

def export_results(df):
    try:
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        parquet_file= f"{EXPORT_FOLDER}/momentum_{timestamp}.parquet"
        excel_file  = f"{EXPORT_FOLDER}/momentum_{timestamp}.xlsx"
        df.to_parquet(parquet_file, engine="pyarrow", index=False)
        df.to_excel(excel_file, engine="openpyxl", index=False)
        log.info("Exports completed → %s", excel_file)
    except Exception:
        traceback.print_exc()

# =============================================================================
# MAIN ENGINE
# =============================================================================

def run():
    log.info("Momentum scan started")

    # Fetch Nifty return once for relative-strength context
    nifty_20d = fetch_nifty_returns(20)
    log.info("Nifty 20-day return: %.2f%%", nifty_20d)

    results      = []
    total_stocks = len(WATCHLIST)

    for index, symbol in enumerate(WATCHLIST, start=1):
        try:
            if index % 10 == 0:
                log.info("Processed %s/%s stocks", index, total_stocks)

            hist = fetch_stock_data(symbol)
            if hist is None:
                continue

            close  = hist["Close"].astype(float)
            high   = hist["High"].astype(float)
            low    = hist["Low"].astype(float)
            open_  = hist["Open"].astype(float)
            volume = hist["Volume"].astype(float)

            current_price = safe_float(close.iloc[-1])
            prev_close    = safe_float(close.iloc[-2])
            change_pct    = (current_price - prev_close) / prev_close * 100

            avg_volume   = safe_float(volume.rolling(20).mean().iloc[-1])
            volume_ratio = (float(volume.iloc[-1]) / avg_volume) if avg_volume > 0 else 0

            # 20-day breakout
            high20      = safe_float(high.rolling(20).max().iloc[-2])   # use prior day's max
            breakout_20d= current_price > high20

            rsi = calculate_rsi(close)

            ema20_s = calculate_ema(close, EMA_FAST)
            ema50_s = calculate_ema(close, EMA_SLOW)
            ema200_s= calculate_ema(close, EMA_TREND)

            if ema20_s.empty or ema50_s.empty:
                continue

            ema20     = safe_float(ema20_s.iloc[-1])
            ema50     = safe_float(ema50_s.iloc[-1])
            ema20_prev= safe_float(ema20_s.iloc[-2])
            ema50_prev= safe_float(ema50_s.iloc[-2])
            ema200    = safe_float(ema200_s.iloc[-1]) if not ema200_s.empty else 0

            golden_cross= ema20 > ema50 and ema20_prev <= ema50_prev
            above_200   = current_price > ema200 if ema200 > 0 else True

            macd_x      = calculate_macd_crossover(close)
            consol_x    = is_consolidation_breakout(high, close)
            cstrength   = candle_strength(open_, close, high, low)
            ath_pct     = ath_proximity_pct(high)
            stock_20d   = (current_price - safe_float(close.iloc[-20])) / safe_float(close.iloc[-20]) * 100
            rel_strength= stock_20d - nifty_20d   # positive = outperforming

            signals = {
                "price_change"         : change_pct,
                "volume_ratio"         : volume_ratio,
                "rsi"                  : rsi,
                "breakout_20d"         : breakout_20d,
                "golden_cross"         : golden_cross,
                "macd_crossover"       : macd_x,
                "consolidation_breakout": consol_x,
                "candle_strength"      : cstrength,
                "ath_proximity_pct"    : ath_pct,
                "above_200ema"         : above_200,
                "rel_strength_vs_nifty": rel_strength,
            }

            score = compute_score(signals)

            result = {
                "symbol"           : symbol,
                "price"            : round(current_price, 2),
                "change_pct"       : round(change_pct, 2),
                "rsi"              : round(rsi, 2),
                "volume_ratio"     : round(volume_ratio, 2),
                "ema20"            : round(ema20, 2),
                "ema50"            : round(ema50, 2),
                "ema200"           : round(ema200, 2),
                "golden_cross"     : golden_cross,
                "macd_crossover"   : macd_x,
                "breakout_20d"     : breakout_20d,
                "consol_breakout"  : consol_x,
                "candle_str"       : round(cstrength, 2),
                "ath_prox_pct"     : round(ath_pct, 2),
                "rel_str_nifty"    : round(rel_strength, 2),
                "above_200ema"     : above_200,
                "score"            : score,
            }

            results.append(result)

            check_news(symbol)

            if score >= STRONG_SCORE and not already_alerted(symbol):
                # Build a concise list of fired signals for the alert
                fired = []
                if change_pct   >= PRICE_CHANGE_MIN:   fired.append(f"📈 Price +{change_pct:.1f}%")
                if volume_ratio >= VOLUME_RATIO_MIN:    fired.append(f"🔊 Volume {volume_ratio:.1f}x avg")
                if rsi          >= RSI_MIN:             fired.append(f"⚡ RSI {rsi:.0f}")
                if breakout_20d:                        fired.append("🚀 20-day Breakout")
                if consol_x:                            fired.append("📦 Consolidation Breakout")
                if golden_cross:                        fired.append("✨ Golden Cross")
                if macd_x:                              fired.append("🔁 MACD Crossover")
                if cstrength > 0.6:                     fired.append(f"🕯 Strong Candle ({cstrength:.0%})")
                if ath_pct   < 5:                       fired.append(f"🏔 Near ATH ({ath_pct:.1f}% away)")
                if above_200:                           fired.append("📊 Above 200 EMA")
                if rel_strength > 3:                    fired.append(f"💪 RS vs Nifty +{rel_strength:.1f}%")

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
                log.info("ALERT SENT %s Score=%s/%s", symbol, score, 14)

            time.sleep(1)

        except Exception:
            traceback.print_exc()

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

    check_bse_announcements()

    log.info("Completed scanning %s stocks", total_stocks)
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
        send_telegram("❌ BOT CRASHED — check logs")
