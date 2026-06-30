import os
import requests
import logging
from datetime import datetime, timedelta
import yfinance as yf
from zoneinfo import ZoneInfo
from db import save_alert, has_alert_today
from scanners.trade_plan import TradePlan, calculate_position_size
from scanners.fyers_client import get_fyers_history

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

def fetch_intraday_cached(symbol, period="5d", interval="1d", ttl_minutes=5, bse_code=None):
    """
    Fetch data from Fyers (if available) with fallback to Yahoo Finance.
    Cache it for ttl_minutes to avoid spamming APIs.
    """
    cache_key = f"{symbol}_{period}_{interval}"
    cached = _data_cache.get(cache_key)
    
    now = get_ist_now()
    
    if cached and (now - cached['timestamp']) < timedelta(minutes=ttl_minutes):
        return cached['data'].copy()
        
    df = None
    
    # 1. Try Fyers API first if credentials exist
    if os.environ.get("FYERS_CLIENT_ID"):
        if 'd' in period:
            days = int(period.replace('d', ''))
        elif 'mo' in period:
            days = int(period.replace('mo', '')) * 30
        elif 'y' in period:
            days = int(period.replace('y', '')) * 365
        else:
            days = 5
            
        try:
            df = get_fyers_history(symbol, resolution=interval, days=days, bse_code=bse_code)
        except Exception as e:
            log.warning(f"Fyers fetch failed for {symbol}, falling back to Yahoo: {e}")
            df = None
            
    # 2. Fallback to Yahoo Finance
    if df is None or df.empty:
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            df = ticker.history(period=period, interval=interval, prepost=False)
        except Exception as e:
            log.error(f"Yahoo fetch failed for {symbol} {period}/{interval}: {e}")
            return None
            
    if df is not None and not df.empty:
        _data_cache[cache_key] = {
            'timestamp': now,
            'data': df
        }
        
        # Update CMP in database if this is the smallest candle we fetch (5m)
        if interval == "5m":
            try:
                from db import update_price
                latest_close = float(df['Close'].iloc[-1])
                # We update the price, leaving change_pct unchanged (handled by daily fetch)
                update_price(symbol, latest_close)
            except Exception as e:
                log.warning(f"Failed to update CMP for {symbol} from candle fetch: {e}")
                
        return df.copy()
        
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

def emit_alert(symbol, scanner_name, message, trade_plan: TradePlan = None, confidence=None, tags=None, allocation_amount=10000):
    """
    Standardized payload emitter for both scanners with Company Quality (CQS)
    and Price Attractiveness (PAS) fundamental overlays.
    """
    if has_alert_today(symbol, scanner_name.upper()):
        log.info(f"[{scanner_name}] SKIPPED {symbol}: Alert already generated today.")
        return

    if trade_plan and trade_plan.invalid:
        log.info(f"[{scanner_name}] REJECTED {symbol}: {trade_plan.reason}")
        return

    # Fetch dynamic CQS / PAS from DB
    from db import get_valuation_details
    q_score, v_score, db_v_label = get_valuation_details(symbol)
    
    # Calculate bonuses/penalties
    q_bonus = 0.0
    v_bonus = 0.0
    q_label = "F-Score Pending"
    v_label = "F-Score Pending"
    rating_label = "Technical Setup (F-Score Pending)"
    
    if q_score is not None:
        q_score = float(q_score)
        if q_score >= 80.0:
            q_bonus = 2.0
            q_label = "Excellent Business"
        elif q_score >= 60.0:
            q_bonus = 1.0
            q_label = "Good Business"
        elif q_score >= 40.0:
            q_label = "Mixed Fundamentals"
        else:
            q_label = "Weak Business"
            
    if v_score is not None:
        v_score = float(v_score)
        if db_v_label:
            if db_v_label == "UNDERVALUED":
                v_bonus = 1.0
                v_label = "Attractive Buy Zone"
            elif db_v_label == "FAIR":
                v_label = "Fairly Priced"
            elif db_v_label == "OVERVALUED":
                v_bonus = -1.0
                v_label = "Expensive / Limited Margin of Safety"
            else:
                v_label = db_v_label
        else:
            if v_score >= 80.0:
                v_bonus = 1.0
                v_label = "Attractive Buy Zone"
            elif v_score >= 60.0:
                v_label = "Fairly Priced"
            elif v_score >= 40.0:
                v_bonus = -1.0
                v_label = "Expensive / Limited Margin of Safety"
            else:
                v_bonus = -1.0
                v_label = "Avoid at current price"

    # Overlay math onto technical score (technical score defaults to passed-in confidence)
    tech_score = float(confidence) if confidence is not None else 7.5
    final_score = round(tech_score + q_bonus + v_bonus, 1)
    
    # Construct final overall classification label
    if q_score is not None and v_score is not None:
        if q_score >= 80.0 and v_score >= 60.0:
            rating_label = "🔥 High Quality Breakout"
        elif q_score >= 60.0 and v_score <= 40.0:
            rating_label = "⚠️ Strong Business but Expensive"
        elif q_score <= 40.0 and v_score >= 60.0:
            rating_label = "💎 Cheap but Weak Fundamentals"
        elif q_score <= 30.0 or v_score <= 30.0:
            rating_label = "🚨 Speculative / Avoid at current price"
        else:
            rating_label = "📈 Balanced Momentum Setup"

    # Decorate original alert message with clear Quality and Valuation notes
    overlay_details = []
    if q_score is not None:
        overlay_details.append(f"Quality: {q_score}/100 ({q_label})")
    if v_score is not None:
        v_text = f"Valuation: {v_score}/100 ({v_label})"
        overlay_details.append(v_text)
        
    full_message = f"[{rating_label}]\n{message}"
    if overlay_details:
        full_message += "\n" + " | ".join(overlay_details)

    log.info(f"[{scanner_name}] ALERT for {symbol}: {full_message}")
    
    pos_size = calculate_position_size(trade_plan.entry, allocation_amount) if trade_plan else None
    
    save_alert(
        symbol=symbol,
        alert_type=scanner_name.upper(),
        message=full_message,
        entry_price=trade_plan.entry if trade_plan else None,
        target_price=trade_plan.target2 if trade_plan else None,  # Using T2 as primary DB target for legacy
        stop_loss=trade_plan.stop_loss if trade_plan else None,
        confidence=final_score,
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
    
    # Send Telegram message
    msg = f"🚨 <b>{scanner_name.upper()} | {symbol}</b>\n"
    msg += f"<b>Rating:</b> {rating_label}\n\n"
    msg += f"{message}\n\n"
    
    msg += f"<b>Fundamentals:</b>\n"
    if q_score is not None:
        msg += f"• Company Quality: <b>{q_score}/100</b> ({q_label})\n"
    else:
        msg += f"• Company Quality: <i>Pending calculation</i>\n"
        
    if v_score is not None:
        v_text = f"• Price Valuation: <b>{v_score}/100</b> ({v_label})"
        msg += v_text + "\n"
    else:
        msg += f"• Price Valuation: <i>Pending calculation</i>\n"
        
    if trade_plan:
        msg += f"\n<b>Trade Parameters:</b>\n"
        msg += f"• Entry: {trade_plan.entry}\n"
        msg += f"• Stop Loss: {trade_plan.stop_loss} <i>(Risk per share: {trade_plan.risk_per_share})</i>\n"
        msg += f"• Target 1 (1.0R): {trade_plan.target1}\n"
        msg += f"• Target 2 (2.0R): {trade_plan.target2}\n"
        msg += f"• Target 3 (Trail): {trade_plan.target3}\n"
        if pos_size:
            msg += f"• Quantity (₹{allocation_amount//1000}k Allocation): {pos_size} shares\n"
        msg += f"• Trail Strategy: {trade_plan.trail_mode}\n"
        
    msg += f"\n<b>Final Alert Score: {final_score}/10</b>\n"
    msg += f"<i>Math: Tech {tech_score} + Quality Bonus {q_bonus:+} + Value Bonus {v_bonus:+}</i>"
    
    if scanner_name != "MF_QUALIFYING":
        send_telegram(msg)
