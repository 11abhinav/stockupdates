import app
import db
import time

print("Fetching all symbols from DB...")
prices = db.get_all_prices()
symbols = [p['symbol'] for p in prices]

print(f"Force refreshing {len(symbols)} symbols...")
results = app.refresh_watchlist_fundamentals(symbols)

print(f"Refreshed {len(results)} symbols.")

print("Done!")
