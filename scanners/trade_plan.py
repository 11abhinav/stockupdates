import math
import pandas as pd
from dataclasses import dataclass
from typing import Optional, Dict

@dataclass
class TradePlan:
    entry: float
    stop_loss: float
    risk_per_share: float
    target1: float
    target2: float
    target3: float
    rr_t1: float
    rr_t2: float
    rr_t3: float
    trail_mode: str
    setup_type: str
    invalid: bool
    reason: str

def round2(x: float) -> float:
    return round(float(x), 2)

def calculate_position_size(entry: float, allocated_capital: float) -> int:
    if entry <= 0:
        return 0
    return max(0, math.floor(allocated_capital / entry))

def build_mf_trade_plan(
    breakout_level: float,
    latest_close: float,
    atr: float,
    swing_low: float,
    ema20: float,
    base_low: Optional[float] = None,
    breakout_buffer_pct: float = 0.0015,   # 0.15%
    atr_sl_buffer_mult: float = 0.5,
    max_risk_atr_mult: float = 2.5
) -> TradePlan:
    if atr <= 0 or breakout_level <= 0:
        return TradePlan(0,0,0,0,0,0,0,0,0,"","MF_BREAKOUT",True,"Invalid ATR or breakout level")

    entry = breakout_level * (1 + breakout_buffer_pct)

    structural_candidates = [x for x in [swing_low, ema20, base_low] if x is not None and x > 0]
    if not structural_candidates:
        return TradePlan(0,0,0,0,0,0,0,0,0,"","MF_BREAKOUT",True,"No structural stop candidate")

    structural_sl = min(structural_candidates)
    stop_loss = structural_sl - (atr_sl_buffer_mult * atr)

    risk_per_share = entry - stop_loss
    if risk_per_share <= 0:
        return TradePlan(0,0,0,0,0,0,0,0,0,"","MF_BREAKOUT",True,"Non-positive risk")

    if risk_per_share > max_risk_atr_mult * atr:
        return TradePlan(0,0,0,0,0,0,0,0,0,"","MF_BREAKOUT",True,"Risk too wide vs ATR")

    target1 = entry + 3.0 * risk_per_share
    target2 = entry + 5.0 * risk_per_share
    target3 = entry + 8.0 * risk_per_share

    return TradePlan(
        entry=round2(entry),
        stop_loss=round2(stop_loss),
        risk_per_share=round2(risk_per_share),
        target1=round2(target1),
        target2=round2(target2),
        target3=round2(target3),
        rr_t1=3.0,
        rr_t2=5.0,
        rr_t3=8.0,
        trail_mode="After T1 move SL to cost, then trail below Swing Low or 2 ATR",
        setup_type="MF_BREAKOUT",
        invalid=False,
        reason="MF breakout plan"
    )

def build_intraday_trade_plan(
    trigger_level: float,
    atr5: float,
    trigger_candle_low: float,
    prev_pivot_low: Optional[float],
    ema9: Optional[float] = None,
    ema20: Optional[float] = None,
    buffer_pct: float = 0.0015,            # 0.15%
    atr_sl_buffer_mult: float = 0.25,
    max_extension_atr: float = 0.8,
    current_price: Optional[float] = None
) -> TradePlan:
    if atr5 <= 0 or trigger_level <= 0:
        return TradePlan(0,0,0,0,0,0,0,0,0,"","INTRADAY_MOMENTUM",True,"Invalid ATR or trigger")

    entry = trigger_level * (1 + buffer_pct)

    structural_candidates = [x for x in [trigger_candle_low, prev_pivot_low, ema9, ema20] if x is not None and x > 0]
    if not structural_candidates:
        return TradePlan(0,0,0,0,0,0,0,0,0,"","INTRADAY_MOMENTUM",True,"No structural stop candidate")

    structural_sl = min(structural_candidates)
    stop_loss = structural_sl - (atr_sl_buffer_mult * atr5)

    risk_per_share = entry - stop_loss
    if risk_per_share <= 0:
        return TradePlan(0,0,0,0,0,0,0,0,0,"","INTRADAY_MOMENTUM",True,"Non-positive risk")

    if current_price is not None and current_price > entry + (max_extension_atr * atr5):
        return TradePlan(0,0,0,0,0,0,0,0,0,"","INTRADAY_MOMENTUM",True,"Price too extended above trigger")

    target1 = entry + 3.0 * risk_per_share
    target2 = entry + 5.0 * risk_per_share
    target3 = entry + 8.0 * risk_per_share

    return TradePlan(
        entry=round2(entry),
        stop_loss=round2(stop_loss),
        risk_per_share=round2(risk_per_share),
        target1=round2(target1),
        target2=round2(target2),
        target3=round2(target3),
        rr_t1=3.0,
        rr_t2=5.0,
        rr_t3=8.0,
        trail_mode="After T1 move SL to cost, then trail by 1.5 ATR or below latest higher low",
        setup_type="INTRADAY_MOMENTUM",
        invalid=False,
        reason="Intraday momentum plan"
    )

def recent_swing_low(df: pd.DataFrame, lookback: int = 10) -> Optional[float]:
    if df is None or len(df) < lookback:
        return None
    return float(df["Low"].iloc[-lookback:].min())

def pivot_low(df: pd.DataFrame, left: int = 2, right: int = 2) -> Optional[float]:
    if df is None or len(df) < left + right + 1:
        return None
    lows = df["Low"].reset_index(drop=True)
    idx = len(lows) - 1 - right
    pivot_val = lows.iloc[idx]
    left_side = lows.iloc[idx-left:idx]
    right_side = lows.iloc[idx+1:idx+1+right]
    if all(pivot_val < x for x in left_side) and all(pivot_val < x for x in right_side):
        return float(pivot_val)
    return None

def consolidation_base_low(df: pd.DataFrame, lookback: int = 15) -> Optional[float]:
    if df is None or len(df) < lookback:
        return None
    return float(df["Low"].iloc[-lookback:].min())
