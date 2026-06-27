import os
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
import db
import bot

# Initialize logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

app = Flask(__name__)

# Initialize DB on startup
db.init_db()

# Setup APScheduler
scheduler = BackgroundScheduler()

# We run the background tasks every 10 minutes.
# bot.py natively checks if the market is open and skips execution if closed.
from datetime import datetime
scheduler.add_job(bot.run, 'interval', minutes=10, next_run_time=datetime.now())
scheduler.add_job(bot.check_bse_announcements, 'interval', minutes=10, next_run_time=datetime.now())

scheduler.start()

@app.route('/')
def index():
    try:
        prices = db.get_all_prices()
        recent_alerts = db.get_recent_alerts(200)
        
        alerts_by_symbol = set(a['symbol'] for a in recent_alerts)
        for p in prices:
            p['has_alert'] = p['symbol'] in alerts_by_symbol
            
        # Sort prices: those with alerts first, then alphabetically
        prices.sort(key=lambda x: (not x.get('has_alert', False), x['symbol']))
        
        return render_template('index.html', prices=prices)
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
        hist = ticker.history(period="1d")
        if not hist.empty:
            live_price = float(hist["Close"].iloc[-1])
            # Update DB with fresh price
            db.update_price(symbol, live_price)
            
        prices = db.get_all_prices()
        stock_data = next((p for p in prices if p['symbol'] == symbol), None)
        if not stock_data:
            return jsonify({'error': 'Stock not found'}), 404
            
        alerts = db.get_stock_alerts(symbol, limit=50)
        return jsonify({
            'symbol': symbol,
            'price': stock_data['latest_price'],
            'last_fetched': stock_data['last_fetched'].isoformat() if stock_data.get('last_fetched') else None,
            'alerts': alerts
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        symbol = request.form.get('symbol', '').strip().upper()
        bse_code = request.form.get('bse_code', '').strip()
        if symbol:
            success = db.add_stock(symbol, bse_code if bse_code else None)
            return redirect(url_for('admin', success=success))
            
    watchlist = db.get_watchlist()
    recent_alerts = db.get_recent_alerts(200)
    alerts_by_symbol = set(a['symbol'] for a in recent_alerts)
    for w in watchlist:
        w['has_alert'] = w['symbol'] in alerts_by_symbol
        
    return render_template('admin.html', watchlist=watchlist)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
