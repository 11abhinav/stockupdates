from flask import Flask, render_template
from psycopg2.extras import RealDictRow

app = Flask(__name__, template_folder='templates')

@app.route('/')
def index():
    # simulate db.get_all_prices() after seeding
    r = RealDictRow(cursor=None)
    r['symbol'] = 'RELIANCE'
    r['latest_price'] = None
    r['last_fetched'] = None
    prices = [r]
    
    alerts_by_symbol = {}
    
    prices.sort(key=lambda x: (x['symbol'] not in alerts_by_symbol, x['symbol']))
    
    with app.app_context():
        return render_template('index.html', prices=prices, alerts=alerts_by_symbol)

if __name__ == '__main__':
    with app.test_client() as c:
        resp = c.get('/')
        print("Status:", resp.status_code)
        if resp.status_code != 200:
            print(resp.text)
