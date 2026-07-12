import logging
from db import get_watchlist, upsert_qualifying_stock, delete_qualifying_stock
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
        bse = row.get('bse_code')
        try:
            # 1. Fetch Daily Data (Trend check)
            daily_df = fetch_intraday_cached(symbol, period="1y", interval="1d", ttl_minutes=60, bse_code=bse)
            if daily_df is None or len(daily_df) < 200:
                reason = "None returned" if daily_df is None else f"only {len(daily_df)} rows"
                log.warning(f"[{symbol}] Data stale: {reason} (need 200)")
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
                delete_qualifying_stock(symbol)
                continue
                
            # 2. Fetch 1H Data (Breakout Structure & Volume)
            hourly_df = fetch_intraday_cached(symbol, period="1mo", interval="1h", ttl_minutes=15, bse_code=bse)
            if hourly_df is None or len(hourly_df) < 20:
                reason = "None returned" if hourly_df is None else f"only {len(hourly_df)} rows"
                log.warning(f"[{symbol}] Hourly data stale: {reason} (need 20)")
                health.record_stock_stale("MF", symbol)
                continue
                
            h_close = hourly_df['Close']
            h_vol = hourly_df['Volume']
            
            # [FIX] Exclude the current forming candle from the resistance high
            recent_high = h_close.iloc[-21:-1].max()
            avg_vol = h_vol.iloc[-20:].mean()
            last_vol = h_vol.iloc[-1]
            
            # [FIX] Calculate 20 EMA on the hourly chart to use as a close-range stop-loss candidate
            h_ema20 = h_close.ewm(span=20, adjust=False).mean().iloc[-1]
            
            # Breakout Check: Price is within 2% of recent high, OR just broke out
            if current_price < recent_high * 0.98:
                health.record_stock_scanned("MF")
                delete_qualifying_stock(symbol)
                continue
                
            # Volume Check: Is volume expanding on the breakout?
            is_expanding_volume = last_vol >= avg_vol * 1.5
            
            alert_emitted = False
            timeframes_passed = {"1d": True, "1h": True, "30m": False, "15m": False, "5m": False}
            final_vol_status = f"{last_vol/avg_vol:.1f}x (1H)"
            tf_trigger = "1H"
            
            if is_expanding_volume:
                alert_emitted = True
            else:
                # Step down to 30m
                df_30m = fetch_intraday_cached(symbol, period="5d", interval="30m", ttl_minutes=15, bse_code=bse)
                if df_30m is not None and len(df_30m) >= 20:
                    c30 = df_30m['Close']
                    v30 = df_30m['Volume']
                    # [FIX] Exclude current candle to prevent self-referential price check
                    r_high_30 = c30.iloc[-21:-1].max()
                    avg_v30 = v30.iloc[-20:].mean()
                    last_v30 = v30.iloc[-1]
                    
                    if current_price >= r_high_30 * 0.98:
                        timeframes_passed["30m"] = True
                        final_vol_status = f"{last_v30/avg_v30:.1f}x (30m)"
                        
                        if last_v30 >= avg_v30 * 1.5:
                            alert_emitted = True
                            tf_trigger = "30m"
                        else:
                            # Step down to 15m
                            df_15m = fetch_intraday_cached(symbol, period="5d", interval="15m", ttl_minutes=15, bse_code=bse)
                            if df_15m is not None and len(df_15m) >= 20:
                                c15 = df_15m['Close']
                                v15 = df_15m['Volume']
                                # [FIX] Exclude current candle to prevent self-referential price check
                                r_high_15 = c15.iloc[-21:-1].max()
                                avg_v15 = v15.iloc[-20:].mean()
                                last_v15 = v15.iloc[-1]
                                
                                if current_price >= r_high_15 * 0.98:
                                    timeframes_passed["15m"] = True
                                    final_vol_status = f"{last_v15/avg_v15:.1f}x (15m)"
                                    
                                    if last_v15 >= avg_v15 * 1.5:
                                        alert_emitted = True
                                        tf_trigger = "15m"
                                    else:
                                        # Step down to 5m
                                        df_5m = fetch_intraday_cached(symbol, period="5d", interval="5m", ttl_minutes=5, bse_code=bse)
                                        if df_5m is not None and len(df_5m) >= 20:
                                            c5 = df_5m['Close']
                                            v5 = df_5m['Volume']
                                            # [FIX] Exclude current candle to prevent self-referential price check
                                            r_high_5 = c5.iloc[-21:-1].max()
                                            avg_v5 = v5.iloc[-20:].mean()
                                            last_v5 = v5.iloc[-1]
                                            
                                            if current_price >= r_high_5 * 0.98:
                                                timeframes_passed["5m"] = True
                                                final_vol_status = f"{last_v5/avg_v5:.1f}x (5m)"
                                                
                                                if last_v5 >= avg_v5 * 1.5:
                                                    alert_emitted = True
                                                    tf_trigger = "5m"

            if alert_emitted:
                atr = (hourly_df['High'] - hourly_df['Low']).iloc[-14:].mean()
                swing_low = recent_swing_low(hourly_df, lookback=20)
                base_low = consolidation_base_low(hourly_df, lookback=40)
                
                # [FIX] Pass hourly EMA 20 instead of daily EMA 50 to avoid risk width rejection
                trade_plan = build_mf_trade_plan(
                    breakout_level=recent_high,
                    latest_close=current_price,
                    atr=atr,
                    swing_low=swing_low,
                    ema20=h_ema20,
                    base_low=base_low,
                    breakout_buffer_pct=0.0015,
                    atr_sl_buffer_mult=0.5
                )

                emit_alert(
                    symbol=symbol,
                    scanner_name="MF",
                    message=f"Breakout Structure confirmed. Strong trend with volume expansion on {tf_trigger} ({final_vol_status}).",
                    trade_plan=trade_plan,
                    confidence=8.5,
                    tags={"trend": "strong", "volume": "expanding"}
                )
                health.record_alert("MF")
            else:
                upsert_qualifying_stock(
                    symbol=symbol,
                    timeframes_dict=timeframes_passed,
                    volume_status=final_vol_status
                )
            
            health.record_stock_scanned("MF")
            
        except Exception as e:
            log.error(f"Error in MF scanner for {symbol}: {e}")
            health.record_stock_error("MF", symbol, str(e))
    
    health.finish_run("MF")
    log.info("MF Scanner run complete.")
