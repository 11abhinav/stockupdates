# MF (Minervini Swing Breakout) Scanner Fixes: Architecture & Lessons Learned

This document details the architectural design decisions and software engineering lessons learned from auditing and correcting the MF scanner.

---

## 1. Architecture Design

The MF Breakout Scanner operates as a **multi-timeframe (Multi-TF)** momentum screening engine:

```
+-------------------------------------------------------+
|  Watchlist Retrieval (postgres: watchlist table)      |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|  Daily Trend Filter (Price > 50 EMA > 200 EMA)        |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|  Hourly Resistance Identification & Proximity Check   |
|  (Close must be within 2% of the 20-period peak close)|
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|  Volume Expansion & Step-Down Cascade                |
|  - Check 1H volume (>= 1.5x)                          |
|  - Step down to 30m -> 15m -> 5m if needed            |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|  Trade Plan Construction & Risk Gate                  |
|  - Entry = Breakout level + 0.15% buffer              |
|  - SL = min(1H swing low, 1H EMA 20, 1H base low)     |
|  - Filter: Risk <= 2.5 * 1H ATR                       |
+-------------------------------------------------------+
```

### Dynamic Failover & Integrations
- **Data Provider**: Fetches real-time intraday candles via the **Fyers API**.
- **Self-Healing Fallback**: Automatically cascades to the **Yahoo Finance API** if Fyers token generation fails or requests are rate-limited (429).
- **Persistent Storage**: Valid breakout signals are saved to `stockupdates.alerts` as `'OPEN'` statuses, while near-breakout candidates are logged in `stockupdates.qualifying_stocks`.
- **Telegram Messaging**: Broadcasts high-scoring setups to subscribers with exact parameters (Entry, SL, Targets, Sizing).

---

## 2. Lessons Learned

### Lesson 1: Active-Bar Pollution in Rolling Windows
- **Pitfall**: When calculating a rolling maximum (e.g., `series.iloc[-20:].max()`), the range includes the current forming bar (`iloc[-1]`). If a breakout is occurring, the current bar's close will naturally be the highest value in the window, meaning `recent_high` self-adjusts upward to the breakout price.
- **Consequence**: Passing `recent_high` as the `breakout_level` to the trade plan builder inflates the entry price, bloats the stop-loss distance, and triggers the risk-checking guardrails to invalidate and suppress the alert.
- **Takeaway**: **Breakout scanner resistance levels must always be computed excluding the active candle** (e.g., `.iloc[-21:-1].max()`).

### Lesson 2: Timeframe Indicator Alignment
- **Pitfall**: Calculating a trade plan's parameters on one timeframe (e.g., Hourly chart) but selecting a stop-loss candidate from a vastly different timeframe (e.g., Daily 50 EMA) causes indicator misalignment.
- **Consequence**: The Daily 50 EMA is typically far below any hourly support structures. By taking the minimum of these support candidates, the stop loss is placed extremely far away, causing the trade plan to fail the hourly ATR-based risk check.
- **Takeaway**: **All stop-loss candidates in a single trade plan must be calculated from aligned timeframes** (e.g., using the 20 EMA of the hourly chart for an hourly swing trade plan).

### Lesson 3: System Expiry Overrides for Swing Setups
- **Pitfall**: Sweeping and auto-expiring all open alerts at 15:30 IST on day one works for intraday setups, but cuts short swing setups.
- **Consequence**: Trailing stop loss and target hits over multiple days were completely disabled for MF breakouts.
- **Takeaway**: **Alert trackers must check the strategy classification (`alert_type`) before applying EOD auto-expiry logic.**
