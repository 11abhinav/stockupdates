import os
from db import init_db, add_stock

WATCHLIST = [
    "ADANIENT", "ADANIGREEN", "ADANIPORTS", "AKZOINDIA", "ANANTRAJ",
    "ASIANPAINT", "ATGL", "BAJAJFINSV", "BEL", "BLS", "BLUEDART",
    "CASTROLIND", "CGPOWER", "CLEAN", "COALINDIA", "DBL", "EIDPARRY",
    "FILATEX", "FORTIS", "GILLETTE", "GSFC", "HDFCBANK", "HINDCOPPER",
    "HINDUNILVR", "ICICIBANK", "IDBI", "IFCI", "INDUSTOWER", "INFY",
    "IRB", "IRCTC", "JIOFIN", "JSWENERGY", "LATENTVIEW", "LLOYDSENGG",
    "LT", "MARUTI", "MAZDOCK", "NATCOPHARM", "ONGC", "ORIENTCEM",
    "PFC", "PIDILITIND", "POONAWALLA", "PVRINOX", "RELIANCE", "RVNL",
    "SBIN", "SUZLON", "SWIGGY", "SYMPHONY", "TATATECH", "TITAN", "TRENT",
]

BSE_CODE_TO_NSE = {
    "500410": "ADANIENT", "541450": "ADANIGREEN", "532921": "ADANIPORTS",
    "500710": "AKZOINDIA", "541523": "ANANTRAJ", "500820": "ASIANPAINT",
    "543529": "ATGL", "532978": "BAJAJFINSV", "500049": "BEL",
    "543579": "BLS", "526612": "BLUEDART", "500870": "CASTROLIND",
    "541137": "CGPOWER", "590061": "CLEAN", "533278": "COALINDIA",
    "534816": "DBL", "500116": "EIDPARRY", "526227": "FILATEX",
    "532779": "FORTIS", "507815": "GILLETTE", "500690": "GSFC",
    "500180": "HDFCBANK", "513599": "HINDCOPPER", "500696": "HINDUNILVR",
    "532174": "ICICIBANK", "500106": "IFCI", "534816": "INDUSTOWER",
    "500209": "INFY", "532947": "IRB", "542830": "IRCTC",
    "543940": "JIOFIN", "533148": "JSWENERGY", "540005": "LATENTVIEW",
    "539275": "LLOYDSENGG", "500510": "LT", "532500": "MARUTI",
    "543237": "MAZDOCK", "524816": "NATCOPHARM", "500312": "ONGC",
    "502165": "ORIENTCEM", "532810": "PFC", "500331": "PIDILITIND",
    "543277": "POONAWALLA", "532344": "PVRINOX", "500325": "RELIANCE",
    "542649": "RVNL", "500112": "SBIN", "532667": "SUZLON",
    "543288": "SWIGGY", "517385": "SYMPHONY", "544028": "TATATECH",
    "500114": "TITAN", "500251": "TRENT",
}

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
    
    print("Database seeded successfully.")

if __name__ == "__main__":
    seed()
