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

# Add jobs matching the cron schedules from bot.py
# Market open 09:20 IST -> 03:50 UTC
scheduler.add_job(bot.run, 'cron', day_of_week='mon-fri', hour=3, minute=50)
# Mid-session 12:00 IST -> 06:30 UTC
scheduler.add_job(bot.run, 'cron', day_of_week='mon-fri', hour=6, minute=30)
# Market close 15:35 IST -> 10:05 UTC
scheduler.add_job(bot.run, 'cron', day_of_week='mon-fri', hour=10, minute=5)
# BSE only every 30 min during market hours (03:30 to 10:00 UTC)
scheduler.add_job(bot.check_bse_announcements, 'cron', day_of_week='mon-fri', hour='3-10', minute='*/30')

scheduler.start()

@app.route('/')
def index():
    try:
        prices = db.get_all_prices()
        recent_alerts = db.get_recent_alerts(100)
        
        alerts_by_symbol = {}
        for a in recent_alerts:
            sym = a['symbol']
            if sym not in alerts_by_symbol:
                alerts_by_symbol[sym] = []
            alerts_by_symbol[sym].append(a)
        
        # Sort prices: those with alerts first, then alphabetically
        prices.sort(key=lambda x: (x['symbol'] not in alerts_by_symbol, x['symbol']))
        
        return render_template('index.html', prices=prices, alerts=alerts_by_symbol)
    except Exception as e:
        import traceback
        return f"<h1>Error Occurred</h1><pre>{traceback.format_exc()}</pre>", 200

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        symbol = request.form.get('symbol', '').strip().upper()
        bse_code = request.form.get('bse_code', '').strip()
        if symbol:
            success = db.add_stock(symbol, bse_code if bse_code else None)
            return redirect(url_for('admin', success=success))
            
    watchlist = db.get_watchlist()
    return render_template('admin.html', watchlist=watchlist)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
