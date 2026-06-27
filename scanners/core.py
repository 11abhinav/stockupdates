import os
import requests
import logging
from datetime import datetime, timedelta
import yfinance as yf
from zoneinfo import ZoneInfo
from db import save_alert

log = logging.getLogger("scanners")
IST = ZoneInfo("Asia/Kolkata")

# TTL Cache for data to avoid spamming YFinance
_data_cache = {}

def get_ist_now():
    return datetime.now(IST)

def is_market_open():
    now = get_ist_now()
    if now.weekday() > 4:  # 5=Sat, 6=Sun
        return False
    
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    return market_open <= now <= market_close

def fetch_yfinance_cached(symbol, period="5d", interval="1d", ttl_minutes=5):
    """
    Fetch data and cache it for ttl_minutes.
    Useful for 5m intraday data across scanners.
    """
    cache_key = f"{symbol}_{period}_{interval}"
    cached = _data_cache.get(cache_key)
    
    now = get_ist_now()
    
    if cached and (now - cached['timestamp']) < timedelta(minutes=ttl_minutes):
        return cached['data'].copy()
        
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        df = ticker.history(period=period, interval=interval, prepost=False)
        if not df.empty:
            _data_cache[cache_key] = {
                'timestamp': now,
                'data': df
            }
        return df.copy()
    except Exception as e:
        log.error(f"Error fetching {symbol} {period}/{interval}: {e}")
        return None

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        log.warning(f"Telegram failed: {e}")

def emit_alert(symbol, scanner_name, message, entry=None, target=None, stop_loss=None, confidence=None, tags=None):
    """
    Standardized payload emitter for both scanners.
    """
    log.info(f"[{scanner_name}] ALERT for {symbol}: {message}")
    
    save_alert(
        symbol=symbol,
        alert_type=scanner_name.upper(),
        message=message,
        entry_price=entry,
        target_price=target,
        stop_loss=stop_loss,
        confidence=confidence,
        trigger_type=scanner_name,
        tags=tags
    )
    
    # Send Telegram
    msg = f"<b>{scanner_name.upper()} | {symbol}</b>\n{message}"
    if entry: msg += f"\nEntry: {entry}"
    if target: msg += f"\nTarget: {target}"
    if stop_loss: msg += f"\nSL: {stop_loss}"
    if confidence: msg += f"\nConf: {confidence}/10"
    
    send_telegram(msg)
