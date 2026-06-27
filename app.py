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

_alerts_cache = {"data": [], "timestamp": 0}
_cache_lock = threading.Lock()

# Initialize logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-123')

# Initialize DB on startup
db.init_db()

def calculate_fundamental_score(info, financials):
    """
    Calculate a score out of 7 points based on key fundamental metrics:
    - Market Cap >= 5,000 Cr (50 Billion INR): +1
    - ROCE/ROE >= 15%: +1
    - Debt/Equity <= 0.5 (or debtToEquity <= 50 in yfinance): +1
    - 3Y Sales CAGR >= 10% (fallback to revenueGrowth >= 10%): +1
    - 3Y Profit CAGR >= 10% (fallback to earningsGrowth >= 10%): +1
    - Latest year operating cash flow > 0: +1
    - Operating Margin >= 15% (substitute for promoter pledge): +1
    """
    if not info:
        return 0
    score = 0
    
    # 1. Market Cap >= 5,000 Cr (50 Billion INR)
    mcap = info.get('marketCap')
    if mcap is not None:
        try:
            if float(mcap) >= 50000000000:
                score += 1
        except:
            pass
            
    # 2. ROCE/ROE >= 15%
    roe = info.get('returnOnEquity')
    if roe is not None:
        try:
            if float(roe) >= 0.15:
                score += 1
        except:
            pass
            
    # 3. Debt/Equity <= 0.5 (debtToEquity is in percentage in yfinance, so <= 50)
    de = info.get('debtToEquity')
    if de is not None:
        try:
            if float(de) <= 50.0:
                score += 1
        except:
            pass
    else:
        # None usually means no debt
        score += 1

    # 3Y Sales CAGR & 3Y Profit CAGR calculations
    sales_cagr = 0.0
    profit_cagr = 0.0
    has_financials = False
    
    if financials is not None and not financials.empty:
        try:
            if 'Total Revenue' in financials.index and len(financials.columns) >= 4:
                rev_latest = financials.loc['Total Revenue'].iloc[0]
                rev_3y = financials.loc['Total Revenue'].iloc[3]
                if rev_3y > 0:
                    sales_cagr = ((rev_latest / rev_3y) ** (1/3)) - 1
                    has_financials = True
            if 'Net Income' in financials.index and len(financials.columns) >= 4:
                prof_latest = financials.loc['Net Income'].iloc[0]
                prof_3y = financials.loc['Net Income'].iloc[3]
                if prof_3y > 0:
                    profit_cagr = ((prof_latest / prof_3y) ** (1/3)) - 1
                    has_financials = True
        except:
            pass

    # 4. 3Y Sales CAGR >= 10% (Fallback to latest revenue growth)
    if has_financials:
        if sales_cagr >= 0.10:
            score += 1
    else:
        rev_growth = info.get('revenueGrowth')
        if rev_growth is not None:
            try:
                if float(rev_growth) >= 0.10:
                    score += 1
            except:
                pass

    # 5. 3Y Profit CAGR >= 10% (Fallback to latest earnings growth)
    if has_financials:
        if profit_cagr >= 0.10:
            score += 1
    else:
        earn_growth = info.get('earningsGrowth')
        if earn_growth is not None:
            try:
                if float(earn_growth) >= 0.10:
                    score += 1
            except:
                pass

    # 6. Operating Cash Flow > 0
    ocf = info.get('operatingCashflow')
    if ocf is not None:
        try:
            if float(ocf) > 0:
                score += 1
        except:
            pass

    # 7. Operating Margin >= 15% (substitute for promoter pledge)
    op_margin = info.get('operatingMargins')
    if op_margin is not None:
        try:
            if float(op_margin) >= 0.15:
                score += 1
        except:
            pass

    return score

def fetch_and_save_fundamentals(symbol, ticker=None):
    try:
        import yfinance as yf
        if not ticker:
            ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info
        financials = ticker.financials
        score = calculate_fundamental_score(info, financials)
        db.update_fundamental_score(symbol, score)
        return score, info
    except Exception as e:
        log.warning(f"Failed to fetch/save fundamentals for {symbol}: {e}")
        return None, None

def backfill_missing_fundamental_scores():
    # Wait a brief moment to let the server start up
    time.sleep(5)
    log.info("Starting background backfill of missing fundamental scores...")
    try:
        prices = db.get_all_prices()
        for p in prices:
            symbol = p['symbol']
            if p.get('fundamental_score') is None:
                log.info(f"Backfilling fundamental score for {symbol}...")
                fetch_and_save_fundamentals(symbol)
                # Rate limit protection (2s between requests)
                time.sleep(2)
        log.info("Background fundamental score backfill complete.")
    except Exception as e:
        log.error(f"Error in backfill_missing_fundamental_scores background thread: {e}")

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
    'max_instances': 1
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
                
        for a in recent_alerts:
            if a.get('created_at'):
                dt = a['created_at']
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=utc)
                a['created_at'] = dt.astimezone(ist)
            
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
                except:
                    time_val = None
                    
                news.append({
                    'title': entry.get("title", ""),
                    'publisher': entry.get("source", {}).get("title", "News") if hasattr(entry, 'source') else "News",
                    'link': entry.get("link", ""),
                    'time': time_val
                })
        except Exception as e:
            log.warning(f"Failed to fetch Google News for {symbol}: {e}")
            
        try:
            info = ticker.info
            if info:
                fundamentals = {
                    'marketCap': info.get('marketCap'),
                    'peRatio': info.get('trailingPE'),
                    'pbRatio': info.get('priceToBook'),
                    'divYield': info.get('dividendYield', 0) * 100 if info.get('dividendYield') else None,
                    'high52': info.get('fiftyTwoWeekHigh'),
                    'low52': info.get('fiftyTwoWeekLow'),
                    'sector': info.get('sector'),
                    'industry': info.get('industry')
                }
                fundamental_score = calculate_fundamental_score(info)
                db.update_fundamental_score(symbol, fundamental_score)
        except Exception as e:
            log.warning(f"Failed to fetch news/fundamentals for {symbol}: {e}")

        return jsonify({
            'symbol': symbol,
            'price': stock_data['latest_price'],
            'change_pct': stock_data['change_pct'],
            'last_fetched': stock_data['last_fetched'].isoformat() if stock_data.get('last_fetched') else None,
            'alerts': alerts,
            'news': news,
            'fundamentals': fundamentals,
            'fundamental_score': fundamental_score
        })
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
        
        if symbol:
            # Check for duplicates
            watchlist = db.get_watchlist()
            if any(w['symbol'] == symbol for w in watchlist):
                flash(f"Error: {symbol} is already in the watchlist.", "error")
                return redirect(url_for('admin'))
                
            # Check if valid ticker
            try:
                import yfinance as yf
                ticker = yf.Ticker(symbol + ".NS")
                hist = ticker.history(period="1d")
                if hist.empty:
                    flash(f"Error: {symbol} is an invalid NSE ticker.", "error")
                    return redirect(url_for('admin'))
            except Exception as e:
                log.error(f"Error validating {symbol}: {e}")
                flash(f"Error: {symbol} could not be validated. Check again.", "error")
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
                    
            db.add_stock(symbol, bse_code)
            try:
                fetch_and_save_fundamentals(symbol, ticker)
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
