"""
Scanner Health Registry - In-memory health tracking for all scanners.
Tracks status, errors, staleness, and provides data for admin dashboard.
"""
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
_lock = threading.Lock()

# Per-scanner health state
_registry = {}

def _now():
    return datetime.now(IST)

def _get_scanner(name):
    """Get or initialize a scanner health entry."""
    if name not in _registry:
        _registry[name] = {
            "status": "IDLE",            # UP, DOWN, DATA_STALE, IDLE
            "last_run": None,
            "last_success": None,
            "alerts_processed": 0,
            "stocks_scanned": 0,
            "stale_count": 0,
            "total_count": 0,
            "critical_error": None,
            "non_critical_errors": {},    # key -> {count, last_occurrence, symbol}
            "acknowledged_errors": set(),
            "data_source": None,         # "fyers" or "yahoo"
        }
    return _registry[name]


def begin_run(scanner_name):
    """Called at the start of a scanner run. Resets per-run counters."""
    with _lock:
        s = _get_scanner(scanner_name)
        s["last_run"] = _now()
        s["alerts_processed"] = 0
        s["stocks_scanned"] = 0
        s["stale_count"] = 0
        s["total_count"] = 0
        s["critical_error"] = None
        # Keep non-critical errors from previous runs (they accumulate until acknowledged)


def record_stock_scanned(scanner_name):
    """Called after successfully processing one stock."""
    with _lock:
        s = _get_scanner(scanner_name)
        s["stocks_scanned"] += 1
        s["total_count"] += 1


def record_stock_stale(scanner_name, symbol):
    """Called when data fetch returns None/empty for a stock."""
    with _lock:
        s = _get_scanner(scanner_name)
        s["stale_count"] += 1
        s["total_count"] += 1


def record_alert(scanner_name):
    """Called when an alert is emitted."""
    with _lock:
        s = _get_scanner(scanner_name)
        s["alerts_processed"] += 1


def record_stock_error(scanner_name, symbol, error_msg):
    """Record a non-critical per-stock error. Deduplicates by error message."""
    with _lock:
        s = _get_scanner(scanner_name)
        s["total_count"] += 1
        # Truncate error message for grouping
        key = str(error_msg)[:120]
        if key in s["acknowledged_errors"]:
            return  # Already acknowledged, don't re-add
        if key in s["non_critical_errors"]:
            s["non_critical_errors"][key]["count"] += 1
            s["non_critical_errors"][key]["last_occurrence"] = _now().isoformat()
            s["non_critical_errors"][key]["symbol"] = symbol  # Update to latest symbol
        else:
            s["non_critical_errors"][key] = {
                "count": 1,
                "last_occurrence": _now().isoformat(),
                "symbol": symbol,
            }


def record_critical_error(scanner_name, error_msg):
    """Record a critical error that brings the scanner DOWN."""
    with _lock:
        s = _get_scanner(scanner_name)
        s["status"] = "DOWN"
        s["critical_error"] = str(error_msg)[:300]


def finish_run(scanner_name):
    """Called at the end of a successful scanner run. Evaluates staleness."""
    with _lock:
        s = _get_scanner(scanner_name)
        if s["critical_error"]:
            # Already marked DOWN by a critical error
            return
        total = s["total_count"]
        stale = s["stale_count"]
        if total > 0 and (stale / total) > 0.30:
            s["status"] = "DATA_STALE"
            s["critical_error"] = f"Data stale for {stale}/{total} stocks ({stale/total*100:.0f}%). Check data source."
        else:
            s["status"] = "UP"
            s["last_success"] = _now()


def acknowledge_error(scanner_name, error_key):
    """Admin acknowledges and removes a non-critical error."""
    with _lock:
        s = _get_scanner(scanner_name)
        s["acknowledged_errors"].add(error_key)
        s["non_critical_errors"].pop(error_key, None)


def clear_all_errors(scanner_name):
    """Admin clears all non-critical errors."""
    with _lock:
        s = _get_scanner(scanner_name)
        keys = list(s["non_critical_errors"].keys())
        for k in keys:
            s["acknowledged_errors"].add(k)
        s["non_critical_errors"].clear()


def set_data_source(scanner_name, source):
    """Track which data source was used (fyers/yahoo)."""
    with _lock:
        s = _get_scanner(scanner_name)
        s["data_source"] = source


def get_status(scanner_name):
    """Return a JSON-serializable snapshot of scanner health."""
    with _lock:
        s = _get_scanner(scanner_name)
        return {
            "name": scanner_name,
            "status": s["status"],
            "last_run": s["last_run"].isoformat() if s["last_run"] else None,
            "last_success": s["last_success"].isoformat() if s["last_success"] else None,
            "alerts_processed": s["alerts_processed"],
            "stocks_scanned": s["stocks_scanned"],
            "stale_count": s["stale_count"],
            "total_count": s["total_count"],
            "critical_error": s["critical_error"],
            "non_critical_errors": [
                {"key": k, "message": k, "count": v["count"], "last_occurrence": v["last_occurrence"], "symbol": v["symbol"]}
                for k, v in s["non_critical_errors"].items()
            ],
            "data_source": s["data_source"],
        }


def get_all_status():
    """Return health status for all registered scanners."""
    # Ensure both scanners are always present
    with _lock:
        _get_scanner("MF")
        _get_scanner("MOMENTUM")
    return {
        "MF": get_status("MF"),
        "MOMENTUM": get_status("MOMENTUM"),
    }
