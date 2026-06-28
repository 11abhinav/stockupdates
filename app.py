import os
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
from zoneinfo import ZoneInfo
import time
import threading
import db

from collections import deque

_alerts_cache = {"data": [], "timestamp": 0}
_cache_lock = threading.Lock()

# Global system errors storage
global_system_errors = deque(maxlen=50)

class GlobalErrorHandler(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR and record.name != "yfinance":
            msg = self.format(record)
            global_system_errors.appendleft({
                "time": time.time(),
                "message": msg
            })

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("app")
error_handler = GlobalErrorHandler()
error_handler.setFormatter(logging.Formatter('%(message)s'))
log.addHandler(error_handler)

# Silence noisy third-party loggers
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-123')

# Initialize DB on startup
db.init_db()

def norm_pct(x):
    if x is None:
        return None
    try:
        x = float(x)
        return x / 100.0 if abs(x) > 1 else x
    except Exception as e:
        log.warning(f"norm_pct failed for {x}: {e}")
        return None

def norm_num(x):
    if x is None:
        return None
    try:
        return float(x)
    except Exception as e:
        log.warning(f"norm_num failed for {x}: {e}")
        return None

def norm_de_ratio(x):
    x = norm_num(x)
    if x is None:
        return None
    return x / 100.0 if x > 10 else x

def score_financial_quality(info, financials):
    score = 0.0
    fields_found = 0
    
    # 1. ROE / ROCE Proxy (Weight: 2)
    roe = norm_pct(info.get('returnOnEquity'))
    if roe is not None:
        fields_found += 1
        if roe >= 0.15:
            score += 2.0
        elif roe >= 0.10:
            score += 1.0

    # 2. Revenue Growth (Weight: 2)
    sales_cagr = None
    if financials is not None and not financials.empty:
        try:
            if 'Total Revenue' in financials.index and len(financials.columns) >= 4:
                rev_latest = norm_num(financials.loc['Total Revenue'].iloc[0])
                rev_3y = norm_num(financials.loc['Total Revenue'].iloc[3])
                if rev_3y and rev_latest and rev_3y > 0:
                    sales_cagr = ((rev_latest / rev_3y) ** (1/3)) - 1
        except Exception as e:
            sym = info.get('symbol', 'Unknown')
            log.warning(f"Failed to calculate revenue CAGR for {sym}: {e}")
            
    if sales_cagr is not None:
        fields_found += 1
        if sales_cagr >= 0.10:
            score += 2.0
        elif sales_cagr >= 0.05:
            score += 1.0
    else:
        rg = norm_pct(info.get('revenueGrowth'))
        if rg is not None:
            fields_found += 1
            if rg >= 0.10:
                score += 2.0
            elif rg >= 0.05:
                score += 1.0

    # 3. Earnings Growth (Weight: 2)
    profit_cagr = None
    if financials is not None and not financials.empty:
        try:
            if 'Net Income' in financials.index and len(financials.columns) >= 4:
                prof_latest = norm_num(financials.loc['Net Income'].iloc[0])
                prof_3y = norm_num(financials.loc['Net Income'].iloc[3])
                if prof_3y and prof_latest and prof_3y > 0:
                    profit_cagr = ((prof_latest / prof_3y) ** (1/3)) - 1
        except Exception as e:
            sym = info.get('symbol', 'Unknown')
            log.warning(f"Failed to calculate earnings CAGR for {sym}: {e}")
            
    if profit_cagr is not None:
        fields_found += 1
        if profit_cagr >= 0.10:
            score += 2.0
        elif profit_cagr >= 0.05:
            score += 1.0
    else:
        eg = norm_pct(info.get('earningsGrowth'))
        if eg is not None:
            fields_found += 1
            if eg >= 0.10:
                score += 2.0
            elif eg >= 0.05:
                score += 1.0

    # 4. Operating Margin (Weight: 1)
    opm = norm_pct(info.get('operatingMargins'))
    if opm is not None:
        fields_found += 1
        if opm >= 0.15:
            score += 1.0
        elif opm >= 0.08:
            score += 0.5

    # 5. Financial Leverage Proxy (Weight: 2) - ROA
    roa = norm_pct(info.get('returnOnAssets'))
    if roa is not None:
        fields_found += 1
        if roa >= 0.015:
            score += 2.0
        elif roa >= 0.005:
            score += 1.0

    # 6. Financial Cash Flow Proxy (Weight: 1) - Positive EPS
    eps = norm_num(info.get('trailingEps') or info.get('forwardEps'))
    if eps is not None:
        fields_found += 1
        if eps > 0:
            score += 1.0
            
    return score, fields_found, None


def score_nonfinancial_quality(info, financials):
    score = 0.0
    fields_found = 0
    hard_cap = None
    
    # 1. ROE / ROCE Proxy (Weight: 2)
    roe = norm_pct(info.get('returnOnEquity'))
    if roe is not None:
        fields_found += 1
        if roe >= 0.15:
            score += 2.0
        elif roe >= 0.10:
            score += 1.0

    # 2. Revenue Growth (Weight: 2)
    sales_cagr = None
    if financials is not None and not financials.empty:
        try:
            if 'Total Revenue' in financials.index and len(financials.columns) >= 4:
                rev_latest = norm_num(financials.loc['Total Revenue'].iloc[0])
                rev_3y = norm_num(financials.loc['Total Revenue'].iloc[3])
                if rev_3y and rev_latest and rev_3y > 0:
                    sales_cagr = ((rev_latest / rev_3y) ** (1/3)) - 1
        except Exception as e:
            sym = info.get('symbol', 'Unknown')
            log.warning(f"Failed to calculate revenue CAGR for {sym}: {e}")
            
    if sales_cagr is not None:
        fields_found += 1
        if sales_cagr >= 0.10:
            score += 2.0
        elif sales_cagr >= 0.05:
            score += 1.0
    else:
        rg = norm_pct(info.get('revenueGrowth'))
        if rg is not None:
            fields_found += 1
            if rg >= 0.10:
                score += 2.0
            elif rg >= 0.05:
                score += 1.0

    # 3. Earnings Growth (Weight: 2)
    profit_cagr = None
    if financials is not None and not financials.empty:
        try:
            if 'Net Income' in financials.index and len(financials.columns) >= 4:
                prof_latest = norm_num(financials.loc['Net Income'].iloc[0])
                prof_3y = norm_num(financials.loc['Net Income'].iloc[3])
                if prof_3y and prof_latest and prof_3y > 0:
                    profit_cagr = ((prof_latest / prof_3y) ** (1/3)) - 1
        except Exception as e:
            sym = info.get('symbol', 'Unknown')
            log.warning(f"Failed to calculate earnings CAGR for {sym}: {e}")
            
    if profit_cagr is not None:
        fields_found += 1
        if profit_cagr >= 0.10:
            score += 2.0
        elif profit_cagr >= 0.05:
            score += 1.0
    else:
        eg = norm_pct(info.get('earningsGrowth'))
        if eg is not None:
            fields_found += 1
            if eg >= 0.10:
                score += 2.0
            elif eg >= 0.05:
                score += 1.0

    # 4. Operating Margin (Weight: 1)
    opm = norm_pct(info.get('operatingMargins'))
    if opm is not None:
        fields_found += 1
        if opm >= 0.15:
            score += 1.0
        elif opm >= 0.08:
            score += 0.5

    # 5. Non-Financial Leverage (Weight: 2) - Debt/Equity
    de = norm_de_ratio(info.get('debtToEquity'))
    if de is not None:
        fields_found += 1
        if de <= 0.50:
            score += 2.0
        elif de <= 1.00:
            score += 1.0
        elif de > 2.00:
            hard_cap = 4.0
            
    # 6. Non-Financial Cash Flow (Weight: 1) - OCF
    ocf = norm_num(info.get('operatingCashflow'))
    if ocf is not None:
        fields_found += 1
        if ocf > 0:
            score += 1.0
        elif ocf < 0:
            score -= 1.0
            
    return score, fields_found, hard_cap


def calculate_quality_score(info, financials):
    if not info:
        return 0.0
        
    is_fin = is_financial_sector(info.get('sector'))
    if is_fin:
        score, fields_found, hard_cap = score_financial_quality(info, financials)
    else:
        score, fields_found, hard_cap = score_nonfinancial_quality(info, financials)
        
    if hard_cap is not None and score > hard_cap:
        score = hard_cap
        
    completeness = fields_found / 6.0
    if completeness >= 0.8:
        info['quality_confidence'] = "High"
    elif completeness >= 0.5:
        info['quality_confidence'] = "Medium"
    else:
        info['quality_confidence'] = "Low"
        score = min(score, 5.0)

    score = max(0.0, score)
    return round(score, 1)

def is_financial_sector(sector):
    if sector is None:
        return False
    s = str(sector).lower()
    if "financial" in s or "bank" in s or "insurance" in s or "nbfc" in s:
        return True
    return False

def compute_sector_medians(all_stocks):
    import statistics
    sector_data = {}
    for stock in all_stocks:
        sector = stock.get('sector')
        if not sector or sector == "Unknown":
            continue
            
        if sector not in sector_data:
            sector_data[sector] = {"pe_list": [], "pb_list": [], "roe_list": []}
            
        pe = norm_num(stock.get('pe'))
        if pe is not None and pe > 0:
            sector_data[sector]["pe_list"].append(pe)
            
        pb = norm_num(stock.get('pb'))
        if pb is not None and pb > 0:
            sector_data[sector]["pb_list"].append(pb)
            
        roe = norm_pct(stock.get('roe'))
        if roe is not None and roe > 0:
            sector_data[sector]["roe_list"].append(roe)
            
    medians = {}
    for sector, data in sector_data.items():
        pe_list = data["pe_list"]
        pb_list = data["pb_list"]
        roe_list = data["roe_list"]
        
        medians[sector] = {
            "median_pe": statistics.median(pe_list) if len(pe_list) >= 3 else None,
            "median_pb": statistics.median(pb_list) if len(pb_list) >= 3 else None,
            "median_roe": statistics.median(roe_list) if len(roe_list) >= 3 else None
        }
    return medians

def calculate_value_score(stock, sector_medians):
    score = 0
    confidence = "HIGH"
    sector = stock.get('sector')
    med = sector_medians.get(sector)
    
    if not med:
        confidence = "LOW"
        med = {}
    
    stock_pb = stock.get('pb')
    stock_pe = stock.get('pe')
    stock_roe = stock.get('roe')
    stock_div = stock.get('div_yield')
    
    if is_financial_sector(sector):
        # 1. P/B relative to sector
        if stock_pb is not None and stock_pb > 0:
            sector_pb = med.get("median_pb")
            if sector_pb is not None:
                if stock_pb <= sector_pb:
                    score += 5
                elif stock_pb <= sector_pb * 1.2:
                    score += 3
            else:
                if stock_pb <= 2.0:
                    score += 5
                elif stock_pb <= 3.5:
                    score += 3
        else:
            confidence = "LOW"
                    
        # 2. ROE relative to sector
        if stock_roe is not None:
            sector_roe = med.get("median_roe")
            if sector_roe is not None:
                if stock_roe >= sector_roe:
                    score += 5
                elif stock_roe >= sector_roe * 0.8:
                    score += 3
            else:
                if stock_roe >= 0.16:
                    score += 5
                elif stock_roe >= 0.12:
                    score += 3
        else:
            confidence = "LOW"
    else:
        # 1. P/E relative to sector
        if stock_pe is not None and stock_pe > 0:
            sector_pe = med.get("median_pe")
            if sector_pe is not None:
                if stock_pe <= sector_pe:
                    score += 5
                elif stock_pe <= sector_pe * 1.2:
                    score += 3
            else:
                if stock_pe <= 20:
                    score += 5
                elif stock_pe <= 35:
                    score += 3
        else:
            confidence = "LOW"
                    
        # 2. P/B relative to sector
        if stock_pb is not None and stock_pb > 0:
            sector_pb = med.get("median_pb")
            if sector_pb is not None:
                if stock_pb <= sector_pb:
                    score += 4
                elif stock_pb <= sector_pb * 1.2:
                    score += 2
            else:
                if stock_pb <= 2.5:
                    score += 4
                elif stock_pb <= 4.5:
                    score += 2
        else:
            confidence = "LOW"
                    
        # 3. Dividend yield
        if stock_div is not None and stock_div >= 0.005:
            score += 1
            
    return round(score, 1), confidence

def calculate_fair_value(stock, current_price, sector_medians):
    sector = stock.get('sector')
    med = sector_medians.get(sector, {})
    
    if is_financial_sector(sector):
        sector_pb = med.get("median_pb")
        stock_bvps = norm_num(stock.get('bvps'))
        if sector_pb is not None and stock_bvps is not None and stock_bvps > 0:
            fair_value = sector_pb * stock_bvps
            return fair_value, "SECTOR_PB"
    else:
        sector_pe = med.get("median_pe")
        stock_eps = norm_num(stock.get('eps'))
        if sector_pe is not None and stock_eps is not None and stock_eps > 0:
            fair_value = sector_pe * stock_eps
            return fair_value, "SECTOR_PE"
            
    if current_price is not None:
        fallback_value = current_price * 0.90
        return fallback_value, "FALLBACK"
        
    return None, "UNAVAILABLE"

def build_valuation_output(stock, current_price, sector_medians):
    value_score, val_confidence = calculate_value_score(stock, sector_medians)
    fair_value, mode = calculate_fair_value(stock, current_price, sector_medians)
    
    valuation_label = "UNKNOWN"
    if fair_value is not None and current_price is not None and current_price > 0:
        if mode == "FALLBACK":
            valuation_label = "LOW_CONFIDENCE"
        else:
            upside_pct = ((fair_value - current_price) / current_price) * 100
            if upside_pct >= 20:
                valuation_label = "UNDERVALUED"
            elif upside_pct >= 0:
                valuation_label = "FAIR"
            else:
                valuation_label = "OVERVALUED"
                
    if val_confidence == "LOW" and valuation_label not in ["LOW_CONFIDENCE", "UNKNOWN"]:
        valuation_label = f"{valuation_label} (LOW CONFIDENCE)"
            
    absolute_warning = None
    if not is_financial_sector(stock.get('sector')):
        pe = stock.get('pe')
        if pe is not None and pe > 60:
            absolute_warning = "ABSOLUTE_PE_TOO_HIGH"
            
    return {
        "value_score": value_score,
        "fair_value": fair_value,
        "valuation_mode": mode,
        "valuation_label": valuation_label,
        "absolute_warning": absolute_warning,
        "valuation_confidence": val_confidence
    }

def fetch_and_save_raw_metrics(symbol, bse_code=None, ticker=None):
    try:
        import yfinance as yf
        if not ticker:
            ticker = yf.Ticker(f"{symbol}.NS")
            if ticker.history(period="1d").empty and bse_code:
                ticker = yf.Ticker(f"{bse_code}.BO")
        info = ticker.info
        financials = ticker.financials
        
        q_score = calculate_quality_score(info, financials)
        
        sector = info.get('sector')
        pe = norm_num(info.get('trailingPE') or info.get('peRatio'))
        pb = norm_num(info.get('priceToBook') or info.get('pbRatio'))
        roe = norm_pct(info.get('returnOnEquity'))
        eps = norm_num(info.get('trailingEps') or info.get('forwardEps'))
        bvps = norm_num(info.get('bookValue'))
        div_yield = norm_pct(info.get('dividendYield') or info.get('divYield'))
        current_price = norm_num(info.get('currentPrice') or info.get('regularMarketPrice'))
        
        db.update_fundamental_metrics(symbol, sector, pe, pb, roe, eps, bvps, div_yield)
        
        current_stock = {
            'sector': sector,
            'pe': pe,
            'pb': pb,
            'roe': roe,
            'eps': eps,
            'bvps': bvps,
            'div_yield': div_yield
        }
        return q_score, current_stock, current_price, info
    except Exception as e:
        log.warning(f"Failed to fetch raw metrics for {symbol}: {e}")
        return None, None, None, None

def refresh_universe(symbols):
    all_rows = []
    watchlist = db.get_watchlist()
    bse_map = {w['symbol']: w['bse_code'] for w in watchlist}
    
    for sym in symbols:
        bse_code = bse_map.get(sym)
        q_score, current_stock, current_price, info = fetch_and_save_raw_metrics(sym, bse_code=bse_code)
        if current_stock:
            all_rows.append((sym, q_score, current_stock, current_price, info))
        time.sleep(2) # rate limit protection
        
    all_stocks = db.get_all_fundamentals()
    sector_medians = compute_sector_medians(all_stocks)
    
    results = []
    for sym, q_score, current_stock, current_price, info in all_rows:
        val_output = build_valuation_output(current_stock, current_price, sector_medians)
        v_score = val_output["value_score"]
        
        db.update_fundamental_scores(sym, q_score, v_score)
        db.update_valuation_fields(sym, v_score, val_output["fair_value"], val_output["valuation_label"])
        
        legacy_score = int((q_score + v_score) / 2) if q_score is not None and v_score is not None else None
        if legacy_score is not None:
            db.update_fundamental_score(sym, legacy_score)
            
        results.append((sym, q_score, v_score, info))
    
    return results, sector_medians

def fetch_and_save_fundamentals(symbol, bse_code=None, ticker=None):
    q_score, current_stock, current_price, info = fetch_and_save_raw_metrics(symbol, bse_code, ticker)
    if not current_stock:
        return None, None, None
        
    # Single fetch: compute against existing full database medians
    all_stocks = db.get_all_fundamentals()
    sector_medians = compute_sector_medians(all_stocks)
    
    val_output = build_valuation_output(current_stock, current_price, sector_medians)
    v_score = val_output["value_score"]
    fair_value = val_output["fair_value"]
    valuation_label = val_output["valuation_label"]
    
    db.update_fundamental_scores(symbol, q_score, v_score)
    db.update_valuation_fields(symbol, v_score, fair_value, valuation_label)
    
    legacy_score = int((q_score + v_score) / 2) if q_score is not None and v_score is not None else None
    if legacy_score is not None:
        db.update_fundamental_score(symbol, legacy_score)
        
    info['valuation_label'] = valuation_label
    info['fair_value'] = fair_value
    info['valuation_mode'] = val_output["valuation_mode"]
    info['absolute_warning'] = val_output["absolute_warning"]
    info['valuation_confidence'] = val_output["valuation_confidence"]
    
    return q_score, v_score, info

def backfill_missing_fundamental_scores():
    # Wait a brief moment to let the server start up
    time.sleep(5)
    log.info("Starting background backfill of missing fundamental scores...")
    try:
        prices = db.get_all_prices()
        symbols_to_fetch = [p['symbol'] for p in prices if p.get('quality_score') is None or p.get('value_score') is None]
        if symbols_to_fetch:
            log.info(f"Backfilling {len(symbols_to_fetch)} symbols...")
            refresh_universe(symbols_to_fetch)
        log.info("Background fundamental score backfill complete.")
    except Exception as e:
        log.error(f"Error in backfill_missing_fundamental_scores background thread: {e}")

def scheduled_universe_refresh():
    """Runs nightly to refresh ALL fundamentals and medians."""
    log.info("Starting scheduled nightly universe refresh...")
    try:
        prices = db.get_all_prices()
        symbols = [p['symbol'] for p in prices]
        if symbols:
            refresh_universe(symbols)
            log.info(f"Nightly refresh complete for {len(symbols)} symbols.")
    except Exception as e:
        log.error(f"Error in scheduled nightly refresh: {e}")

# Setup APScheduler
# Register Dual Scanners (IST Native)
import scanners.mf
import scanners.momentum
import scanners.news
import scanners.tracker

# Setup APScheduler
ist_tz = ZoneInfo("Asia/Kolkata")
job_defaults = {
    'misfire_grace_time': 120,
    'max_instances': 1,
    'coalesce': True
}
scheduler = BackgroundScheduler(timezone=ist_tz, job_defaults=job_defaults)

# MF Breakout Scanner (Every 30 min during market hours)
scheduler.add_job(
    scanners.mf.run, CronTrigger(day_of_week='mon-fri', hour='9', minute='15,45', timezone=ist_tz),
    id='mf_9', replace_existing=True
)
scheduler.add_job(
    scanners.mf.run, CronTrigger(day_of_week='mon-fri', hour='10-14', minute='15,45', timezone=ist_tz),
    id='mf_10_14', replace_existing=True
)
scheduler.add_job(
    scanners.mf.run, CronTrigger(day_of_week='mon-fri', hour='15', minute='15', timezone=ist_tz),
    id='mf_15', replace_existing=True
)

# Momentum Scanner (Every 5 min during market hours)
scheduler.add_job(
    scanners.momentum.run, CronTrigger(day_of_week='mon-fri', hour='9', minute='15,20,25,30,35,40,45,50,55', timezone=ist_tz),
    id='momentum_9', replace_existing=True
)
scheduler.add_job(
    scanners.momentum.run, CronTrigger(day_of_week='mon-fri', hour='10-14', minute='*/5', timezone=ist_tz),
    id='momentum_10_14', replace_existing=True
)
scheduler.add_job(
    scanners.momentum.run, CronTrigger(day_of_week='mon-fri', hour='15', minute='0,5,10,15,20,25,30', timezone=ist_tz),
    id='momentum_15', replace_existing=True
)

# News/BSE Scanner
scheduler.add_job(
    scanners.news.run_bse_scan, CronTrigger(day_of_week='mon-fri', hour='9-15', minute='15,45', timezone=ist_tz),
    id='news_9_15', replace_existing=True
)

# Nightly Fundamentals Refresh (1:00 AM IST)
scheduler.add_job(
    scheduled_universe_refresh, CronTrigger(hour='1', minute='0', timezone=ist_tz),
    id='nightly_fundamentals', replace_existing=True
)

# Tracker Scanner (Let it run until 15:55 to catch post-market closures)
scheduler.add_job(
    scanners.tracker.resolve_open_alerts, CronTrigger(day_of_week='mon-fri', hour='9-15', minute='*/5', timezone=ist_tz),
    id='tracker_9_15', replace_existing=True
)

if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
    scheduler.start()
    
    # Spawn background thread to backfill missing scores for existing stocks
    threading.Thread(target=backfill_missing_fundamental_scores, daemon=True).start()
atexit.register(lambda: scheduler.shutdown(wait=False))

@app.route('/')
def index():
    try:
        prices = db.get_all_prices()
        
        with _cache_lock:
            now = time.time()
            if now - _alerts_cache["timestamp"] < 30 and _alerts_cache["data"]:
                recent_alerts = _alerts_cache["data"]
            else:
                recent_alerts = db.get_recent_alerts(200)
                _alerts_cache["data"] = recent_alerts
                _alerts_cache["timestamp"] = now
            
        alerts_by_symbol = set(a['symbol'] for a in recent_alerts)
        
        ist = ZoneInfo("Asia/Kolkata")
        utc = ZoneInfo("UTC")
        
        for p in prices:
            p['has_alert'] = p['symbol'] in alerts_by_symbol
            if p.get('last_fetched'):
                dt = p['last_fetched']
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=utc)
                p['last_fetched'] = dt.astimezone(ist)
                
        price_map = {p['symbol']: float(p['latest_price']) if p.get('latest_price') else None for p in prices}

        for a in recent_alerts:
            if a.get('created_at'):
                dt = a['created_at']
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=utc)
                a['created_at'] = dt.astimezone(ist)

            # Dynamic Capital Sizing and PnL calculation
            # High Setup Score (>=7.5): risk ₹50,000
            # Med Setup Score (>=5.0): risk ₹25,000
            # Low/Caution Score (<5.0): risk ₹10,000
            a['pnl'] = 0.0
            a['allocated_capital'] = 0.0
            
            entry = float(a['entry_price']) if a.get('entry_price') else None
            sl = float(a['stop_loss']) if a.get('stop_loss') else None
            conf = float(a['confidence']) if a.get('confidence') else 5.0
            
            if conf >= 7.5:
                allocated_risk = 50000.0
                a['risk_label'] = "₹50k Risk (High Quality Setup)"
            elif conf >= 5.0:
                allocated_risk = 25000.0
                a['risk_label'] = "₹25k Risk (Medium Quality Setup)"
            else:
                allocated_risk = 10000.0
                a['risk_label'] = "₹10k Risk (Speculative Setup)"
                
            risk_per_share = float(a['risk_per_share']) if a.get('risk_per_share') else (entry - sl if entry and sl else 1.0)
            
            if entry and sl and risk_per_share > 0:
                qty = int(allocated_risk / risk_per_share)
                a['position_size_hint'] = qty # override default flat 10k sized quantity
                a['allocated_capital'] = entry * qty
                
                if a.get('status') == 'CLOSED_WIN':
                    target = entry
                    if a.get('highest_hit') == 'T3' and a.get('t3_price'):
                        target = float(a['t3_price'])
                    elif a.get('highest_hit') == 'T2' and a.get('t2_price'):
                        target = float(a['t2_price'])
                    elif a.get('t1_price'):
                        target = float(a['t1_price'])
                    a['pnl'] = (target - entry) * qty
                elif a.get('status') == 'CLOSED_LOSS':
                    a['pnl'] = (sl - entry) * qty
                elif a.get('status') == 'OPEN' or not a.get('status'):
                    current_price = price_map.get(a['symbol'])
                    if current_price:
                        a['pnl'] = (current_price - entry) * qty
            
        # Sort prices: those with alerts first, then alphabetically
        prices.sort(key=lambda x: (not x.get('has_alert', False), x['symbol']))
        
        return render_template('index.html', prices=prices, all_alerts=recent_alerts)
    except Exception as e:
        import traceback
        return f"<h1>Error Occurred</h1><pre>{traceback.format_exc()}</pre>", 200

@app.route('/api/stock/<symbol>')
def api_stock(symbol):
    try:
        symbol = symbol.upper()
        
        # Fetch live price on-demand when clicked
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        hist = ticker.history(period="5d")
        if not hist.empty and len(hist) >= 2:
            live_price = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2])
            change_pct = ((live_price - prev_close) / prev_close) * 100
            # Update DB with fresh price
            db.update_price(symbol, live_price, change_pct)
            
        prices = db.get_all_prices()
        stock_data = next((p for p in prices if p['symbol'] == symbol), None)
        if not stock_data:
            return jsonify({'error': 'Stock not found'}), 404
            
        alerts = db.get_stock_alerts(symbol, limit=50)
        current_price = float(stock_data['latest_price']) if stock_data.get('latest_price') else None
        
        for a in alerts:
            a['pnl'] = 0.0
            a['allocated_capital'] = 0.0
            
            entry = float(a['entry_price']) if a.get('entry_price') else None
            sl = float(a['stop_loss']) if a.get('stop_loss') else None
            conf = float(a['confidence']) if a.get('confidence') else 5.0
            
            if conf >= 7.5:
                allocated_risk = 50000.0
                a['risk_label'] = "₹50k Risk (High Quality Setup)"
            elif conf >= 5.0:
                allocated_risk = 25000.0
                a['risk_label'] = "₹25k Risk (Medium Quality Setup)"
            else:
                allocated_risk = 10000.0
                a['risk_label'] = "₹10k Risk (Speculative Setup)"
                
            risk_per_share = float(a['risk_per_share']) if a.get('risk_per_share') else (entry - sl if entry and sl else 1.0)
            
            if entry and sl and risk_per_share > 0:
                qty = int(allocated_risk / risk_per_share)
                a['position_size_hint'] = qty
                a['allocated_capital'] = entry * qty
                
                if a.get('status') == 'CLOSED_WIN':
                    target = entry
                    if a.get('highest_hit') == 'T3' and a.get('t3_price'):
                        target = float(a['t3_price'])
                    elif a.get('highest_hit') == 'T2' and a.get('t2_price'):
                        target = float(a['t2_price'])
                    elif a.get('t1_price'):
                        target = float(a['t1_price'])
                    a['pnl'] = (target - entry) * qty
                elif a.get('status') == 'CLOSED_LOSS':
                    a['pnl'] = (sl - entry) * qty
                elif a.get('status') == 'OPEN' or not a.get('status'):
                    if current_price:
                        a['pnl'] = (current_price - entry) * qty
        
        # Fetch news and fundamentals
        news = []
        fundamentals = {}
        fundamental_score = stock_data.get('fundamental_score')
        try:
            import feedparser
            url = f"https://news.google.com/rss/search?q={symbol}+NSE+stock+when:7d"
            feed = feedparser.parse(url)
            
            for entry in feed.entries[:5]:
                import dateutil.parser
                try:
                    dt = dateutil.parser.parse(entry.get("published", ""))
                    time_val = dt.timestamp()
                except Exception as e:
                    log.warning(f"News date parsing failed for {symbol}: {e}")
                    time_val = None
                    
                news.append({
                    'title': entry.get("title", ""),
                    'publisher': entry.get("source", {}).get("title", "News") if hasattr(entry, 'source') else "News",
                    'link': entry.get("link", ""),
                    'time': time_val
                })
        except Exception as e:
            log.warning(f"Failed to fetch Google News for {symbol}: {e}")
            
        quality_score = stock_data.get('quality_score')
        value_score = stock_data.get('value_score')
        chart_data = []
        try:
            q_score, v_score, info = fetch_and_save_fundamentals(symbol, ticker)
            if q_score is not None:
                quality_score = q_score
                value_score = v_score
            if info:
                fundamentals = {
                    'marketCap': info.get('marketCap'),
                    'peRatio': info.get('trailingPE') or info.get('peRatio'),
                    'pbRatio': info.get('priceToBook') or info.get('pbRatio'),
                    'divYield': info.get('dividendYield', 0) * 100 if info.get('dividendYield') else None,
                    'high52': info.get('fiftyTwoWeekHigh'),
                    'low52': info.get('fiftyTwoWeekLow'),
                    'sector': info.get('sector'),
                    'industry': info.get('industry'),
                    # Score card checklist fields:
                    'roe': info.get('returnOnEquity'),
                    'debtToEquity': info.get('debtToEquity'),
                    'operatingMargins': info.get('operatingMargins'),
                    'operatingCashflow': info.get('operatingCashflow'),
                    'revenueGrowth': info.get('revenueGrowth'),
                    'earningsGrowth': info.get('earningsGrowth'),
                    'enterpriseToEbitda': info.get('enterpriseToEbitda'),
                    'enterpriseToRevenue': info.get('enterpriseToRevenue') or info.get('priceToSalesTrailing12Months'),
                    'quality_confidence': info.get('quality_confidence', 'Unknown'),
                    'fairValue': info.get('fair_value'),
                    'valuationLabel': info.get('valuation_label'),
                    'valuationMode': info.get('valuation_mode'),
                    'valuationConfidence': info.get('valuation_confidence'),
                    'absoluteWarning': info.get('absolute_warning')
                }
            
            # Fetch daily candlestick history for interactive charts (5 years)
            hist_daily = ticker.history(period="5y", interval="1d")
            for index, row in hist_daily.iterrows():
                chart_data.append({
                    'time': index.strftime('%Y-%m-%d'),
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                })
        except Exception as e:
            log.warning(f"Failed to fetch news/fundamentals/charts for {symbol}: {e}")

        return jsonify({
            'symbol': symbol,
            'price': stock_data['latest_price'],
            'change_pct': stock_data['change_pct'],
            'last_fetched': stock_data['last_fetched'].isoformat() if stock_data.get('last_fetched') else None,
            'alerts': alerts,
            'news': news,
            'fundamentals': fundamentals,
            'quality_score': quality_score,
            'value_score': value_score,
            'chart_data': chart_data
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prices')
def get_prices():
    try:
        prices = db.get_all_prices()
        price_map = {}
        for p in prices:
            price_map[p['symbol']] = {
                'latest_price': float(p['latest_price']) if p['latest_price'] else None,
                'change_pct': float(p['change_pct']) if p['change_pct'] else None,
                'last_fetched': p['last_fetched'].isoformat() if p['last_fetched'] else None,
                'quality_score': float(p['quality_score']) if p['quality_score'] is not None else None,
                'value_score': float(p['value_score']) if p['value_score'] is not None else None
            }
        return jsonify(price_map)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/refresh_watchlist')
def api_refresh_watchlist():
    try:
        watchlist = db.get_watchlist()
        symbols = [w['symbol'] for w in watchlist]
        
        import yfinance as yf
        # Batch download all tickers for 5 days to get prev close
        df = yf.download([f"{s}.NS" for s in symbols], period="5d", progress=False)
        
        if not df.empty and len(df) >= 2:
            for s in symbols:
                try:
                    # if only 1 symbol, df structure is different than if multiple
                    if len(symbols) == 1:
                        live_price = float(df['Close'].iloc[-1])
                        prev_close = float(df['Close'].iloc[-2])
                    else:
                        live_price = float(df['Close'][f"{s}.NS"].iloc[-1])
                        prev_close = float(df['Close'][f"{s}.NS"].iloc[-2])
                        
                    if not __import__("math").isnan(live_price) and not __import__("math").isnan(prev_close) and prev_close > 0:
                        change_pct = ((live_price - prev_close) / prev_close) * 100
                        db.update_price(s, live_price, change_pct)
                except Exception as e:
                    pass
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/search')
def api_search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    try:
        import requests
        headers = {'User-Agent': 'Mozilla/5.0'}
        # Search Yahoo Finance, filtering for NSE (.NS) and BSE (.BO) stocks
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=15&newsCount=0"
        resp = requests.get(url, headers=headers, timeout=5)
        data = resp.json()
        results = []
        for quote in data.get('quotes', []):
            symbol = quote.get('symbol', '')
            exchange = quote.get('exchange', '')
            # Allow both NSE and BSE stocks, but avoid indices starting with 0P
            if exchange in ['NSI', 'BSE'] and not symbol.startswith('0P'):
                clean_symbol = symbol.replace('.NS', '').replace('.BO', '')
                results.append({
                    'symbol': clean_symbol,
                    'name': quote.get('shortname', quote.get('longname', '')),
                    'exchange': 'NSE' if exchange == 'NSI' else 'BSE'
                })
        
        # Deduplicate by symbol
        seen = set()
        deduped = []
        for r in results:
            if r['symbol'] not in seen:
                seen.add(r['symbol'])
                deduped.append(r)
                
        return jsonify(deduped)
    except Exception as e:
        log.error(f"Search API Error: {e}")
        return jsonify([])

@app.route('/api/remove_stock/<symbol>', methods=['POST'])
def api_remove_stock(symbol):
    try:
        success = db.remove_stock(symbol)
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Failed to remove stock'})
    except Exception as e:
        log.error(f"Remove stock error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clean_dummy_alerts')
def api_clean_dummy_alerts():
    try:
        with db.get_db_connection() as conn:
            if not conn: return jsonify({'error': 'No DB connection'})
            with conn.cursor() as cur:
                # Forcefully wipe ALL alerts to guarantee no mock data is left behind
                cur.execute("TRUNCATE TABLE stockupdates.alerts RESTART IDENTITY;")
                conn.commit()
        
        # Clear the memory cache as well so the UI updates instantly
        global _alerts_cache
        with _cache_lock:
            _alerts_cache["data"] = []
            _alerts_cache["timestamp"] = 0
        
        return jsonify({'success': True, 'message': 'ALL alerts have been completely wiped. Dashboard is fresh!'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        symbol = request.form.get('symbol', '').strip().upper()
        bse_code = request.form.get('bse_code', '').strip()
        
        if not symbol and bse_code:
            symbol = str(bse_code)
            
        if not symbol and not bse_code:
            flash("Error: Either NSE Symbol or BSE Code is required.", "error")
            return redirect(url_for('admin'))
        
        if symbol:
            # Check for duplicates
            watchlist = db.get_watchlist()
            if any(w['symbol'] == symbol for w in watchlist):
                flash(f"Error: {symbol} is already in the watchlist.", "error")
                return redirect(url_for('admin'))
                
            if not bse_code:
                # Auto-fetch BSE code from Screener.in if not provided
                try:
                    import requests
                    import re
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5'
                    }
                    res = requests.get(f'https://www.screener.in/company/{symbol}/', headers=headers, timeout=5)
                    if res.status_code == 200:
                        match = re.search(r'BSE:\s*(\d{6})', res.text)
                        if match:
                            bse_code = match.group(1)
                    else:
                        log.warning(f"Screener returned status {res.status_code} for {symbol}")
                except Exception as e:
                    log.error(f"Failed to auto-fetch BSE code for {symbol}: {e}")
            
            if not bse_code:
                bse_code = None

            # Check if valid ticker
            valid_nse = False
            valid_bse = False
            ticker = None
            try:
                import yfinance as yf
                ticker = yf.Ticker(symbol + ".NS")
                hist = ticker.history(period="1d")
                if not hist.empty:
                    valid_nse = True
                elif bse_code:
                    ticker = yf.Ticker(bse_code + ".BO")
                    hist = ticker.history(period="1d")
                    if not hist.empty:
                        valid_bse = True
            except Exception as e:
                log.error(f"Error validating {symbol}: {e}")

            if not valid_nse and not valid_bse:
                flash(f"Error: {symbol} is invalid on NSE, and no valid BSE data was found (tried {bse_code}.BO).", "error")
                return redirect(url_for('admin'))

            db.add_stock(symbol, bse_code)
            try:
                fetch_and_save_fundamentals(symbol, bse_code, ticker)
            except Exception as e:
                log.error(f"Error calculating fundamental score on addition of {symbol}: {e}")
            flash(f"Success: {symbol} added to watchlist.", "success")
            return redirect(url_for('admin'))
            
    prices = db.get_all_prices()
    recent_alerts = db.get_recent_alerts(200)
    alerts_by_symbol = set(a['symbol'] for a in recent_alerts)
    
    ist = ZoneInfo("Asia/Kolkata")
    utc = ZoneInfo("UTC")
    
    for p in prices:
        p['has_alert'] = p['symbol'] in alerts_by_symbol
        if p.get('last_fetched'):
            dt = p['last_fetched']
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=utc)
            p['last_fetched'] = dt.astimezone(ist)
            
    # Sort prices: those with alerts first, then alphabetically
    prices.sort(key=lambda x: (not x.get('has_alert', False), x['symbol']))
        
    return render_template('admin.html', watchlist=prices)


@app.route('/api/admin/scanner_status', methods=['GET'])
def api_scanner_status():
    """Return health status for all scanners."""
    from scanners.health import get_all_status
    return jsonify(get_all_status())

@app.route('/api/admin/fyers_status', methods=['GET'])
def api_fyers_status():
    """Check if Fyers API is configured and working."""
    import os
    client_id = os.environ.get("FYERS_CLIENT_ID")
    if not client_id:
        return jsonify({"status": "not_configured", "message": "FYERS_CLIENT_ID not set in environment variables."})
    
    missing = []
    for var in ["FYERS_SECRET_KEY", "FYERS_TOTP_SECRET", "FYERS_PIN", "FYERS_USER_ID"]:
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        return jsonify({"status": "incomplete", "message": f"Missing variables: {', '.join(missing)}", "client_id": client_id})
    
    try:
        from scanners.fyers_client import get_fyers_instance
        fyers = get_fyers_instance()
        if fyers:
            # Try a simple profile call to verify token works
            profile = fyers.get_profile()
            return jsonify({
                "status": "connected",
                "message": "Fyers API is authenticated and working!",
                "client_id": client_id,
                "profile": profile.get("data", {})
            })
        else:
            return jsonify({"status": "login_failed", "message": "Fyers login failed. Check your TOTP secret and PIN.", "client_id": client_id})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Fyers connection error: {str(e)}", "client_id": client_id})

@app.route('/api/admin/run_scanner/<name>', methods=['POST'])
def api_run_scanner(name):
    """Manually trigger a scanner run in the background."""
    name = name.upper()
    if name == 'MF':
        threading.Thread(target=scanners.mf.run, daemon=True).start()
        return jsonify({"status": "success", "message": "MF Scanner started in background."})
    elif name == 'MOMENTUM':
        threading.Thread(target=scanners.momentum.run, daemon=True).start()
        return jsonify({"status": "success", "message": "Momentum Scanner started in background."})
    else:
        return jsonify({"status": "error", "message": f"Unknown scanner: {name}"}), 400

@app.route('/api/admin/acknowledge_error', methods=['POST'])
def api_acknowledge_error():
    """Acknowledge and remove a non-critical error from the dashboard."""
    from scanners.health import acknowledge_error
    data = request.get_json()
    scanner = data.get('scanner')
    error_key = data.get('error_key')
    if not scanner or not error_key:
        return jsonify({"status": "error", "message": "Missing scanner or error_key"}), 400
    acknowledge_error(scanner, error_key)
    return jsonify({"status": "success"})

@app.route('/api/admin/clear_errors', methods=['POST'])
def api_clear_errors():
    """Clear all non-critical errors for a scanner."""
    from scanners.health import clear_all_errors
    data = request.get_json()
    scanner = data.get('scanner')
    if not scanner:
        return jsonify({"status": "error", "message": "Missing scanner"}), 400
    clear_all_errors(scanner)
    return jsonify({"status": "success"})

@app.route('/api/notifications', methods=['GET'])
def api_notifications():
    """Poll for new alerts and scanner status changes for toast notifications."""
    from scanners.health import get_all_status
    since = request.args.get('since', '0')
    try:
        since_ts = float(since)
    except ValueError:
        since_ts = 0
    
    notifications = []
    
    # Check for scanner DOWN/DATA_STALE
    statuses = get_all_status()
    for name, s in statuses.items():
        if s['status'] in ('DOWN', 'DATA_STALE'):
            notifications.append({
                'type': 'scanner_down',
                'scanner': name,
                'status': s['status'],
                'message': s['critical_error'] or f'{name} scanner is {s["status"]}',
            })
    
    # Check for recent alerts
    recent_alerts = db.get_recent_alerts(10)
    for a in recent_alerts:
        created = a.get('created_at')
        if created:
            alert_ts = created.timestamp() if hasattr(created, 'timestamp') else 0
            if alert_ts > since_ts:
                notifications.append({
                    'type': 'new_alert',
                    'symbol': a.get('symbol'),
                    'alert_type': a.get('alert_type'),
                    'message': f"{a.get('alert_type', 'ALERT')} | {a.get('symbol', '?')}: New signal detected",
                    'timestamp': alert_ts,
                })
    
    return jsonify({"notifications": notifications, "server_time": time.time()})

@app.route('/api/admin/system_errors')
def api_system_errors():
    return jsonify(list(global_system_errors))

@app.route('/api/admin/clear_system_errors', methods=['POST'])
def api_clear_system_errors():
    global_system_errors.clear()
    return jsonify({"status": "success"})

@app.route('/api/admin/force_refresh', methods=['GET', 'POST'])
def api_force_refresh():
    """Endpoint to manually trigger a full universe refresh on Railway."""
    def run_refresh_background():
        try:
            import time
            log.info("Force refresh triggered via API...")
            prices = db.get_all_prices()
            symbols = [p['symbol'] for p in prices]
            if symbols:
                refresh_universe(symbols)
                log.info(f"Force refresh complete for {len(symbols)} symbols.")
        except Exception as e:
            log.error(f"Error in force refresh background thread: {e}")
            
    import threading
    threading.Thread(target=run_refresh_background, daemon=True).start()
    
    return jsonify({
        "status": "success",
        "message": "Full fundamentals and valuation refresh started in the background. Please wait a few minutes for it to complete."
    })


def _shutdown_scheduler():
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    except Exception as e:
        log.warning(f"Scheduler shutdown skipped: {e}")

import atexit
atexit.register(_shutdown_scheduler)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
