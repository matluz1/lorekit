"""Shared database utilities for LoreKit core modules."""

import os
import sqlite3

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
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    key         TEXT    NOT NULL,
    value       TEXT    NOT NULL,
    UNIQUE(session_id, key)
);

CREATE TABLE IF NOT EXISTS characters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    gender      TEXT    NOT NULL DEFAULT '',
    level       INTEGER NOT NULL DEFAULT 1,
    status      TEXT    NOT NULL DEFAULT 'alive',
    type        TEXT    NOT NULL DEFAULT 'pc',
    prefetch    INTEGER NOT NULL DEFAULT 0,
    region_id   INTEGER REFERENCES regions(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS character_attributes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    category     TEXT    NOT NULL,
    key          TEXT    NOT NULL,
    value        TEXT    NOT NULL,
    UNIQUE(character_id, category, key)
);

CREATE TABLE IF NOT EXISTS character_inventory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    quantity     INTEGER NOT NULL DEFAULT 1,
    equipped     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(character_id, name)
);

CREATE TABLE IF NOT EXISTS character_abilities (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    category     TEXT    NOT NULL,
    uses         TEXT    NOT NULL DEFAULT 'at_will',
    cost         REAL    NOT NULL DEFAULT 0,
    UNIQUE(character_id, name)
);

CREATE TABLE IF NOT EXISTS regions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    parent_id   INTEGER REFERENCES regions(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS journal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    entry_type      TEXT    NOT NULL,
    content         TEXT    NOT NULL,
    narrative_time  TEXT    NOT NULL DEFAULT '',
    scope           TEXT    NOT NULL DEFAULT 'participants',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS timeline (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    entry_type      TEXT    NOT NULL,
    content         TEXT    NOT NULL,
    summary         TEXT    NOT NULL DEFAULT '',
    narrative_time  TEXT    NOT NULL DEFAULT '',
    scope           TEXT    NOT NULL DEFAULT 'participants',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS stories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    adventure_size TEXT NOT NULL,
    premise     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(session_id)
);

CREATE TABLE IF NOT EXISTS story_acts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    act_order   INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    goal        TEXT    NOT NULL DEFAULT '',
    event       TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'pending',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(session_id, act_order)
);

CREATE TABLE IF NOT EXISTS combat_state (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id   INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    source         TEXT    NOT NULL,
    target_stat    TEXT    NOT NULL,
    modifier_type  TEXT    NOT NULL,
    value          INTEGER NOT NULL,
    bonus_type     TEXT,
    duration_type  TEXT    NOT NULL DEFAULT 'encounter',
    duration       INTEGER,
    save_stat      TEXT,
    save_dc        INTEGER,
    applied_by     INTEGER REFERENCES characters(id),
    metadata       TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(character_id, source, target_stat)
);

CREATE TABLE IF NOT EXISTS encounter_state (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    status           TEXT    NOT NULL DEFAULT 'active',
    round            INTEGER NOT NULL DEFAULT 1,
    initiative_order TEXT    NOT NULL DEFAULT '[]',
    current_turn     INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS encounter_zones (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id INTEGER NOT NULL REFERENCES encounter_state(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    tags         TEXT    NOT NULL DEFAULT '[]',
    UNIQUE(encounter_id, name)
);

CREATE TABLE IF NOT EXISTS zone_adjacency (
    zone_a INTEGER NOT NULL REFERENCES encounter_zones(id) ON DELETE CASCADE,
    zone_b INTEGER NOT NULL REFERENCES encounter_zones(id) ON DELETE CASCADE,
    weight INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (zone_a, zone_b)
);

CREATE TABLE IF NOT EXISTS character_zone (
    encounter_id INTEGER NOT NULL REFERENCES encounter_state(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    zone_id      INTEGER NOT NULL REFERENCES encounter_zones(id) ON DELETE CASCADE,
    team         TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (encounter_id, character_id)
);

CREATE TABLE IF NOT EXISTS embeddings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    source_id   INTEGER NOT NULL,
    session_id  INTEGER NOT NULL,
    npc_id      INTEGER,
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timeline_max_id INTEGER NOT NULL DEFAULT 0,
    journal_max_id  INTEGER NOT NULL DEFAULT 0,
    snapshot        TEXT    NOT NULL,
    kind            TEXT    NOT NULL DEFAULT 'auto',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS npc_memories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    npc_id          INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    importance      REAL NOT NULL DEFAULT 0.5,
    memory_type     TEXT NOT NULL,
    entities        TEXT,
    narrative_time  TEXT NOT NULL,
    access_count    INTEGER NOT NULL DEFAULT 0,
    last_accessed   TEXT,
    source_ids      TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS character_aliases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    alias        TEXT NOT NULL,
    UNIQUE(character_id, alias)
);

CREATE TABLE IF NOT EXISTS entry_entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    source_id   INTEGER NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    UNIQUE(source, source_id, entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS npc_core (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    npc_id          INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    self_concept    TEXT,
    current_goals   TEXT,
    emotional_state TEXT,
    relationships   TEXT,
    behavioral_patterns TEXT,
    updated_at      TEXT,
    UNIQUE(session_id, npc_id)
);

"""

INDEXES_SQL = """\
CREATE INDEX IF NOT EXISTS idx_timeline_session ON timeline(session_id, entry_type);
CREATE INDEX IF NOT EXISTS idx_journal_session ON journal(session_id, entry_type);
CREATE INDEX IF NOT EXISTS idx_characters_session ON characters(session_id, type);
CREATE INDEX IF NOT EXISTS idx_char_attrs ON character_attributes(character_id);
CREATE INDEX IF NOT EXISTS idx_char_inventory ON character_inventory(character_id);
CREATE INDEX IF NOT EXISTS idx_char_abilities ON character_abilities(character_id);
CREATE INDEX IF NOT EXISTS idx_session_meta ON session_meta(session_id);
CREATE INDEX IF NOT EXISTS idx_story_acts_session ON story_acts(session_id, act_order);
CREATE INDEX IF NOT EXISTS idx_regions_session ON regions(session_id);
CREATE INDEX IF NOT EXISTS idx_combat_state ON combat_state(character_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_session ON embeddings(session_id, source);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_encounter_state_session ON encounter_state(session_id);
CREATE INDEX IF NOT EXISTS idx_encounter_zones ON encounter_zones(encounter_id);
CREATE INDEX IF NOT EXISTS idx_character_zone ON character_zone(encounter_id);
CREATE INDEX IF NOT EXISTS idx_npc_memories_npc ON npc_memories(npc_id, session_id);
CREATE INDEX IF NOT EXISTS idx_npc_memories_importance ON npc_memories(importance);
CREATE INDEX IF NOT EXISTS idx_npc_core_npc ON npc_core(session_id, npc_id);
CREATE INDEX IF NOT EXISTS idx_character_aliases ON character_aliases(character_id);
CREATE INDEX IF NOT EXISTS idx_entry_entities_entity ON entry_entities(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_entry_entities_source ON entry_entities(source, source_id);
"""

# Migrations: add or drop columns on older databases
ADD_COLUMN_MIGRATIONS = [
    ("characters", "type", "ALTER TABLE characters ADD COLUMN type TEXT NOT NULL DEFAULT 'pc'"),
    ("characters", "region_id", "ALTER TABLE characters ADD COLUMN region_id INTEGER REFERENCES regions(id)"),
    ("timeline", "summary", "ALTER TABLE timeline ADD COLUMN summary TEXT NOT NULL DEFAULT ''"),
    ("regions", "parent_id", "ALTER TABLE regions ADD COLUMN parent_id INTEGER REFERENCES regions(id)"),
    ("timeline", "narrative_time", "ALTER TABLE timeline ADD COLUMN narrative_time TEXT NOT NULL DEFAULT ''"),
    ("journal", "narrative_time", "ALTER TABLE journal ADD COLUMN narrative_time TEXT NOT NULL DEFAULT ''"),
    ("combat_state", "save_stat", "ALTER TABLE combat_state ADD COLUMN save_stat TEXT"),
    ("combat_state", "save_dc", "ALTER TABLE combat_state ADD COLUMN save_dc INTEGER"),
    ("character_zone", "team", "ALTER TABLE character_zone ADD COLUMN team TEXT NOT NULL DEFAULT ''"),
    ("character_abilities", "cost", "ALTER TABLE character_abilities ADD COLUMN cost REAL NOT NULL DEFAULT 0"),
    ("characters", "gender", "ALTER TABLE characters ADD COLUMN gender TEXT NOT NULL DEFAULT ''"),
    ("combat_state", "applied_by", "ALTER TABLE combat_state ADD COLUMN applied_by INTEGER REFERENCES characters(id)"),
    ("combat_state", "metadata", "ALTER TABLE combat_state ADD COLUMN metadata TEXT"),
    ("timeline", "scope", "ALTER TABLE timeline ADD COLUMN scope TEXT NOT NULL DEFAULT 'participants'"),
    ("journal", "scope", "ALTER TABLE journal ADD COLUMN scope TEXT NOT NULL DEFAULT 'participants'"),
    ("checkpoints", "kind", "ALTER TABLE checkpoints ADD COLUMN kind TEXT NOT NULL DEFAULT 'auto'"),
    ("characters", "prefetch", "ALTER TABLE characters ADD COLUMN prefetch INTEGER NOT NULL DEFAULT 0"),
]

DROP_COLUMN_MIGRATIONS = [
    ("timeline", "speaker", "ALTER TABLE timeline DROP COLUMN speaker"),
    ("timeline", "npc_id", "ALTER TABLE timeline DROP COLUMN npc_id"),
]


class LoreKitError(Exception):
    """Raised when a command encounters an expected error condition."""

    pass


def resolve_db_path():
    """Resolve the database path from environment variables."""
    from lorekit.rules import project_root

    db_dir = os.environ.get("LOREKIT_DB_DIR", os.path.join(project_root(), "data"))
    return os.environ.get("LOREKIT_DB", os.path.join(db_dir, "game.db")), db_dir


def get_db(db_path=None):
    """Open a connection to the database."""
    if db_path is None:
        db_path, _ = resolve_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except ImportError:
        pass
    return conn


_migrated_dbs: set[str] = set()


def require_db():
    """Return a connection to the database, auto-creating and migrating if needed."""
    db_path, _ = resolve_db_path()
    if not os.path.isfile(db_path):
        init_schema(db_path)
    elif db_path not in _migrated_dbs:
        _run_migrations(db_path)
        _migrated_dbs.add(db_path)
    return get_db(db_path)


def _migrate_table_with_cascade(conn, table, new_ddl, columns):
    """Recreate a table with new DDL, preserving data.

    Used to add ON DELETE CASCADE / UNIQUE constraints to existing tables
    (SQLite doesn't support ALTER FOREIGN KEY or ALTER ADD CONSTRAINT).
    """
    col_list = ", ".join(columns)
    conn.execute(f"CREATE TABLE IF NOT EXISTS __{table}_backup AS SELECT {col_list} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(new_ddl)
    conn.execute(f"INSERT OR IGNORE INTO {table} ({col_list}) SELECT {col_list} FROM __{table}_backup")
    conn.execute(f"DROP TABLE __{table}_backup")


# Tables that need recreation for CASCADE + UNIQUE constraints.
# Map of table -> (new CREATE DDL, list of columns to preserve).
_CASCADE_MIGRATIONS = {
    "session_meta": (
        """CREATE TABLE session_meta (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            key         TEXT    NOT NULL,
            value       TEXT    NOT NULL,
            UNIQUE(session_id, key)
        )""",
        ["id", "session_id", "key", "value"],
    ),
    "characters": (
        """CREATE TABLE characters (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            name        TEXT    NOT NULL,
            gender      TEXT    NOT NULL DEFAULT '',
            level       INTEGER NOT NULL DEFAULT 1,
            status      TEXT    NOT NULL DEFAULT 'alive',
            type        TEXT    NOT NULL DEFAULT 'pc',
            region_id   INTEGER REFERENCES regions(id) ON DELETE SET NULL,
            created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )""",
        ["id", "session_id", "name", "gender", "level", "status", "type", "region_id", "created_at"],
    ),
    "character_attributes": (
        """CREATE TABLE character_attributes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            category     TEXT    NOT NULL,
            key          TEXT    NOT NULL,
            value        TEXT    NOT NULL,
            UNIQUE(character_id, category, key)
        )""",
        ["id", "character_id", "category", "key", "value"],
    ),
    "character_inventory": (
        """CREATE TABLE character_inventory (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            name         TEXT    NOT NULL,
            description  TEXT    NOT NULL DEFAULT '',
            quantity     INTEGER NOT NULL DEFAULT 1,
            equipped     INTEGER NOT NULL DEFAULT 0,
            UNIQUE(character_id, name)
        )""",
        ["id", "character_id", "name", "description", "quantity", "equipped"],
    ),
    "character_abilities": (
        """CREATE TABLE character_abilities (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            name         TEXT    NOT NULL,
            description  TEXT    NOT NULL DEFAULT '',
            category     TEXT    NOT NULL,
            uses         TEXT    NOT NULL DEFAULT 'at_will',
            cost         REAL    NOT NULL DEFAULT 0,
            UNIQUE(character_id, name)
        )""",
        ["id", "character_id", "name", "description", "category", "uses", "cost"],
    ),
    "regions": (
        """CREATE TABLE regions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            parent_id   INTEGER REFERENCES regions(id) ON DELETE SET NULL,
            created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )""",
        ["id", "session_id", "name", "description", "parent_id", "created_at"],
    ),
    "journal": (
        """CREATE TABLE journal (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            entry_type      TEXT    NOT NULL,
            content         TEXT    NOT NULL,
            narrative_time  TEXT    NOT NULL DEFAULT '',
            scope           TEXT    NOT NULL DEFAULT 'participants',
            created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )""",
        ["id", "session_id", "entry_type", "content", "narrative_time", "scope", "created_at"],
    ),
    "timeline": (
        """CREATE TABLE timeline (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            entry_type      TEXT    NOT NULL,
            content         TEXT    NOT NULL,
            summary         TEXT    NOT NULL DEFAULT '',
            narrative_time  TEXT    NOT NULL DEFAULT '',
            scope           TEXT    NOT NULL DEFAULT 'participants',
            created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )""",
        ["id", "session_id", "entry_type", "content", "summary", "narrative_time", "scope", "created_at"],
    ),
    "stories": (
        """CREATE TABLE stories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            adventure_size TEXT NOT NULL,
            premise     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(session_id)
        )""",
        ["id", "session_id", "adventure_size", "premise", "created_at"],
    ),
    "story_acts": (
        """CREATE TABLE story_acts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            act_order   INTEGER NOT NULL,
            title       TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            goal        TEXT    NOT NULL DEFAULT '',
            event       TEXT    NOT NULL DEFAULT '',
            status      TEXT    NOT NULL DEFAULT 'pending',
            created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(session_id, act_order)
        )""",
        ["id", "session_id", "act_order", "title", "description", "goal", "event", "status", "created_at"],
    ),
    "encounter_state": (
        """CREATE TABLE encounter_state (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id       INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            status           TEXT    NOT NULL DEFAULT 'active',
            round            INTEGER NOT NULL DEFAULT 1,
            initiative_order TEXT    NOT NULL DEFAULT '[]',
            current_turn     INTEGER NOT NULL DEFAULT 0,
            created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )""",
        ["id", "session_id", "status", "round", "initiative_order", "current_turn", "created_at"],
    ),
    "encounter_zones": (
        """CREATE TABLE encounter_zones (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            encounter_id INTEGER NOT NULL REFERENCES encounter_state(id) ON DELETE CASCADE,
            name         TEXT    NOT NULL,
            tags         TEXT    NOT NULL DEFAULT '[]',
            UNIQUE(encounter_id, name)
        )""",
        ["id", "encounter_id", "name", "tags"],
    ),
    "zone_adjacency": (
        """CREATE TABLE zone_adjacency (
            zone_a INTEGER NOT NULL REFERENCES encounter_zones(id) ON DELETE CASCADE,
            zone_b INTEGER NOT NULL REFERENCES encounter_zones(id) ON DELETE CASCADE,
            weight INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (zone_a, zone_b)
        )""",
        ["zone_a", "zone_b", "weight"],
    ),
    "character_zone": (
        """CREATE TABLE character_zone (
            encounter_id INTEGER NOT NULL REFERENCES encounter_state(id) ON DELETE CASCADE,
            character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            zone_id      INTEGER NOT NULL REFERENCES encounter_zones(id) ON DELETE CASCADE,
            team         TEXT    NOT NULL DEFAULT '',
            PRIMARY KEY (encounter_id, character_id)
        )""",
        ["encounter_id", "character_id", "zone_id", "team"],
    ),
    "combat_state": (
        """CREATE TABLE combat_state (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id   INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            source         TEXT    NOT NULL,
            target_stat    TEXT    NOT NULL,
            modifier_type  TEXT    NOT NULL,
            value          INTEGER NOT NULL,
            bonus_type     TEXT,
            duration_type  TEXT    NOT NULL DEFAULT 'encounter',
            duration       INTEGER,
            save_stat      TEXT,
            save_dc        INTEGER,
            applied_by     INTEGER REFERENCES characters(id),
            metadata       TEXT,
            created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(character_id, source, target_stat)
        )""",
        [
            "id",
            "character_id",
            "source",
            "target_stat",
            "modifier_type",
            "value",
            "bonus_type",
            "duration_type",
            "duration",
            "save_stat",
            "save_dc",
            "applied_by",
            "metadata",
            "created_at",
        ],
    ),
}

# Order matters: tables with no FK deps first, then dependents.
_CASCADE_MIGRATION_ORDER = [
    "session_meta",
    "regions",
    "journal",
    "timeline",
    "stories",
    "story_acts",
    "characters",
    "character_attributes",
    "character_inventory",
    "character_abilities",
    "combat_state",
    "encounter_state",
    "encounter_zones",
    "zone_adjacency",
    "character_zone",
]


def _needs_cascade_migration(conn):
    """Check if any table is missing ON DELETE CASCADE (proxy: check character_inventory for UNIQUE)."""
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='character_inventory'").fetchone()
    if ddl is None:
        return False
    return "ON DELETE CASCADE" not in ddl[0]


def _run_migrations(db_path):
    """Run column migrations on an existing database (fast, idempotent)."""
    conn = get_db(db_path)
    changed = False
    for table, column, sql in ADD_COLUMN_MIGRATIONS:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(sql)
            changed = True
    for table, column, sql in DROP_COLUMN_MIGRATIONS:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column in cols:
            conn.execute(sql)
            changed = True
    # Data migration: backfill prefetch=1 for existing PCs
    if changed:
        conn.execute("UPDATE characters SET prefetch = 1 WHERE type = 'pc' AND prefetch = 0")
        conn.commit()
    conn.close()


def init_schema(db_path=None):
    """Create all tables and run migrations."""
    if db_path is None:
        db_path, db_dir = resolve_db_path()
    else:
        db_dir = os.path.dirname(db_path)
    os.makedirs(db_dir, exist_ok=True)
    conn = get_db(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(INDEXES_SQL)
    # Create vec0 virtual table if sqlite-vec is loaded
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings USING vec0(embedding float[384])")
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass
    # Run column migrations
    for table, column, sql in ADD_COLUMN_MIGRATIONS:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(sql)
    for table, column, sql in DROP_COLUMN_MIGRATIONS:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column in cols:
            conn.execute(sql)
    # Recreate tables to add ON DELETE CASCADE + UNIQUE constraints
    if _needs_cascade_migration(conn):
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in _CASCADE_MIGRATION_ORDER:
            ddl, columns = _CASCADE_MIGRATIONS[table]
            _migrate_table_with_cascade(conn, table, ddl, columns)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(INDEXES_SQL)
    conn.commit()
    conn.close()
    return db_path


def format_table(cursor):
    """Format query results as a table string (sqlite3 -header -column style)."""
    description = cursor.description
    if description is None:
        return ""
    rows = cursor.fetchall()
    headers = [d[0] for d in description]
    if not rows and not headers:
        return ""
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
    lines = []
    # Header line
    lines.append(sep.join(h.ljust(w) for h, w in zip(headers, widths)))
    # Separator line (dashes)
    lines.append(sep.join("-" * w for w in widths))
    # Data rows
    for row in str_rows:
        lines.append(sep.join(val.ljust(w) for val, w in zip(row, widths)))
    return "\n".join(lines)
