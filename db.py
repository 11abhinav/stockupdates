import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

log = logging.getLogger("momentum_bot.db")

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set.")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL:
        log.warning("DATABASE_URL not set. Skipping DB initialization.")
        return

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Create schema
                cur.execute("CREATE SCHEMA IF NOT EXISTS stockupdates;")
                
                # Create watchlist table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS stockupdates.watchlist (
                        symbol VARCHAR(50) PRIMARY KEY,
                        bse_code VARCHAR(20),
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # Create prices table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS stockupdates.prices (
                        symbol VARCHAR(50) PRIMARY KEY,
                        latest_price NUMERIC(10, 2),
                        last_fetched TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # Add change_pct column if it doesn't exist
                cur.execute("""
                    ALTER TABLE stockupdates.prices 
                    ADD COLUMN IF NOT EXISTS change_pct NUMERIC(10, 2);
                """)
                
                # Create alerts table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS stockupdates.alerts (
                        id SERIAL PRIMARY KEY,
                        symbol VARCHAR(50),
                        alert_type VARCHAR(50),
                        message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        entry_price NUMERIC(10, 2),
                        target_price NUMERIC(10, 2),
                        stop_loss NUMERIC(10, 2),
                        confidence NUMERIC(5, 2),
                        trigger_type VARCHAR(50),
                        tags JSONB
                    );
                """)
                
                # Add new columns to existing alerts table just in case it already exists
                alter_queries = [
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS entry_price NUMERIC(10, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS target_price NUMERIC(10, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS stop_loss NUMERIC(10, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS confidence NUMERIC(5, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS trigger_type VARCHAR(50);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS tags JSONB;"
                ]
                for query in alter_queries:
                    cur.execute(query)
                conn.commit()
                log.info("Database initialized successfully.")
    except Exception as e:
        log.error(f"Error initializing database: {e}")

def get_watchlist():
    if not DATABASE_URL:
        return []
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT symbol, bse_code FROM stockupdates.watchlist ORDER BY symbol;")
                return cur.fetchall()
    except Exception as e:
        log.error(f"Error fetching watchlist: {e}")
        return []

def add_stock(symbol, bse_code=None):
    if not DATABASE_URL:
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO stockupdates.watchlist (symbol, bse_code)
                    VALUES (%s, %s)
                    ON CONFLICT (symbol) DO UPDATE SET bse_code = EXCLUDED.bse_code;
                """, (symbol.upper(), bse_code))
                conn.commit()
                return True
    except Exception as e:
        log.error(f"Error adding stock {symbol}: {e}")
        return False

def update_price(symbol, price, change_pct=None):
    if not DATABASE_URL:
        return
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO stockupdates.prices (symbol, latest_price, change_pct, last_fetched)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (symbol) DO UPDATE 
                    SET latest_price = EXCLUDED.latest_price,
                        change_pct = COALESCE(EXCLUDED.change_pct, stockupdates.prices.change_pct),
                        last_fetched = CURRENT_TIMESTAMP;
                """, (symbol.upper(), price, change_pct))
                conn.commit()
    except Exception as e:
        log.error(f"Error updating price for {symbol}: {e}")

def get_all_prices():
    if not DATABASE_URL:
        return []
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT w.symbol, p.latest_price, p.change_pct, p.last_fetched 
                    FROM stockupdates.watchlist w
                    LEFT JOIN stockupdates.prices p ON w.symbol = p.symbol
                    ORDER BY w.symbol;
                """)
                return cur.fetchall()
    except Exception as e:
        log.error(f"Error fetching prices: {e}")
        return []

def save_alert(symbol, alert_type, message, entry_price=None, target_price=None, stop_loss=None, confidence=None, trigger_type=None, tags=None):
    if not DATABASE_URL:
        return
    try:
        import json
        tags_json = json.dumps(tags) if tags else None
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO stockupdates.alerts (
                        symbol, alert_type, message, created_at,
                        entry_price, target_price, stop_loss, confidence, trigger_type, tags
                    )
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s)
                """, (symbol.upper(), alert_type, message, entry_price, target_price, stop_loss, confidence, trigger_type, tags_json))
                conn.commit()
    except Exception as e:
        log.error(f"Error saving alert for {symbol}: {e}")

def get_recent_alerts(limit=50):
    if not DATABASE_URL:
        return []
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, symbol, alert_type, message, created_at,
                           entry_price, target_price, stop_loss, confidence, trigger_type, tags
                    FROM stockupdates.alerts
                    ORDER BY created_at DESC
                    LIMIT %s;
                """, (limit,))
                return cur.fetchall()
    except Exception as e:
        log.error(f"Error fetching alerts: {e}")
        return []

def get_stock_alerts(symbol, limit=50):
    if not DATABASE_URL:
        return []
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, symbol, alert_type, message, created_at,
                           entry_price, target_price, stop_loss, confidence, trigger_type, tags
                    FROM stockupdates.alerts 
                    WHERE symbol = %s
                    ORDER BY created_at DESC LIMIT %s;
                """, (symbol.upper(), limit))
                return cur.fetchall()
    except Exception as e:
        log.error(f"Error fetching stock alerts for {symbol}: {e}")
        return []

if __name__ == "__main__":
    init_db()
