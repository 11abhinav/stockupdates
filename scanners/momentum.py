import logging
from db import get_watchlist
from scanners.core import fetch_intraday_cached, emit_alert
from scanners.trade_plan import build_intraday_trade_plan, pivot_low
from scanners import health

log = logging.getLogger("scanners.momentum")

def is_compressed(high_series, low_series, period=14, threshold=0.015):
    """Check if price is trading in a tight range (compression)"""
    recent_highs = high_series.iloc[-period:]
    recent_lows = low_series.iloc[-period:]
    
    max_high = recent_highs.max()
    min_low = recent_lows.min()
    
    return (max_high - min_low) / min_low < threshold

def run():
    log.info("Running Intraday Momentum Scanner...")
    health.begin_run("MOMENTUM")
    
    try:
        watchlist = get_watchlist()
    except Exception as e:
        health.record_critical_error("MOMENTUM", f"Failed to fetch watchlist: {e}")
        log.error(f"CRITICAL: Cannot fetch watchlist: {e}")
        return
    
    if not watchlist:
        health.record_critical_error("MOMENTUM", "Watchlist is empty - no stocks to scan")
        log.warning("Watchlist is empty.")
        return
    
    for row in watchlist:
        symbol = row['symbol']
        bse = row.get('bse_code')
        try:
            # 1. Fetch 15m Data (Compression / Trend setup)
            df_15m = fetch_intraday_cached(symbol, period="5d", interval="15m", ttl_minutes=15, bse_code=bse)
            if df_15m is None or len(df_15m) < 20:
                reason = "None returned" if df_15m is None else f"only {len(df_15m)} rows"
                log.warning(f"[{symbol}] 15m data stale: {reason} (need 20)")
                health.record_stock_stale("MOMENTUM", symbol)
                continue
                
            close_15 = df_15m['Close']
            ema20_15 = close_15.ewm(span=20, adjust=False).mean().iloc[-1]
            
            if close_15.iloc[-1] < ema20_15:
                health.record_stock_scanned("MOMENTUM")
                continue # Only looking for longs above 15m EMA20
                
            if not is_compressed(df_15m['High'], df_15m['Low']):
                health.record_stock_scanned("MOMENTUM")
                continue
                
            # 2. Fetch 5m Data (Trigger & Confirmation)
            df_5m = fetch_intraday_cached(symbol, period="5d", interval="5m", ttl_minutes=5, bse_code=bse)
            if df_5m is None or len(df_5m) < 10:
                reason = "None returned" if df_5m is None else f"only {len(df_5m)} rows"
                log.warning(f"[{symbol}] 5m data stale: {reason} (need 10)")
                health.record_stock_stale("MOMENTUM", symbol)
                continue
                
            close_5 = df_5m['Close']
            vol_5 = df_5m['Volume']
            
            current_price = close_5.iloc[-1]
            avg_vol_5 = vol_5.iloc[-10:].mean()
            last_vol_5 = vol_5.iloc[-1]
            
            # Trigger: 5m close breaks above 15m recent consolidation with volume
            recent_15m_high = df_15m['High'].iloc[-10:].max()
            
            if current_price > recent_15m_high and last_vol_5 > (avg_vol_5 * 2):
                
                # ATR for stop loss
                atr = (df_5m['High'] - df_5m['Low']).iloc[-14:].mean()
                
                trigger_candle_low = df_5m['Low'].iloc[-1]
                prev_pivot = pivot_low(df_5m, left=3, right=3)
                
                trade_plan = build_intraday_trade_plan(
                    trigger_level=recent_15m_high,
                    atr5=atr,
                    trigger_candle_low=trigger_candle_low,
                    prev_pivot_low=prev_pivot,
                    ema20=close_5.ewm(span=20, adjust=False).mean().iloc[-1],
                    buffer_pct=0.0015,
                    atr_sl_buffer_mult=0.25,
                    current_price=current_price
                )
                
                emit_alert(
                    symbol=symbol,
                    scanner_name="MOMENTUM",
                    message=f"Intraday 5m breakout from 15m compression. Volume surge {last_vol_5/avg_vol_5:.1f}x.",
                    trade_plan=trade_plan,
                    confidence=7.5,
                    tags={"timeframe": "5m", "setup": "compression_breakout"}
                )
                health.record_alert("MOMENTUM")
            
            health.record_stock_scanned("MOMENTUM")

        except Exception as e:
            log.error(f"Error in Momentum scanner for {symbol}: {e}")
            health.record_stock_error("MOMENTUM", symbol, str(e))
    
    health.finish_run("MOMENTUM")
    log.info("Momentum Scanner run complete.")
