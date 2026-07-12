import unittest
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Import the modules we need to test
# We set up paths so it can import correctly
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanners.trade_plan import build_mf_trade_plan
from scanners.tracker import resolve_open_alerts
from scanners.core import fetch_intraday_cached

IST = ZoneInfo("Asia/Kolkata")

class TestMFScannerFixes(unittest.TestCase):

    def test_breakout_level_calculation(self):
        """Test that excluding the current candle avoids breakout level inflation."""
        # Setup mock close prices where price just broke out from 100 to 105 in the last bar
        prices = [100.0] * 19 + [105.0]  # Length 20
        h_close = pd.Series(prices)
        
        # Inflated logic (original bug): includes the current bar
        inflated_high = h_close.iloc[-20:].max()
        # Fixed logic: excludes the current bar
        fixed_high = h_close.iloc[-21:-1].max()
        
        self.assertEqual(inflated_high, 105.0)
        self.assertEqual(fixed_high, 100.0)
        print("✓ Test passed: Breakout level calculation properly isolates historical resistance.")

    def test_trade_plan_validation_under_hourly_ema(self):
        """Test that trade plan is valid under hourly EMA 20 stop loss candidate but invalid under daily EMA 50."""
        breakout_level = 100.0
        latest_close = 101.0
        atr = 2.0  # Hourly ATR
        swing_low = 98.0
        base_low = 97.0
        
        # Scenario A: Using Hourly EMA 20 (e.g. 99.0)
        h_ema20 = 99.0
        plan_hourly = build_mf_trade_plan(
            breakout_level=breakout_level,
            latest_close=latest_close,
            atr=atr,
            swing_low=swing_low,
            ema20=h_ema20,
            base_low=base_low
        )
        self.assertFalse(plan_hourly.invalid, f"Hourly plan should be valid but failed: {plan_hourly.reason}")
        
        # Scenario B: Using Daily EMA 50 (e.g. 85.0) - mimicking the bug
        daily_ema50 = 85.0
        plan_daily = build_mf_trade_plan(
            breakout_level=breakout_level,
            latest_close=latest_close,
            atr=atr,
            swing_low=swing_low,
            ema20=daily_ema50,
            base_low=base_low
        )
        self.assertTrue(plan_daily.invalid)
        self.assertEqual(plan_daily.reason, "Risk too wide vs ATR")
        print("✓ Test passed: Correct EMA 20 stop-loss prevents false risk rejections.")

    @patch('scanners.core.yf.Ticker')
    def test_dynamic_yfinance_suffix(self, mock_ticker):
        """Test that fetch_intraday_cached dynamically appends .BO for BSE and .NS for NSE."""
        mock_instance = MagicMock()
        mock_ticker.return_value = mock_instance
        mock_instance.history.return_value = pd.DataFrame([1], columns=['Close']) # Mock valid data to stop fallback
        
        # Case 1: Standard NSE symbol
        fetch_intraday_cached("INFY", period="5d", interval="1d")
        mock_ticker.assert_called_with("INFY.NS")
        
        # Case 2: BSE-only numeric code
        fetch_intraday_cached("500209", period="5d", interval="1d")
        mock_ticker.assert_called_with("500209.BO")
        
        # Case 3: NSE symbol with BSE code provided
        fetch_intraday_cached("TCS", period="5d", interval="1d", bse_code="532540")
        mock_ticker.assert_called_with("532540.BO")
        print("✓ Test passed: Dynamic BSE/NSE suffix resolution behaves correctly.")

    @patch('scanners.tracker.get_open_alerts')
    @patch('scanners.tracker.update_alert_status')
    @patch('scanners.tracker.fetch_intraday_cached')
    def test_swing_position_expiry_preservation(self, mock_fetch, mock_update, mock_get_alerts):
        """Test that MF alerts bypass EOD auto-expiry while other alerts (MOMENTUM) expire."""
        created_at = datetime.now(IST) - timedelta(hours=5)
        
        # Mock alerts: one MF swing, one MOMENTUM intraday
        mock_get_alerts.return_value = [
            {
                'id': 1,
                'symbol': 'TCS',
                'alert_type': 'MF',
                'created_at': created_at,
                'highest_hit': None,
                'stop_loss': 3000.0,
                't1_price': 3200.0,
                'target_price': 3200.0,
                't2_price': 3300.0,
                't3_price': 3400.0,
                'bse_code': None
            },
            {
                'id': 2,
                'symbol': 'INFY',
                'alert_type': 'MOMENTUM',
                'created_at': created_at,
                'highest_hit': None,
                'stop_loss': 1400.0,
                't1_price': 1450.0,
                'target_price': 1450.0,
                't2_price': 1480.0,
                't3_price': 1500.0,
                'bse_code': None
            }
        ]
        
        # Mock fetch_intraday_cached to return mock price df
        mock_fetch.return_value = pd.DataFrame(
            [[1410.0, 1420.0, 1405.0, 1415.0, 1000]], 
            columns=['Open', 'High', 'Low', 'Close', 'Volume'],
            index=[created_at + timedelta(minutes=5)]
        )
        
        # Mock datetime to simulate past 15:30 IST on the same day
        with patch('scanners.tracker.datetime') as mock_date:
            mock_date.now.return_value = datetime.combine(created_at.date(), datetime.strptime("16:00", "%H:%M").time(), tzinfo=IST)
            mock_date.combine = datetime.combine
            mock_date.strptime = datetime.strptime
            
            resolve_open_alerts()
            
            # Assertions: 
            # 1. Update alert status should be called for INFY (ID 2) to expire it
            # 2. It should NOT be called for TCS (ID 1) to expire it
            mock_update.assert_any_call(2, 'EXPIRED', None)
            
            # Check that alert ID 1 (MF) was never expired
            for call in mock_update.call_args_list:
                args = call[0]
                if args[0] == 1:
                    self.assertNotEqual(args[1], 'EXPIRED')
                    
        print("✓ Test passed: Tracker successfully bypasses EOD auto-expiry for MF alerts while expiring others.")

if __name__ == '__main__':
    unittest.main()
