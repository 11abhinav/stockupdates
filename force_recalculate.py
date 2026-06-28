import os
import time
import app
import db
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("recalc")

def run_recalculation():
    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL environment variable is not set. Please set it before running this script.")
        return
        
    log.info("Fetching all symbols from DB...")
    prices = db.get_all_prices()
    symbols = [p['symbol'] for p in prices]
    
    if not symbols:
        log.warning("No symbols found in the database.")
        return
        
    log.info(f"Force recalculating {len(symbols)} symbols...")
    
    # Run the universe refresh
    results, medians = app.refresh_universe(symbols)
    
    log.info(f"Successfully recalculated {len(results)} symbols.")
    log.info("New Sector Medians:")
    for sector, med in medians.items():
        log.info(f"  {sector}: P/E={med.get('median_pe')}, P/B={med.get('median_pb')}, ROE={med.get('median_roe')}")
        
    log.info("Done! The database now contains the updated valuation and quality scores.")

if __name__ == "__main__":
    run_recalculation()
