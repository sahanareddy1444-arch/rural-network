"""
database.py
Person A's data layer: SQLite schema + a couple of small connection helpers.

Kept intentionally boring for a 36-hour hackathon: no ORM, no migrations
framework, just sqlite3 + row_factory so query results come back as
dict-like Row objects that matching.py's dict-shaped inputs are happy with.
"""

import sqlite3
from contextlib import contextmanager

DB_PATH = "rhrn.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS hospitals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    contact_phone TEXT,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    credit_balance INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
    resource_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit TEXT,
    UNIQUE(hospital_id, resource_type)
);

CREATE TABLE IF NOT EXISTS capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
    facility_type TEXT NOT NULL,
    available_capacity INTEGER NOT NULL,
    UNIQUE(hospital_id, facility_type)
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requesting_hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
    resource_type TEXT NOT NULL,
    quantity_needed INTEGER NOT NULL,
    urgency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    fulfilling_hospital_id INTEGER REFERENCES hospitals(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT,
    patient_name TEXT NOT NULL,
    referring_hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
    required_facility TEXT NOT NULL,
    reason TEXT,
    urgency TEXT NOT NULL,
    preferred_radius_km REAL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    accepting_hospital_id INTEGER REFERENCES hospitals(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session():
    """Usage: with db_session() as db: db.execute(...)  — commits on success,
    rolls back on exception, always closes."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_session() as db:
        db.executescript(SCHEMA)


if __name__ == "__main__":
    init_db()
    print(f"Initialized schema in {DB_PATH}")
