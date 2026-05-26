# =========================================================
# ALERT PROCESSOR  [v7]
# =========================================================
#
# MESSAGE CONSOLIDATION UPDATE
# ---------------------------------------------------------
#
# CHANGED:
#   ✅ PRICE MOVE alerts consolidated into ONE message
#   ✅ DAY HIGH alerts consolidated into ONE message
#   ✅ CONSOLIDATION alerts consolidated into ONE message
#
# UNCHANGED:
#   ✅ Alert logic
#   ✅ Thresholds
#   ✅ Dedup logic
#   ✅ Notice alerts
#   ✅ News alerts
#   ✅ Breakout detection
#   ✅ Price calculations
#
# WHY:
#   - Reduce Telegram spam
#   - Cleaner scanning experience
#   - Faster bot execution
#   - Fewer Telegram API calls
#
# =========================================================

def process_alerts(all_data: dict):

    alert_count = 0

    price_levels    = seen_alerts.setdefault("price_levels", {})
    day_high_levels = seen_alerts.setdefault("day_high_levels", {})
    one_shot_keys   = seen_alerts.setdefault("keys", [])

    # =====================================================
    # ALERT BATCHES
    # =====================================================
    #
    # Instead of sending messages immediately,
    # we collect them first and send ONE message
    # per category at the end.
    #
    # =====================================================

    price_alert_batch = []
    day_high_batch    = []
    consol_batch      = []

    for symbol, stock in all_data.items():

        move_pct   = stock["move_pct"]
        last_price = stock["price"]
        day_high   = stock["day_high"]

        # =================================================
        # 1. PRICE MOVE ALERTS
        # =================================================
        #
        # Existing logic unchanged
        #
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

                # =========================================
                # NEW:
                # Add to batch instead of Telegram send
                # =========================================

                price_alert_batch.append({
                    "symbol": symbol,
                    "price": last_price,
                    "move_pct": move_pct,
                    "step_num": step_num,
                })

        # =================================================
        # 2. DAY HIGH ALERTS
        # =================================================
        #
        # Existing detection logic unchanged
        #
        # =================================================

        if stock["at_day_high"]:

            last_high_alerted = day_high_levels.get(symbol, 0.0)

            high_extension = 0.0

            if last_high_alerted > 0:

                high_extension = (
                    (day_high - last_high_alerted)
                    / last_high_alerted
                ) * 100

            if (
                last_high_alerted == 0.0
                or high_extension >= DAY_HIGH_STEP_PCT
            ):

                day_high_levels[symbol] = day_high

                log(
                    f"🔥 DAY HIGH: "
                    f"{symbol} ₹{day_high:,.2f}"
                )

                # =========================================
                # NEW:
                # Add to batch instead of Telegram send
                # =========================================

                day_high_batch.append({
                    "symbol": symbol,
                    "price": last_price,
                    "move_pct": move_pct,
                    "day_high": day_high,
                })

        # =================================================
        # 3. CONSOLIDATION BREAKOUT — 5m
        # =================================================
        #
        # Existing logic unchanged
        #
        # =================================================

        if stock["consol_5m"]:

            key = f"{symbol}-CONSOL5M-{today_str()}"

            if key not in one_shot_keys:

                one_shot_keys.append(key)

                log(
                    f"🔲 CONSOL 5M: "
                    f"{symbol} break "
                    f"+{stock['consol_5m']['break_above_pct']:.2f}%"
                )

                # =========================================
                # NEW:
                # Add to consolidated batch
                # =========================================

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
        #
        # Existing logic unchanged
        #
        # =================================================

        if stock["consol_15m"]:

            key = f"{symbol}-CONSOL15M-{today_str()}"

            if key not in one_shot_keys:

                one_shot_keys.append(key)

                log(
                    f"🔲 CONSOL 15M: "
                    f"{symbol} break "
                    f"+{stock['consol_15m']['break_above_pct']:.2f}%"
                )

                # =========================================
                # NEW:
                # Add to consolidated batch
                # =========================================

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
    # SEND CONSOLIDATED PRICE MOVE ALERTS
    # =====================================================

    if price_alert_batch:

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

        time.sleep(0.5)

    # =====================================================
    # SEND CONSOLIDATED DAY HIGH ALERTS
    # =====================================================

    if day_high_batch:

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

        time.sleep(0.5)

    # =====================================================
    # SEND CONSOLIDATED CONSOLIDATION ALERTS
    # =====================================================

    if consol_batch:

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

        time.sleep(0.5)

    return alert_count
