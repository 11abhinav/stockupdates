import os
from db import init_db, add_stock
from bot import WATCHLIST, BSE_CODE_TO_NSE

def seed():
    print("Initializing DB...")
    init_db()
    
    # Reverse mapping for BSE codes
    nse_to_bse = {v: k for k, v in BSE_CODE_TO_NSE.items()}
    
    print(f"Adding {len(WATCHLIST)} stocks to DB...")
    for symbol in WATCHLIST:
        bse_code = nse_to_bse.get(symbol)
        add_stock(symbol, bse_code)
    
    print("Database seeded successfully.")

if __name__ == "__main__":
    seed()
