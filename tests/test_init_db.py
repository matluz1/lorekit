"""Tests for database initialization."""

import os
import sqlite3

from lorekit.server import init_db


def test_init_db_creates_file():
    result = init_db()
    assert "Database initialized" in result
    db = os.environ["LOREKIT_DB"]
    assert os.path.isfile(db)


def test_creates_all_tables():
    conn = sqlite3.connect(os.environ["LOREKIT_DB"])
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE 'vec_embeddings_%' "  # sqlite-vec shadow tables
            "ORDER BY name"
        ).fetchall()
    ]
    conn.close()
    expected = [
        "character_abilities",
        "character_aliases",
        "character_attributes",
        "character_inventory",
        "character_zone",
        "characters",
        "checkpoints",
        "combat_state",
        "embeddings",
        "encounter_state",
        "encounter_zones",
        "entry_entities",
        "journal",
        "npc_core",
        "npc_memories",
        "regions",
        "session_meta",
        "sessions",
        "stories",
        "story_acts",
        "timeline",
        "vec_embeddings",
        "zone_adjacency",
    ]
    assert sorted(tables) == expected


def test_idempotent_reinit():
    result = init_db()
    assert "Database initialized" in result
    result = init_db()
    assert "Database initialized" in result


def test_characters_has_type_column():
    conn = sqlite3.connect(os.environ["LOREKIT_DB"])
    cols = [row[1] for row in conn.execute("PRAGMA table_info(characters)").fetchall()]
    conn.close()
    assert "type" in cols


def test_characters_has_region_id_column():
    conn = sqlite3.connect(os.environ["LOREKIT_DB"])
    cols = [row[1] for row in conn.execute("PRAGMA table_info(characters)").fetchall()]
    conn.close()
    assert "region_id" in cols
