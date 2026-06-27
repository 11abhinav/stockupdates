import logging
import feedparser
import requests
import traceback
from db import get_db_connection
from scanners.core import is_market_open, emit_alert, get_ist_now

log = logging.getLogger("scanners.news")

# Simple memory cache for alerts to avoid duplicate messages per day
_alerted = set()

from dateutil import parser
from datetime import datetime, timezone, timedelta

def is_recent(published_str, max_hours=6):
    """Check if the news/announcement is within max_hours"""
    if not published_str:
        return False
    try:
        pub_date = parser.parse(published_str)
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - pub_date) <= timedelta(hours=max_hours)
    except Exception as e:
        log.error(f"Date parse error: {e}")
        return False

def get_active_symbols():
    """Returns symbols that had an alert in the last 3 days"""
    try:
        with get_db_connection() as conn:
            if not conn: return []
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT symbol FROM stockupdates.watchlist
                """)
                return [row[0] for row in cur.fetchall()]
    except Exception as e:
        log.error(f"Error getting active symbols: {e}")
        return []

def run_news_scan():
    log.info("Running News Scanner for active symbols...")
    active_symbols = get_active_symbols()
    
    if not active_symbols:
        log.info("No active symbols to check news for.")
        return
        
    for symbol in active_symbols:
        try:
            url = f"https://news.google.com/rss/search?q={symbol}+NSE+stock"
            feed = feedparser.parse(url)
            
            if not feed.entries:
                continue
                
            entry = feed.entries[0]
            title = entry.get("title", "")
            link = entry.get("link", "")
            published = entry.get("published", "")
            
            if not is_recent(published, max_hours=6):
                continue
            
            alert_key = f"{symbol}_{title}"
            if alert_key in _alerted:
                continue
                
            emit_alert(
                symbol=symbol,
                scanner_name="NEWS",
                message=f"Recent catalyst news: {title}\nLink: {link}",
                tags={"type": "news"}
            )
            _alerted.add(alert_key)
            
        except Exception as e:
            log.error(f"Error checking news for {symbol}: {e}")

def run_bse_scan():
    log.info("Running BSE Scanner / News Scanner...")
    # Add BSE logic here. For brevity, using RSS fallback approach for all active symbols.
    run_news_scan() # Placeholder calling news scan for now, since it covers catalyst checks.

