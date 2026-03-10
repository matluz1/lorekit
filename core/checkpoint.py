"""checkpoint.py -- Turn checkpoint system for precise undo.

Each turn_save creates a checkpoint capturing the full mutable session state.
turn_revert pops the latest checkpoint and restores the previous one, undoing
all changes (timeline, journal, characters, items, attributes, abilities,
stories, acts, regions, metadata) made since that checkpoint.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import LoreKitError


def snapshot_session(db, session_id):
    """Read all mutable session state into a dict for checkpointing."""
    snap = {}

    # Session metadata
    snap["session_meta"] = [
        {"id": r[0], "key": r[1], "value": r[2]}
        for r in db.execute(
            "SELECT id, key, value FROM session_meta WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # Characters (full rows — needed to restore characters created then reverted)
    char_rows = db.execute(
        "SELECT id, name, level, status, type, region_id, created_at "
        "FROM characters WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    char_ids = [r[0] for r in char_rows]
    snap["characters"] = [
        {"id": r[0], "name": r[1], "level": r[2], "status": r[3],
         "type": r[4], "region_id": r[5], "created_at": r[6]}
        for r in char_rows
    ]

    # Character sub-tables
    if char_ids:
        ph = ",".join("?" * len(char_ids))
        snap["character_attributes"] = [
            {"id": r[0], "character_id": r[1], "category": r[2], "key": r[3], "value": r[4]}
            for r in db.execute(
                f"SELECT id, character_id, category, key, value FROM character_attributes "
                f"WHERE character_id IN ({ph})", char_ids,
            ).fetchall()
        ]
        snap["character_inventory"] = [
            {"id": r[0], "character_id": r[1], "name": r[2], "description": r[3],
             "quantity": r[4], "equipped": r[5]}
            for r in db.execute(
                f"SELECT id, character_id, name, description, quantity, equipped "
                f"FROM character_inventory WHERE character_id IN ({ph})", char_ids,
            ).fetchall()
        ]
        snap["character_abilities"] = [
            {"id": r[0], "character_id": r[1], "name": r[2], "description": r[3],
             "category": r[4], "uses": r[5]}
            for r in db.execute(
                f"SELECT id, character_id, name, description, category, uses "
                f"FROM character_abilities WHERE character_id IN ({ph})", char_ids,
            ).fetchall()
        ]
    else:
        snap["character_attributes"] = []
        snap["character_inventory"] = []
        snap["character_abilities"] = []

    # Stories
    snap["stories"] = [
        {"id": r[0], "adventure_size": r[1], "premise": r[2]}
        for r in db.execute(
            "SELECT id, adventure_size, premise FROM stories WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # Story acts
    snap["story_acts"] = [
        {"id": r[0], "act_order": r[1], "title": r[2], "description": r[3],
         "goal": r[4], "event": r[5], "status": r[6]}
        for r in db.execute(
            "SELECT id, act_order, title, description, goal, event, status "
            "FROM story_acts WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # Regions
    snap["regions"] = [
        {"id": r[0], "name": r[1], "description": r[2], "parent_id": r[3], "created_at": r[4]}
        for r in db.execute(
            "SELECT id, name, description, parent_id, created_at "
            "FROM regions WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    return snap


def restore_snapshot(db, session_id, snapshot):
    """Replace all mutable session state from a snapshot dict."""
    # Disable FK checks during restore to avoid ordering issues
    db.execute("PRAGMA foreign_keys = OFF")

    try:
        # --- Delete current state ---

        # Get current character IDs for sub-table cleanup
        cur_char_ids = [
            r[0] for r in db.execute(
                "SELECT id FROM characters WHERE session_id = ?", (session_id,)
            ).fetchall()
        ]
        if cur_char_ids:
            ph = ",".join("?" * len(cur_char_ids))
            db.execute(f"DELETE FROM character_attributes WHERE character_id IN ({ph})", cur_char_ids)
            db.execute(f"DELETE FROM character_inventory WHERE character_id IN ({ph})", cur_char_ids)
            db.execute(f"DELETE FROM character_abilities WHERE character_id IN ({ph})", cur_char_ids)

        db.execute("DELETE FROM characters WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM session_meta WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM story_acts WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM stories WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM regions WHERE session_id = ?", (session_id,))

        # --- Restore from snapshot ---

        # Regions (parents first to satisfy FK, but FK is off so order doesn't matter)
        for r in snapshot.get("regions", []):
            db.execute(
                "INSERT INTO regions (id, session_id, name, description, parent_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["id"], session_id, r["name"], r["description"], r["parent_id"], r["created_at"]),
            )

        # Stories
        for r in snapshot.get("stories", []):
            db.execute(
                "INSERT INTO stories (id, session_id, adventure_size, premise) VALUES (?, ?, ?, ?)",
                (r["id"], session_id, r["adventure_size"], r["premise"]),
            )

        # Story acts
        for r in snapshot.get("story_acts", []):
            db.execute(
                "INSERT INTO story_acts (id, session_id, act_order, title, description, goal, event, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (r["id"], session_id, r["act_order"], r["title"], r["description"],
                 r["goal"], r["event"], r["status"]),
            )

        # Session meta
        for r in snapshot.get("session_meta", []):
            db.execute(
                "INSERT INTO session_meta (id, session_id, key, value) VALUES (?, ?, ?, ?)",
                (r["id"], session_id, r["key"], r["value"]),
            )

        # Characters
        for r in snapshot.get("characters", []):
            db.execute(
                "INSERT INTO characters (id, session_id, name, level, status, type, region_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (r["id"], session_id, r["name"], r["level"], r["status"],
                 r["type"], r["region_id"], r["created_at"]),
            )

        # Character attributes
        for r in snapshot.get("character_attributes", []):
            db.execute(
                "INSERT INTO character_attributes (id, character_id, category, key, value) "
                "VALUES (?, ?, ?, ?, ?)",
                (r["id"], r["character_id"], r["category"], r["key"], r["value"]),
            )

        # Character inventory
        for r in snapshot.get("character_inventory", []):
            db.execute(
                "INSERT INTO character_inventory (id, character_id, name, description, quantity, equipped) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["id"], r["character_id"], r["name"], r["description"],
                 r["quantity"], r["equipped"]),
            )

        # Character abilities
        for r in snapshot.get("character_abilities", []):
            db.execute(
                "INSERT INTO character_abilities (id, character_id, name, description, category, uses) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["id"], r["character_id"], r["name"], r["description"],
                 r["category"], r["uses"]),
            )

        db.commit()
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def create_checkpoint(db, session_id):
    """Snapshot current state and save as a checkpoint. Returns checkpoint id."""
    tl_max = db.execute(
        "SELECT COALESCE(MAX(id), 0) FROM timeline WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]

    jn_max = db.execute(
        "SELECT COALESCE(MAX(id), 0) FROM journal WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]

    snap = snapshot_session(db, session_id)

    cur = db.execute(
        "INSERT INTO checkpoints (session_id, timeline_max_id, journal_max_id, snapshot) "
        "VALUES (?, ?, ?, ?)",
        (session_id, tl_max, jn_max, json.dumps(snap)),
    )
    db.commit()
    return cur.lastrowid


def revert_to_previous(db, session_id):
    """Pop the latest checkpoint and restore the previous one.

    Returns a summary string of what was undone.
    """
    rows = db.execute(
        "SELECT id, timeline_max_id, journal_max_id, snapshot "
        "FROM checkpoints WHERE session_id = ? ORDER BY id DESC LIMIT 2",
        (session_id,),
    ).fetchall()

    if len(rows) < 2:
        raise LoreKitError("Nothing to revert -- not enough checkpoints")

    latest_id = rows[0][0]
    prev_id, tl_max, jn_max, snapshot_json = rows[1]
    snapshot = json.loads(snapshot_json)

    # Find entries to remove (above the previous checkpoint's watermarks)
    tl_ids = [
        r[0] for r in db.execute(
            "SELECT id FROM timeline WHERE session_id = ? AND id > ?",
            (session_id, tl_max),
        ).fetchall()
    ]

    jn_ids = [
        r[0] for r in db.execute(
            "SELECT id FROM journal WHERE session_id = ? AND id > ?",
            (session_id, jn_max),
        ).fetchall()
    ]

    # Clean up embeddings for deleted entries
    from _vectordb import delete_embeddings
    delete_embeddings(db, "timeline", tl_ids)
    delete_embeddings(db, "journal", jn_ids)

    # Delete timeline and journal entries above watermarks
    if tl_ids:
        ph = ",".join("?" * len(tl_ids))
        db.execute(f"DELETE FROM timeline WHERE id IN ({ph})", tl_ids)
    if jn_ids:
        ph = ",".join("?" * len(jn_ids))
        db.execute(f"DELETE FROM journal WHERE id IN ({ph})", jn_ids)

    # Delete the latest checkpoint
    db.execute("DELETE FROM checkpoints WHERE id = ?", (latest_id,))

    # Restore mutable state from previous checkpoint
    restore_snapshot(db, session_id, snapshot)

    parts = []
    if tl_ids:
        parts.append(f"{len(tl_ids)} timeline")
    if jn_ids:
        parts.append(f"{len(jn_ids)} journal")
    removed = f" ({', '.join(parts)} entries removed)" if parts else ""

    return f"TURN_REVERTED: restored to checkpoint #{prev_id}{removed}"
