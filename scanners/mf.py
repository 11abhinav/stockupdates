import logging
from db import get_watchlist
from scanners.core import fetch_intraday_cached, emit_alert
from scanners.trade_plan import build_mf_trade_plan, recent_swing_low, consolidation_base_low
from scanners import health

log = logging.getLogger("scanners.mf")

def run():
    log.info("Running MF Breakout Scanner...")
    health.begin_run("MF")
    
    try:
        watchlist = get_watchlist()
    except Exception as e:
        health.record_critical_error("MF", f"Failed to fetch watchlist: {e}")
        log.error(f"CRITICAL: Cannot fetch watchlist: {e}")
        return
    
    if not watchlist:
        health.record_critical_error("MF", "Watchlist is empty - no stocks to scan")
        log.warning("Watchlist is empty.")
        return
    
    for row in watchlist:
        symbol = row['symbol']
        try:
            # 1. Fetch Daily Data (Trend check)
            daily_df = fetch_intraday_cached(symbol, period="6mo", interval="1d", ttl_minutes=60)
            if daily_df is None or len(daily_df) < 200:
                health.record_stock_stale("MF", symbol)
                continue
                
            # Calculate EMAs for Minervini Trend Template
            close = daily_df['Close']
            ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
            ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
            current_price = close.iloc[-1]
            
            # Trend Check: Price > 50 EMA > 200 EMA
            if not (current_price > ema50 > ema200):
                health.record_stock_scanned("MF")
                continue
                
            # 2. Fetch 1H Data (Breakout Structure & Volume)
            hourly_df = fetch_intraday_cached(symbol, period="1mo", interval="1h", ttl_minutes=15)
            if hourly_df is None or len(hourly_df) < 20:
                health.record_stock_stale("MF", symbol)
                continue
                
            h_close = hourly_df['Close']
            h_vol = hourly_df['Volume']
            
            recent_high = h_close.iloc[-20:].max()
            avg_vol = h_vol.iloc[-20:].mean()
            last_vol = h_vol.iloc[-1]
            
            # Breakout Check: Price is within 2% of recent high, OR just broke out
            if current_price < recent_high * 0.98:
                health.record_stock_scanned("MF")
                continue
                
            # Volume Check: Is volume expanding on the breakout?
            is_expanding_volume = last_vol >= avg_vol * 1.5
            
            if is_expanding_volume:
                # Calculate Risk/Reward (ATR based Stop Loss) using the new Trade Plan
                atr = (hourly_df['High'] - hourly_df['Low']).iloc[-14:].mean()
                
                swing_low = recent_swing_low(hourly_df, lookback=20)
                base_low = consolidation_base_low(hourly_df, lookback=40)
                
                trade_plan = build_mf_trade_plan(
                    breakout_level=recent_high,
                    latest_close=current_price,
                    atr=atr,
                    swing_low=swing_low,
                    ema20=ema50, # using ema50 from daily as a proxy, or calculate ema20 on hourly
                    base_low=base_low,
                    breakout_buffer_pct=0.0015,
                    atr_sl_buffer_mult=0.5
                )

                # Emit Full Breakout Alert
                emit_alert(
                    symbol=symbol,
                    scanner_name="MF",
                    message=f"Breakout Structure confirmed. Strong trend with volume expansion ({last_vol/avg_vol:.1f}x avg vol).",
                    trade_plan=trade_plan,
                    confidence=8.5,
                    tags={"trend": "strong", "volume": "expanding"}
                )
                health.record_alert("MF")
            else:
                # Emit Qualifying Alert (Ladder) without a trade plan
                emit_alert(
                    symbol=symbol,
                    scanner_name="MF_QUALIFYING",
                    message=f"Eligible on 1H structure, waiting for volume expansion to qualify on 30m/5m (currently {last_vol/avg_vol:.1f}x avg vol).",
                    trade_plan=None,
                    confidence=6.0,
                    tags={"status": "waiting", "ladder": "1H_ready"}
                )
                health.record_alert("MF")
            
            health.record_stock_scanned("MF")
            
        except Exception as e:
            log.error(f"Error in MF scanner for {symbol}: {e}")
            health.record_stock_error("MF", symbol, str(e))
    
    health.finish_run("MF")
    log.info("MF Scanner run complete.")
