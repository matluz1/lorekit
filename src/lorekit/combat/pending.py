"""Pending resolution storage — two-phase resolution for PC reaction choice."""

from __future__ import annotations

import json

from lorekit.db import LoreKitError


def store_pending(
    db,
    session_id: int,
    attacker_id: int,
    defender_id: int,
    action_name: str,
    pack_dir: str,
    calculated_state: dict,
    available_reactions: list[dict],
    options: dict | None = None,
) -> int:
    """Store a pending resolution. Returns the pending ID.

    Replaces any existing pending resolution for the session.
    """
    db.execute("DELETE FROM pending_resolutions WHERE session_id = ?", (session_id,))

    cursor = db.execute(
        "INSERT INTO pending_resolutions "
        "(session_id, attacker_id, defender_id, action_name, pack_dir, "
        "calculated_state, available_reactions, options) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            attacker_id,
            defender_id,
            action_name,
            pack_dir,
            json.dumps(calculated_state),
            json.dumps(available_reactions),
            json.dumps(options or {}),
        ),
    )
    db.commit()
    return cursor.lastrowid


def load_pending(db, pending_id: int) -> dict:
    """Load a pending resolution by ID. Raises LoreKitError if not found."""
    row = db.execute(
        "SELECT id, session_id, attacker_id, defender_id, action_name, pack_dir, "
        "calculated_state, available_reactions, options "
        "FROM pending_resolutions WHERE id = ?",
        (pending_id,),
    ).fetchone()

    if not row:
        raise LoreKitError(f"No pending resolution with id {pending_id}")

    return {
        "id": row[0],
        "session_id": row[1],
        "attacker_id": row[2],
        "defender_id": row[3],
        "action_name": row[4],
        "pack_dir": row[5],
        "calculated_state": json.loads(row[6]),
        "available_reactions": json.loads(row[7]),
        "options": json.loads(row[8]),
    }


def delete_pending(db, pending_id: int) -> None:
    """Delete a pending resolution after confirmation."""
    db.execute("DELETE FROM pending_resolutions WHERE id = ?", (pending_id,))
    db.commit()
