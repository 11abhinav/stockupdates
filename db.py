import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

from psycopg2 import pool as pg_pool
from contextlib import contextmanager

log = logging.getLogger("momentum_bot.db")

DATABASE_URL = os.environ.get("DATABASE_URL")

_pool = None

def get_pool():
    global _pool
    if _pool is None and DATABASE_URL:
        _pool = pg_pool.ThreadedConnectionPool(1, 15, DATABASE_URL)
    return _pool

@contextmanager
def get_db_connection():
    pool = get_pool()
    if not pool:
        yield None
        return
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)

def init_db():
    if not DATABASE_URL:
        log.warning("DATABASE_URL not set. Skipping DB initialization.")
        return

    try:
        with get_db_connection() as conn:
            if not conn: return
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
                
                # Add fundamental_score column if it doesn't exist
                cur.execute("""
                    ALTER TABLE stockupdates.prices 
                    ADD COLUMN IF NOT EXISTS fundamental_score INTEGER;
                """)
                
                # Add quality_score and value_score columns if they don't exist
                cur.execute("""
                    ALTER TABLE stockupdates.prices 
                    ADD COLUMN IF NOT EXISTS quality_score NUMERIC(4, 1),
                    ADD COLUMN IF NOT EXISTS value_score NUMERIC(4, 1),
                    ADD COLUMN IF NOT EXISTS sector VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS pe NUMERIC(10, 2),
                    ADD COLUMN IF NOT EXISTS pb NUMERIC(10, 2),
                    ADD COLUMN IF NOT EXISTS roe NUMERIC(10, 4),
                    ADD COLUMN IF NOT EXISTS eps NUMERIC(10, 2),
                    ADD COLUMN IF NOT EXISTS bvps NUMERIC(10, 2),
                    ADD COLUMN IF NOT EXISTS div_yield NUMERIC(10, 4),
                    ADD COLUMN IF NOT EXISTS fair_value NUMERIC(10, 2),
                    ADD COLUMN IF NOT EXISTS valuation_label VARCHAR(50);
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
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS tags JSONB;",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS t1_price NUMERIC(10, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS t2_price NUMERIC(10, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS t3_price NUMERIC(10, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS risk_per_share NUMERIC(10, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS rr_to_t1 NUMERIC(5, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS rr_to_t2 NUMERIC(5, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS rr_to_t3 NUMERIC(5, 2);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS trail_mode VARCHAR(255);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS position_size_hint INTEGER;",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS setup_expiry_minutes INTEGER;",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS invalid BOOLEAN;",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS reason VARCHAR(255);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS status VARCHAR(50);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS highest_hit VARCHAR(50);",
                    "ALTER TABLE stockupdates.alerts ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;"
                ]
                for query in alter_queries:
                    cur.execute(query)
                
                # Add index
                cur.execute("CREATE INDEX IF NOT EXISTS idx_alerts_symbol_status ON stockupdates.alerts(symbol, status);")
                
                # Add check constraint for highest_hit safely
                cur.execute("""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint WHERE conname = 'chk_highest_hit'
                        ) THEN 
                            ALTER TABLE stockupdates.alerts ADD CONSTRAINT chk_highest_hit CHECK (highest_hit IN ('T1', 'T2', 'T3', 'SL', NULL));
                        END IF;
                    END $$;
                """)
                
                conn.commit()
                log.info("Database initialized successfully.")
    except Exception as e:
        log.error(f"Error initializing database: {e}")

def get_watchlist():
    if not DATABASE_URL:
        return []
    try:
        with get_db_connection() as conn:
            if not conn: return []
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT symbol, bse_code FROM stockupdates.watchlist ORDER BY symbol;")
                return cur.fetchall()
    except Exception as e:
        log.error(f"Error fetching watchlist: {e}")
        return []

def get_fundamental_scores(symbol):
    if not DATABASE_URL:
        return None, None
    try:
        with get_db_connection() as conn:
            if not conn: return None, None
            with conn.cursor() as cur:
                cur.execute("SELECT quality_score, value_score FROM stockupdates.prices WHERE symbol = %s;", (symbol.upper(),))
                row = cur.fetchone()
                if row:
                    return row[0], row[1]
    except Exception as e:
        log.error(f"Error fetching fundamental scores for {symbol}: {e}")
    return None, None

def get_valuation_details(symbol):
    if not DATABASE_URL:
        return None, None, None, None
    try:
        with get_db_connection() as conn:
            if not conn: return None, None, None, None
            with conn.cursor() as cur:
                cur.execute("SELECT quality_score, value_score, fair_value, valuation_label FROM stockupdates.prices WHERE symbol = %s;", (symbol.upper(),))
                row = cur.fetchone()
                if row:
                    return row[0], row[1], row[2], row[3]
    except Exception as e:
        log.error(f"Error fetching valuation details for {symbol}: {e}")
    return None, None, None, None

def add_stock(symbol, bse_code=None):
    if not DATABASE_URL:
        return False
    try:
        with get_db_connection() as conn:
            if not conn: return False
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

def remove_stock(symbol):
    if not DATABASE_URL:
        return False
    try:
        with get_db_connection() as conn:
            if not conn: return False
            with conn.cursor() as cur:
                # We also might want to remove it from prices table just in case,
                # but removing from watchlist is the primary goal.
                # Foreign keys are not strictly set to cascade, so let's delete from both
                cur.execute("DELETE FROM stockupdates.prices WHERE symbol = %s;", (symbol.upper(),))
                cur.execute("DELETE FROM stockupdates.watchlist WHERE symbol = %s;", (symbol.upper(),))
                conn.commit()
                return True
    except Exception as e:
        log.error(f"Error removing stock {symbol}: {e}")
        return False

def update_price(symbol, price, change_pct=None):
    if not DATABASE_URL:
        return
    try:
        with get_db_connection() as conn:
            if not conn: return
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
        with get_db_connection() as conn:
            if not conn: return []
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT w.symbol, w.bse_code, p.latest_price, p.change_pct, p.last_fetched, p.fundamental_score, p.quality_score, p.value_score
                    FROM stockupdates.watchlist w
                    LEFT JOIN stockupdates.prices p ON w.symbol = p.symbol
                    ORDER BY w.symbol;
                """)
                return cur.fetchall()
    except Exception as e:
        log.error(f"Error fetching prices: {e}")
        return []

def update_fundamental_score(symbol, score):
    if not DATABASE_URL:
        return
    try:
        with get_db_connection() as conn:
            if not conn: return
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO stockupdates.prices (symbol, fundamental_score, last_fetched)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (symbol) DO UPDATE 
                    SET fundamental_score = EXCLUDED.fundamental_score,
                        last_fetched = CURRENT_TIMESTAMP;
                """, (symbol.upper(), score))
                conn.commit()
    except Exception as e:
        log.error(f"Error updating fundamental score for {symbol}: {e}")

def update_fundamental_scores(symbol, quality_score, value_score):
    if not DATABASE_URL:
        return
    try:
        with get_db_connection() as conn:
            if not conn: return
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO stockupdates.prices (symbol, quality_score, value_score, last_fetched)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (symbol) DO UPDATE 
                    SET quality_score = EXCLUDED.quality_score,
                        value_score = EXCLUDED.value_score,
                        last_fetched = CURRENT_TIMESTAMP;
                """, (symbol.upper(), quality_score, value_score))
                conn.commit()
    except Exception as e:
        log.error(f"Error updating fundamental scores for {symbol}: {e}")

def update_fundamental_metrics(symbol, sector, pe, pb, roe, eps, bvps, div_yield):
    if not DATABASE_URL:
        return
    try:
        with get_db_connection() as conn:
            if not conn: return
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO stockupdates.prices (
                        symbol, sector, pe, pb, roe, eps, bvps, div_yield, last_fetched
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (symbol) DO UPDATE 
                    SET sector = EXCLUDED.sector,
                        pe = EXCLUDED.pe,
                        pb = EXCLUDED.pb,
                        roe = EXCLUDED.roe,
                        eps = EXCLUDED.eps,
                        bvps = EXCLUDED.bvps,
                        div_yield = EXCLUDED.div_yield,
                        last_fetched = CURRENT_TIMESTAMP;
                """, (symbol.upper(), sector, pe, pb, roe, eps, bvps, div_yield))
                conn.commit()
    except Exception as e:
        log.error(f"Error updating fundamental metrics for {symbol}: {e}")

def update_valuation_fields(symbol, value_score, fair_value, valuation_label):
    if not DATABASE_URL:
        return
    try:
        with get_db_connection() as conn:
            if not conn: return
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO stockupdates.prices (
                        symbol, value_score, fair_value, valuation_label, last_fetched
                    ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (symbol) DO UPDATE 
                    SET value_score = EXCLUDED.value_score,
                        fair_value = EXCLUDED.fair_value,
                        valuation_label = EXCLUDED.valuation_label,
                        last_fetched = CURRENT_TIMESTAMP;
                """, (symbol.upper(), value_score, fair_value, valuation_label))
                conn.commit()
    except Exception as e:
        log.error(f"Error updating valuation fields for {symbol}: {e}")

def get_all_fundamentals():
    if not DATABASE_URL:
        return []
    try:
        with get_db_connection() as conn:
            if not conn: return []
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT symbol, sector, pe, pb, roe, eps, bvps, div_yield
                    FROM stockupdates.prices;
                """)
                return cur.fetchall()
    except Exception as e:
        log.error(f"Error fetching fundamentals: {e}")
        return []


def save_alert(symbol, alert_type, message, entry_price=None, target_price=None, stop_loss=None, 
               confidence=None, trigger_type=None, tags=None,
               t1_price=None, t2_price=None, t3_price=None, risk_per_share=None,
               rr_to_t1=None, rr_to_t2=None, rr_to_t3=None, trail_mode=None,
               position_size_hint=None, setup_expiry_minutes=None, invalid=None, reason=None):
    if not DATABASE_URL:
        return
    import json
    try:
        with get_db_connection() as conn:
            if not conn: return
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO stockupdates.alerts (
                        symbol, alert_type, message, entry_price, target_price, stop_loss, confidence, trigger_type, tags,
                        t1_price, t2_price, t3_price, risk_per_share, rr_to_t1, rr_to_t2, rr_to_t3, trail_mode, 
                        position_size_hint, setup_expiry_minutes, invalid, reason, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    symbol.upper(), alert_type, message, entry_price, target_price, stop_loss, confidence, trigger_type, 
                    json.dumps(tags) if tags else None,
                    t1_price, t2_price, t3_price, risk_per_share, rr_to_t1, rr_to_t2, rr_to_t3, trail_mode,
                    position_size_hint, setup_expiry_minutes, invalid, reason, 
                    'OPEN' if entry_price else 'INFO'
                ))
                conn.commit()
    except Exception as e:
        log.error(f"Error saving alert for {symbol}: {e}")

def get_open_alerts():
    """Fetch all alerts with status 'OPEN'."""
    if not DATABASE_URL:
        return []
    try:
        with get_db_connection() as conn:
            if not conn: return []
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, symbol, alert_type, message, created_at, 
                           entry_price, stop_loss, target_price, t1_price, t2_price, t3_price,
                           highest_hit
                    FROM stockupdates.alerts 
                    WHERE status = 'OPEN'
                """)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception as e:
        log.error(f"Error fetching open alerts: {e}")
        return []

def update_alert_status(alert_id, new_status, highest_hit=None):
    if not DATABASE_URL:
        return
    try:
        with get_db_connection() as conn:
            if not conn: return
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE stockupdates.alerts
                    SET status = %s, highest_hit = COALESCE(%s, highest_hit), 
                        resolved_at = CASE WHEN %s IN ('SL_HIT', 'T3_HIT', 'CLOSED_WIN', 'CLOSED_LOSS', 'EXPIRED') THEN CURRENT_TIMESTAMP ELSE resolved_at END
                    WHERE id = %s
                """, (new_status, highest_hit, new_status, alert_id))
                conn.commit()
    except Exception as e:
        log.error(f"Error updating alert {alert_id}: {e}")

def get_recent_alerts(limit=50):
    if not DATABASE_URL:
        return []
    try:
        with get_db_connection() as conn:
            if not conn: return []
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, symbol, alert_type, message, created_at,
                           entry_price, target_price, stop_loss, confidence, trigger_type, tags,
                           t1_price, t2_price, t3_price, risk_per_share, rr_to_t1, rr_to_t2, trail_mode, position_size_hint,
                           status, highest_hit
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
        with get_db_connection() as conn:
            if not conn: return []
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, symbol, alert_type, message, created_at,
                           entry_price, target_price, stop_loss, confidence, trigger_type, tags,
                           t1_price, t2_price, t3_price, risk_per_share, rr_to_t1, rr_to_t2, trail_mode, position_size_hint,
                           status, highest_hit
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
