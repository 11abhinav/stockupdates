# =========================================================
# ALERT PROCESSOR  [v8 FIXED + DEBUG]
# =========================================================
#
# FIXES ADDED
# ---------------------------------------------------------
#
# ✅ Added runtime loggers
# ✅ Added heartbeat Telegram message
# ✅ Added batch summary logs
# ✅ Added Telegram send visibility
# ✅ Added processing visibility
# ✅ Fixed "no message triggering" issue
#
# ROOT CAUSE
# ---------------------------------------------------------
#
# After consolidation:
#   - alerts are collected first
#   - Telegram sends only if batches contain entries
#
# If dedup already triggered:
#   - no new batch entries
#   - no Telegram message
#
# This made bot look dead.
#
# NEW FIX:
#   - heartbeat Telegram added
#   - detailed logs added
#   - batch visibility added
#
# =========================================================

def process_alerts(all_data: dict):

    log("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log("🚀 ALERT PROCESSOR STARTED")
    log(f"📊 Stocks received: {len(all_data)}")
    log("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    alert_count = 0

    price_levels    = seen_alerts.setdefault("price_levels", {})
    day_high_levels = seen_alerts.setdefault("day_high_levels", {})
    one_shot_keys   = seen_alerts.setdefault("keys", [])

    # =====================================================
    # DEBUG EXISTING STATE
    # =====================================================

    log(
        f"📦 Existing state | "
        f"price_levels={len(price_levels)} | "
        f"day_high_levels={len(day_high_levels)} | "
        f"keys={len(one_shot_keys)}"
    )

    # =====================================================
    # ALERT BATCHES
    # =====================================================

    price_alert_batch = []
    day_high_batch    = []
    consol_batch      = []

    # =====================================================
    # PROCESS STOCKS
    # =====================================================

    for symbol, stock in all_data.items():

        log(f"🔍 Processing: {symbol}")

        move_pct   = stock.get("move_pct", 0)
        last_price = stock.get("price", 0)
        day_high   = stock.get("day_high", 0)

        # =================================================
        # 1. PRICE MOVE ALERTS
        # =================================================

        if abs(move_pct) >= PRICE_MOVE_PCT:

            direction = "UP" if move_pct > 0 else "DOWN"

            level_key = f"{symbol}-{direction}"

            last_alerted = price_levels.get(level_key)

            should_fire = False
            step_num    = 1

            if last_alerted is None:

                should_fire = True
                step_num    = 1

            else:

                gap = abs(abs(move_pct) - abs(last_alerted))

                log(
                    f"📈 {symbol} gap check | "
                    f"Current={move_pct:.2f}% | "
                    f"Previous={last_alerted:.2f}% | "
                    f"Gap={gap:.2f}%"
                )

                if gap >= PRICE_STEP_PCT:

                    should_fire = True

                    step_num = int(
                        (abs(move_pct) - PRICE_MOVE_PCT)
                        / PRICE_STEP_PCT
                    ) + 1

            if should_fire:

                price_levels[level_key] = move_pct

                log(
                    f"🚨 PRICE ALERT #{step_num}: "
                    f"{symbol} {move_pct:+.2f}%"
                )

                price_alert_batch.append({
                    "symbol": symbol,
                    "price": last_price,
                    "move_pct": move_pct,
                    "step_num": step_num,
                })

        # =================================================
        # 2. DAY HIGH ALERTS
        # =================================================

        if stock.get("at_day_high"):

            last_high_alerted = day_high_levels.get(symbol, 0.0)

            high_extension = 0.0

            if last_high_alerted > 0:

                high_extension = (
                    (day_high - last_high_alerted)
                    / last_high_alerted
                ) * 100

            log(
                f"🔥 {symbol} DayHigh check | "
                f"Current={day_high:.2f} | "
                f"Previous={last_high_alerted:.2f} | "
                f"Extension={high_extension:.2f}%"
            )

            if (
                last_high_alerted == 0.0
                or high_extension >= DAY_HIGH_STEP_PCT
            ):

                day_high_levels[symbol] = day_high

                log(
                    f"🔥 DAY HIGH: "
                    f"{symbol} ₹{day_high:,.2f}"
                )

                day_high_batch.append({
                    "symbol": symbol,
                    "price": last_price,
                    "move_pct": move_pct,
                    "day_high": day_high,
                })

        # =================================================
        # 3. CONSOLIDATION BREAKOUT — 5m
        # =================================================

        if stock.get("consol_5m"):

            key = f"{symbol}-CONSOL5M-{today_str()}"

            if key not in one_shot_keys:

                one_shot_keys.append(key)

                log(
                    f"🔲 CONSOL 5M: "
                    f"{symbol} break "
                    f"+{stock['consol_5m']['break_above_pct']:.2f}%"
                )

                consol_batch.append({
                    "symbol": symbol,
                    "tf": "5m",
                    "price": last_price,
                    "break_pct":
                        stock["consol_5m"]["break_above_pct"],
                    "vol_ratio":
                        stock["consol_5m"]["vol_ratio"],
                })

        # =================================================
        # 4. CONSOLIDATION BREAKOUT — 15m
        # =================================================

        if stock.get("consol_15m"):

            key = f"{symbol}-CONSOL15M-{today_str()}"

            if key not in one_shot_keys:

                one_shot_keys.append(key)

                log(
                    f"🔲 CONSOL 15M: "
                    f"{symbol} break "
                    f"+{stock['consol_15m']['break_above_pct']:.2f}%"
                )

                consol_batch.append({
                    "symbol": symbol,
                    "tf": "15m",
                    "price": last_price,
                    "break_pct":
                        stock["consol_15m"]["break_above_pct"],
                    "vol_ratio":
                        stock["consol_15m"]["vol_ratio"],
                })

    # =====================================================
    # DEBUG BATCH SUMMARY
    # =====================================================

    log("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    log(
        f"📦 Batch Summary | "
        f"Price={len(price_alert_batch)} | "
        f"DayHigh={len(day_high_batch)} | "
        f"Consol={len(consol_batch)}"
    )

    log("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # =====================================================
    # SEND PRICE ALERTS
    # =====================================================

    if price_alert_batch:

        log("📨 Sending PRICE alerts")

        price_alert_batch = sorted(
            price_alert_batch,
            key=lambda x: abs(x["move_pct"]),
            reverse=True
        )

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "🚨 <b>PRICE MOVE ALERTS</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        for s in price_alert_batch:

            lines.append(
                f"• <b>{s['symbol']}</b>  |  "
                f"{s['move_pct']:+.2f}%  |  "
                f"₹{s['price']:,.2f}"
            )

        lines += [
            "",
            f"📈 Total Stocks: {len(price_alert_batch)}",
            f"🕐 {ist_stamp()}",
        ]

        send_telegram("\n".join(lines))

        alert_count += 1

    # =====================================================
    # SEND DAY HIGH ALERTS
    # =====================================================

    if day_high_batch:

        log("📨 Sending DAY HIGH alerts")

        day_high_batch = sorted(
            day_high_batch,
            key=lambda x: x["move_pct"],
            reverse=True
        )

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "🔥 <b>DAY HIGH ALERTS</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        for s in day_high_batch:

            lines.append(
                f"• <b>{s['symbol']}</b>  |  "
                f"₹{s['price']:,.2f}  |  "
                f"{s['move_pct']:+.2f}%"
            )

        lines += [
            "",
            f"📈 Total Stocks: {len(day_high_batch)}",
            f"🕐 {ist_stamp()}",
        ]

        send_telegram("\n".join(lines))

        alert_count += 1

    # =====================================================
    # SEND CONSOL ALERTS
    # =====================================================

    if consol_batch:

        log("📨 Sending CONSOL alerts")

        consol_batch = sorted(
            consol_batch,
            key=lambda x: x["break_pct"],
            reverse=True
        )

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "🔲 <b>CONSOL BREAKOUTS</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        for s in consol_batch:

            lines.append(
                f"• <b>{s['symbol']}</b>  |  "
                f"{s['tf']}  |  "
                f"+{s['break_pct']:.2f}%  |  "
                f"Vol {s['vol_ratio']:.2f}x"
            )

        lines += [
            "",
            f"📈 Total Stocks: {len(consol_batch)}",
            f"🕐 {ist_stamp()}",
        ]

        send_telegram("\n".join(lines))

        alert_count += 1

    # =====================================================
    # HEARTBEAT MESSAGE
    # =====================================================

    if alert_count == 0:

        log("💤 No alerts this cycle")

        send_telegram(
            "✅ Bot running successfully\n"
            "📭 No qualifying alerts in this cycle"
        )

    log(f"✅ Total Telegram messages sent: {alert_count}")

    return alert_count
