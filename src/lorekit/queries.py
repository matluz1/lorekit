"""queries.py -- Shared data-access helpers to reduce query duplication.

Thin wrappers around common SELECT patterns. Each function takes a db
connection and returns plain values — no ORM, no caching, no side effects.
"""

from __future__ import annotations


def get_character_name(db, character_id: int) -> str | None:
    """Return the character's name, or None if not found."""
    row = db.execute("SELECT name FROM characters WHERE id = ?", (character_id,)).fetchone()
    return row[0] if row else None


def get_character_session_id(db, character_id: int) -> int | None:
    """Return the session_id for a character, or None if not found."""
    row = db.execute("SELECT session_id FROM characters WHERE id = ?", (character_id,)).fetchone()
    return row[0] if row else None


def get_character_type(db, character_id: int) -> str | None:
    """Return the character's type ('pc' or 'npc'), or None if not found."""
    row = db.execute("SELECT type FROM characters WHERE id = ?", (character_id,)).fetchone()
    return row[0] if row else None


def get_session_meta(db, session_id: int, key: str) -> str | None:
    """Return a single session_meta value, or None if not set."""
    row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = ?",
        (session_id, key),
    ).fetchone()
    return row[0] if row else None


def upsert_attribute(db, character_id: int, category: str, key: str, value: str) -> None:
    """Insert or update a single character attribute."""
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
        (character_id, category, key, value),
    )


def get_attribute(db, character_id: int, category: str, key: str) -> str | None:
    """Return a single attribute value, or None if not set."""
    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND category = ? AND key = ?",
        (character_id, category, key),
    ).fetchone()
    return row[0] if row else None


def get_attribute_by_key(db, character_id: int, key: str) -> str | None:
    """Return a single attribute value by key (any category), or None if not set."""
    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND key = ?",
        (character_id, key),
    ).fetchone()
    return row[0] if row else None
