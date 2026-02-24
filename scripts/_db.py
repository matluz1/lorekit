"""Shared database utilities for LoreKit scripts."""

import os
import sqlite3
import sys

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    setting     TEXT    NOT NULL,
    system_type TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS session_meta (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    key         TEXT    NOT NULL,
    value       TEXT    NOT NULL,
    UNIQUE(session_id, key)
);

CREATE TABLE IF NOT EXISTS characters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    name        TEXT    NOT NULL,
    level       INTEGER NOT NULL DEFAULT 1,
    status      TEXT    NOT NULL DEFAULT 'alive',
    type        TEXT    NOT NULL DEFAULT 'pc',
    region_id   INTEGER REFERENCES regions(id),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS character_attributes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    category     TEXT    NOT NULL,
    key          TEXT    NOT NULL,
    value        TEXT    NOT NULL,
    UNIQUE(character_id, category, key)
);

CREATE TABLE IF NOT EXISTS character_inventory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    quantity     INTEGER NOT NULL DEFAULT 1,
    equipped     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS character_abilities (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    category     TEXT    NOT NULL,
    uses         TEXT    NOT NULL DEFAULT 'at_will'
);

CREATE TABLE IF NOT EXISTS regions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS journal (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    entry_type  TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS timeline (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    entry_type  TEXT    NOT NULL,
    speaker     TEXT    NOT NULL DEFAULT '',
    npc_id      INTEGER REFERENCES characters(id),
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

# Migration: add columns that may not exist on older databases
MIGRATIONS = [
    ("characters", "type", "ALTER TABLE characters ADD COLUMN type TEXT NOT NULL DEFAULT 'pc'"),
    ("characters", "region_id", "ALTER TABLE characters ADD COLUMN region_id INTEGER REFERENCES regions(id)"),
]


def resolve_db_path():
    """Resolve the database path from environment variables."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_dir = os.environ.get("LOREKIT_DB_DIR", os.path.join(script_dir, "..", "data"))
    return os.environ.get("LOREKIT_DB", os.path.join(db_dir, "game.db")), db_dir


def get_db(db_path=None):
    """Open a connection to the database."""
    if db_path is None:
        db_path, _ = resolve_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def require_db():
    """Return a connection to the database, or exit if it doesn't exist."""
    db_path, _ = resolve_db_path()
    if not os.path.isfile(db_path):
        error("Database not found. Run init_db.py first.")
    return get_db(db_path)


def init_schema(db_path=None):
    """Create all tables and run migrations."""
    if db_path is None:
        db_path, db_dir = resolve_db_path()
    else:
        db_dir = os.path.dirname(db_path)
    os.makedirs(db_dir, exist_ok=True)
    conn = get_db(db_path)
    conn.executescript(SCHEMA_SQL)
    # Run migrations
    for table, column, sql in MIGRATIONS:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(sql)
    conn.commit()
    conn.close()
    return db_path


def print_table(cursor):
    """Print query results in sqlite3 -header -column format."""
    description = cursor.description
    if description is None:
        return
    rows = cursor.fetchall()
    headers = [d[0] for d in description]
    if not rows and not headers:
        return
    # Convert all values to strings
    str_rows = []
    for row in rows:
        str_rows.append([str(v) if v is not None else "" for v in row])
    # Calculate column widths (minimum: header length, at least 1)
    widths = [len(h) for h in headers]
    for row in str_rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(val))
    # Ensure minimum width of 1
    widths = [max(w, 1) for w in widths]
    sep = "  "
    # Header line
    header_line = sep.join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    # Separator line (dashes)
    dash_line = sep.join("-" * w for w in widths)
    print(dash_line)
    # Data rows
    for row in str_rows:
        print(sep.join(val.ljust(w) for val, w in zip(row, widths)))


def error(msg):
    """Print an error message to stderr and exit with code 1."""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)
