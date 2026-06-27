import os
import requests
import logging
from datetime import datetime, timedelta
import yfinance as yf
from zoneinfo import ZoneInfo
from db import save_alert
from scanners.trade_plan import TradePlan, calculate_position_size

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

def emit_alert(symbol, scanner_name, message, trade_plan: TradePlan = None, confidence=None, tags=None, risk_amount=10000):
    """
    Standardized payload emitter for both scanners.
    """
    if trade_plan and trade_plan.invalid:
        log.info(f"[{scanner_name}] REJECTED {symbol}: {trade_plan.reason}")
        return

    log.info(f"[{scanner_name}] ALERT for {symbol}: {message}")
    
    pos_size = calculate_position_size(trade_plan.entry, trade_plan.stop_loss, risk_amount) if trade_plan else None
    
    save_alert(
        symbol=symbol,
        alert_type=scanner_name.upper(),
        message=message,
        entry_price=trade_plan.entry if trade_plan else None,
        target_price=trade_plan.target2 if trade_plan else None,  # Using T2 as primary DB target for legacy
        stop_loss=trade_plan.stop_loss if trade_plan else None,
        confidence=confidence,
        trigger_type=scanner_name,
        tags=tags,
        t1_price=trade_plan.target1 if trade_plan else None,
        t2_price=trade_plan.target2 if trade_plan else None,
        t3_price=trade_plan.target3 if trade_plan else None,
        risk_per_share=trade_plan.risk_per_share if trade_plan else None,
        rr_to_t1=trade_plan.rr_t1 if trade_plan else None,
        rr_to_t2=trade_plan.rr_t2 if trade_plan else None,
        rr_to_t3=trade_plan.rr_t3 if trade_plan else None,
        trail_mode=trade_plan.trail_mode if trade_plan else None,
        position_size_hint=pos_size,
        setup_expiry_minutes=None,
        invalid=False,
        reason=trade_plan.reason if trade_plan else "Legacy alert"
    )
    
    # Send Telegram
    msg = f"🚨 <b>{scanner_name.upper()} | {symbol}</b>\n\n{message}\n"
    if trade_plan:
        msg += f"<b>Entry:</b> {trade_plan.entry}\n"
        msg += f"<b>SL:</b> {trade_plan.stop_loss} <i>(Risk: {trade_plan.risk_per_share})</i>\n"
        msg += f"<b>T1 (1.0R+):</b> {trade_plan.target1}\n"
        msg += f"<b>T2 (2.0R+):</b> {trade_plan.target2}\n"
        msg += f"<b>T3/Trail:</b> {trade_plan.target3}\n"
        if pos_size:
            msg += f"<b>Qty (₹10k Risk):</b> {pos_size} shares\n"
        msg += f"<b>Trail:</b> {trade_plan.trail_mode}\n"
        
    if confidence: msg += f"\nConf: {confidence}/10"
    
    send_telegram(msg)
