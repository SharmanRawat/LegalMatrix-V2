import sqlite3
from pathlib import Path

from app.config import get_database_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('ADMIN', 'INSPECTOR', 'VIEWER')),
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inspections (
    id               TEXT PRIMARY KEY,
    product_name     TEXT,
    manufacturer     TEXT,
    status           TEXT NOT NULL,
    compliance_score REAL NOT NULL DEFAULT 0,
    passed_count     INTEGER NOT NULL DEFAULT 0,
    total_rules      INTEGER NOT NULL DEFAULT 0,
    declarations_json TEXT NOT NULL DEFAULT '{}',
    missing_json     TEXT NOT NULL DEFAULT '[]',
    violations_json  TEXT NOT NULL DEFAULT '[]',
    misleading_json  TEXT NOT NULL DEFAULT '[]',
    meta_json         TEXT NOT NULL DEFAULT '{}',
    evidence_hash    TEXT NOT NULL DEFAULT '',
    images_count     INTEGER NOT NULL DEFAULT 0,
    model            TEXT NOT NULL DEFAULT '',
    user_id          INTEGER,
    created_at       TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS inspection_images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id TEXT NOT NULL,
    filename      TEXT NOT NULL,
    original_name TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (inspection_id) REFERENCES inspections(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inspections_created_at ON inspections(created_at);
CREATE INDEX IF NOT EXISTS idx_inspections_status ON inspections(status);
CREATE INDEX IF NOT EXISTS idx_inspections_product_name ON inspections(product_name);
CREATE INDEX IF NOT EXISTS idx_inspections_manufacturer ON inspections(manufacturer);
CREATE INDEX IF NOT EXISTS idx_images_inspection ON inspection_images(inspection_id);
"""


def get_connection(db_path=None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns added after the initial schema (idempotent)."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(inspections)")}
    if "misleading_json" not in cols:
        conn.execute(
            "ALTER TABLE inspections ADD COLUMN misleading_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "meta_json" not in cols:
        conn.execute(
            "ALTER TABLE inspections ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}'"
        )


def init_db(db_path=None) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()