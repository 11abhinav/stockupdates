import logging
from db import get_watchlist
from scanners.core import fetch_yfinance_cached, emit_alert

log = logging.getLogger("scanners.mf")

def run():
    log.info("Running MF Breakout Scanner...")
    watchlist = get_watchlist()
    
    for row in watchlist:
        symbol = row['symbol']
        try:
            # 1. Fetch Daily Data (Trend check)
            daily_df = fetch_yfinance_cached(symbol, period="6mo", interval="1d", ttl_minutes=60)
            if daily_df is None or len(daily_df) < 200:
                continue
                
            # Calculate EMAs for Minervini Trend Template
            close = daily_df['Close']
            ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
            ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
            current_price = close.iloc[-1]
            
            # Trend Check: Price > 50 EMA > 200 EMA
            if not (current_price > ema50 > ema200):
                continue
                
            # 2. Fetch 1H Data (Breakout Structure & Volume)
            hourly_df = fetch_yfinance_cached(symbol, period="1mo", interval="1h", ttl_minutes=15)
            if hourly_df is None or len(hourly_df) < 20:
                continue
                
            h_close = hourly_df['Close']
            h_vol = hourly_df['Volume']
            
            recent_high = h_close.iloc[-20:].max()
            avg_vol = h_vol.iloc[-20:].mean()
            last_vol = h_vol.iloc[-1]
            
            # Breakout Check: Price is within 2% of recent high, OR just broke out
            if current_price < recent_high * 0.98:
                continue
                
            # Volume Check: Is volume expanding on the breakout?
            is_expanding_volume = last_vol >= avg_vol * 1.5
            
            # Calculate Risk/Reward (ATR based Stop Loss)
            atr = (hourly_df['High'] - hourly_df['Low']).iloc[-14:].mean()
            stop_loss = round(current_price - (atr * 2), 2)
            target = round(current_price + (atr * 4), 2)  # 1:2 Risk/Reward
            
            if is_expanding_volume:
                # Emit Full Breakout Alert
                emit_alert(
                    symbol=symbol,
                    scanner_name="MF",
                    message=f"Breakout Structure confirmed. Strong trend with volume expansion ({last_vol/avg_vol:.1f}x avg vol).",
                    entry=round(current_price, 2),
                    target=target,
                    stop_loss=stop_loss,
                    confidence=8.5,
                    tags={"trend": "strong", "volume": "expanding"}
                )
            else:
                # Emit Qualifying Alert (Ladder)
                emit_alert(
                    symbol=symbol,
                    scanner_name="MF_QUALIFYING",
                    message=f"Eligible on 1H structure, waiting for volume expansion to qualify on 30m/5m (currently {last_vol/avg_vol:.1f}x avg vol).",
                    entry=round(current_price, 2),
                    target=target,
                    stop_loss=stop_loss,
                    confidence=6.0,
                    tags={"status": "waiting", "ladder": "1H_ready"}
                )
            
        except Exception as e:
            log.error(f"Error in MF scanner for {symbol}: {e}")
