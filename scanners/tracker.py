import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from db import get_open_alerts, update_alert_status
from scanners.core import fetch_intraday_cached, send_telegram

log = logging.getLogger("scanners.tracker")
IST = ZoneInfo("Asia/Kolkata")

def resolve_open_alerts():
    log.info("Running Alert Resolution Tracker...")
    open_alerts = get_open_alerts()
    if not open_alerts:
        return
        
    for alert in open_alerts:
        symbol = alert['symbol']
        alert_id = alert['id']
        created_at = alert['created_at']
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc).astimezone(IST)
            
        # Expire alerts if the current time is past 15:30 IST on the day they were created
        now_ist = datetime.now(IST)
        eod_time = datetime.combine(created_at.date(), datetime.strptime("15:30", "%H:%M").time(), tzinfo=IST)
        if now_ist > eod_time:
            update_alert_status(alert_id, 'EXPIRED', alert['highest_hit'])
            log.info(f"Alert {alert_id} for {symbol} expired at EOD.")
            continue
            
        try:
            # Fetch 5m data. Use ttl_minutes=5 so we hit cache if momentum scanner just ran it
            bse = alert.get('bse_code')
            df = fetch_intraday_cached(symbol, period="5d", interval="5m", ttl_minutes=5, bse_code=bse)
            if df is None or df.empty:
                log.warning(f"Tracker: No 5m data returned for {symbol} (Alert {alert_id})")
                continue
                
            # Filter data to only include candles AFTER the alert was created
            df = df[df.index >= created_at]
            if df.empty:
                continue
                
            highest_high = float(df['High'].max())
            lowest_low = float(df['Low'].min())
            
            stop_loss = float(alert['stop_loss']) if alert['stop_loss'] else None
            t1 = float(alert['t1_price']) if alert['t1_price'] else float(alert['target_price']) if alert['target_price'] else None
            t2 = float(alert['t2_price']) if alert['t2_price'] else None
            t3 = float(alert['t3_price']) if alert['t3_price'] else None
            
            status = 'OPEN'
            highest_hit = alert['highest_hit'] or None
            message = ""
            
            # Check Stop Loss First (Assume worse case if both hit in same candle)
            if stop_loss and lowest_low <= stop_loss:
                status = 'CLOSED_LOSS'
                message = f"❌ <b>STOP LOSS HIT</b>\n\n<b>{symbol}</b> hit its Stop Loss of ₹{stop_loss}.\nTrade closed."
            elif t1 and highest_high >= t1:
                # Determine highest target hit
                if t3 and highest_high >= t3:
                    highest_hit = 'T3'
                    status = 'CLOSED_WIN'
                    message = f"✅ <b>T3 TARGET HIT (FULL WIN)</b>\n\n<b>{symbol}</b> crushed T3 at ₹{t3}!\nTrade fully closed."
                elif t2 and highest_high >= t2:
                    if highest_hit != 'T2':
                        highest_hit = 'T2'
                        message = f"🟢 <b>T2 TARGET HIT</b>\n\n<b>{symbol}</b> hit T2 at ₹{t2}!\nTrail your stops."
                else:
                    if highest_hit != 'T1':
                        highest_hit = 'T1'
                        message = f"🟢 <b>T1 TARGET HIT</b>\n\n<b>{symbol}</b> hit T1 at ₹{t1}!\nTrail your stops."
            
            # Update DB if status changed or a new target was hit
            if status != 'OPEN' or highest_hit != alert['highest_hit']:
                update_alert_status(alert_id, status, highest_hit)
                if message:
                    send_telegram(message)
                log.info(f"Updated Alert {alert_id} for {symbol}: Status={status}, Hit={highest_hit}")
                
        except Exception as e:
            log.error(f"Tracker error for {symbol} (Alert {alert_id}): {e}")
