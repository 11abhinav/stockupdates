import app
import db
import time

print("Fetching all symbols from DB...")
prices = db.get_all_prices()
symbols = [p['symbol'] for p in prices]

print(f"Force refreshing {len(symbols)} symbols...")
results, medians = app.refresh_universe(symbols)

print(f"Refreshed {len(results)} symbols.")
print("Sector Medians Calculated:")
for sector, med in medians.items():
    print(f" - {sector}: PE={med.get('median_pe')}, PB={med.get('median_pb')}, ROE={med.get('median_roe')}")

print("Done!")
