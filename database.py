import sqlite3
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

DB_PATH = "cloudguard.db"

def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str = DB_PATH) -> None:
    """Initialize database tables for monitoring events, metrics, and system state."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS system_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                healthy INTEGER NOT NULL,
                failure_reason TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            INSERT OR IGNORE INTO system_state (id, healthy, failure_reason, updated_at)
            VALUES (1, 1, NULL, ?)
            """,
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),)
        )
        conn.commit()

def set_service_state(healthy: bool, failure_reason: Optional[str] = None, db_path: str = DB_PATH) -> None:
    """Persist system state to SQLite so all processes share exact ground truth."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO system_state (id, healthy, failure_reason, updated_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                healthy = excluded.healthy,
                failure_reason = excluded.failure_reason,
                updated_at = excluded.updated_at
            """,
            (1 if healthy else 0, failure_reason, now)
        )
        conn.commit()

def get_service_state(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Retrieve shared system state from SQLite."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT healthy, failure_reason, updated_at FROM system_state WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return {
                "healthy": bool(row["healthy"]),
                "failure_reason": row["failure_reason"],
                "updated_at": row["updated_at"]
            }
        return {"healthy": True, "failure_reason": None, "updated_at": ""}

def log_event(event_type: str, status: str, details: str = "", db_path: str = DB_PATH) -> int:
    """Log a monitoring or recovery event to SQLite."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO events (timestamp, event_type, status, details)
            VALUES (?, ?, ?, ?)
            """,
            (now, event_type, status, details),
        )
        conn.commit()
        return cursor.lastrowid

def get_recent_events(limit: int = 15, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve recent monitoring and recovery events."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, timestamp, event_type, status, details
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_event_counts(db_path: str = DB_PATH) -> Dict[str, int]:
    """Calculate summary counts for dashboard."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'FAILURE'")
        total_failures = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'RECOVERY' AND status = 'SUCCESS'")
        successful_recoveries = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'HEALTH_CHECK'")
        total_checks = cursor.fetchone()[0]

        return {
            "total_failures": total_failures,
            "successful_recoveries": successful_recoveries,
            "total_checks": total_checks,
        }
