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

    # Session metadata (exclude cursor_checkpoint_id — managed outside snapshot)
    snap["session_meta"] = [
        {"id": r[0], "key": r[1], "value": r[2]}
        for r in db.execute(
            "SELECT id, key, value FROM session_meta WHERE session_id = ? AND key != 'cursor_checkpoint_id'",
            (session_id,),
        ).fetchall()
    ]

    # Characters (full rows — needed to restore characters created then reverted)
    char_rows = db.execute(
        "SELECT id, name, level, status, type, region_id, created_at FROM characters WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    char_ids = [r[0] for r in char_rows]
    snap["characters"] = [
        {"id": r[0], "name": r[1], "level": r[2], "status": r[3], "type": r[4], "region_id": r[5], "created_at": r[6]}
        for r in char_rows
    ]

    # Character sub-tables
    if char_ids:
        ph = ",".join("?" * len(char_ids))
        snap["character_attributes"] = [
            {"id": r[0], "character_id": r[1], "category": r[2], "key": r[3], "value": r[4]}
            for r in db.execute(
                f"SELECT id, character_id, category, key, value FROM character_attributes WHERE character_id IN ({ph})",
                char_ids,
            ).fetchall()
        ]
        snap["character_inventory"] = [
            {"id": r[0], "character_id": r[1], "name": r[2], "description": r[3], "quantity": r[4], "equipped": r[5]}
            for r in db.execute(
                f"SELECT id, character_id, name, description, quantity, equipped "
                f"FROM character_inventory WHERE character_id IN ({ph})",
                char_ids,
            ).fetchall()
        ]
        snap["character_abilities"] = [
            {
                "id": r[0],
                "character_id": r[1],
                "name": r[2],
                "description": r[3],
                "category": r[4],
                "uses": r[5],
                "cost": r[6],
            }
            for r in db.execute(
                f"SELECT id, character_id, name, description, category, uses, cost "
                f"FROM character_abilities WHERE character_id IN ({ph})",
                char_ids,
            ).fetchall()
        ]
        snap["combat_state"] = [
            {
                "id": r[0],
                "character_id": r[1],
                "source": r[2],
                "target_stat": r[3],
                "modifier_type": r[4],
                "value": r[5],
                "bonus_type": r[6],
                "duration_type": r[7],
                "duration": r[8],
                "save_stat": r[9],
                "save_dc": r[10],
                "created_at": r[11],
            }
            for r in db.execute(
                f"SELECT id, character_id, source, target_stat, modifier_type, "
                f"value, bonus_type, duration_type, duration, save_stat, save_dc, "
                f"created_at FROM combat_state WHERE character_id IN ({ph})",
                char_ids,
            ).fetchall()
        ]
        snap["character_aliases"] = [
            {"id": r[0], "character_id": r[1], "alias": r[2]}
            for r in db.execute(
                f"SELECT id, character_id, alias FROM character_aliases WHERE character_id IN ({ph})",
                char_ids,
            ).fetchall()
        ]
    else:
        snap["character_attributes"] = []
        snap["character_inventory"] = []
        snap["character_abilities"] = []
        snap["combat_state"] = []
        snap["character_aliases"] = []

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
        {"id": r[0], "act_order": r[1], "title": r[2], "description": r[3], "goal": r[4], "event": r[5], "status": r[6]}
        for r in db.execute(
            "SELECT id, act_order, title, description, goal, event, status FROM story_acts WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # Encounter state
    enc_rows = db.execute(
        "SELECT id, status, round, initiative_order, current_turn, created_at "
        "FROM encounter_state WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    enc_ids = [r[0] for r in enc_rows]
    snap["encounter_state"] = [
        {"id": r[0], "status": r[1], "round": r[2], "initiative_order": r[3], "current_turn": r[4], "created_at": r[5]}
        for r in enc_rows
    ]

    if enc_ids:
        eph = ",".join("?" * len(enc_ids))
        zone_rows = db.execute(
            f"SELECT id, encounter_id, name, tags FROM encounter_zones WHERE encounter_id IN ({eph})",
            enc_ids,
        ).fetchall()
        zone_ids = [r[0] for r in zone_rows]
        snap["encounter_zones"] = [{"id": r[0], "encounter_id": r[1], "name": r[2], "tags": r[3]} for r in zone_rows]
        if zone_ids:
            zph = ",".join("?" * len(zone_ids))
            snap["zone_adjacency"] = [
                {"zone_a": r[0], "zone_b": r[1], "weight": r[2]}
                for r in db.execute(
                    f"SELECT zone_a, zone_b, weight FROM zone_adjacency WHERE zone_a IN ({zph})",
                    zone_ids,
                ).fetchall()
            ]
        else:
            snap["zone_adjacency"] = []
        snap["character_zone"] = [
            {"encounter_id": r[0], "character_id": r[1], "zone_id": r[2], "team": r[3]}
            for r in db.execute(
                f"SELECT encounter_id, character_id, zone_id, team FROM character_zone WHERE encounter_id IN ({eph})",
                enc_ids,
            ).fetchall()
        ]
    else:
        snap["encounter_zones"] = []
        snap["zone_adjacency"] = []
        snap["character_zone"] = []

    # Regions
    snap["regions"] = [
        {"id": r[0], "name": r[1], "description": r[2], "parent_id": r[3], "created_at": r[4]}
        for r in db.execute(
            "SELECT id, name, description, parent_id, created_at FROM regions WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # Entry entities (tags on timeline/journal entries for this session)
    snap["entry_entities"] = [
        {"id": r[0], "source": r[1], "source_id": r[2], "entity_type": r[3], "entity_id": r[4]}
        for r in db.execute(
            """SELECT ee.id, ee.source, ee.source_id, ee.entity_type, ee.entity_id
               FROM entry_entities ee
               WHERE (ee.source = 'timeline' AND ee.source_id IN (SELECT id FROM timeline WHERE session_id = ?))
                  OR (ee.source = 'journal' AND ee.source_id IN (SELECT id FROM journal WHERE session_id = ?))""",
            (session_id, session_id),
        ).fetchall()
    ]

    # NPC memories
    snap["npc_memories"] = [
        {
            "id": r[0],
            "npc_id": r[1],
            "content": r[2],
            "importance": r[3],
            "memory_type": r[4],
            "entities": r[5],
            "narrative_time": r[6],
            "access_count": r[7],
            "last_accessed": r[8],
            "source_ids": r[9],
            "created_at": r[10],
        }
        for r in db.execute(
            "SELECT id, npc_id, content, importance, memory_type, entities, narrative_time, "
            "access_count, last_accessed, source_ids, created_at FROM npc_memories WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # NPC core identity
    snap["npc_core"] = [
        {
            "id": r[0],
            "npc_id": r[1],
            "self_concept": r[2],
            "current_goals": r[3],
            "emotional_state": r[4],
            "relationships": r[5],
            "behavioral_patterns": r[6],
            "updated_at": r[7],
        }
        for r in db.execute(
            "SELECT id, npc_id, self_concept, current_goals, emotional_state, relationships, "
            "behavioral_patterns, updated_at FROM npc_core WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # Timeline
    snap["timeline"] = [
        {"id": r[0], "entry_type": r[1], "content": r[2], "summary": r[3], "narrative_time": r[4], "created_at": r[5]}
        for r in db.execute(
            "SELECT id, entry_type, content, summary, narrative_time, created_at FROM timeline WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # Journal
    snap["journal"] = [
        {"id": r[0], "entry_type": r[1], "content": r[2], "narrative_time": r[3], "created_at": r[4]}
        for r in db.execute(
            "SELECT id, entry_type, content, narrative_time, created_at FROM journal WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    return snap


def restore_snapshot(db, session_id, snapshot):
    """Replace all mutable session state from a snapshot dict."""
    # Disable FK checks during restore to avoid ordering issues.
    # PRAGMA foreign_keys is ignored inside an active transaction,
    # so commit any pending work first.
    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")

    try:
        # --- Delete current state ---

        # Get current character IDs for sub-table cleanup
        cur_char_ids = [
            r[0] for r in db.execute("SELECT id FROM characters WHERE session_id = ?", (session_id,)).fetchall()
        ]
        if cur_char_ids:
            ph = ",".join("?" * len(cur_char_ids))
            db.execute(f"DELETE FROM character_attributes WHERE character_id IN ({ph})", cur_char_ids)
            db.execute(f"DELETE FROM character_inventory WHERE character_id IN ({ph})", cur_char_ids)
            db.execute(f"DELETE FROM character_abilities WHERE character_id IN ({ph})", cur_char_ids)
            db.execute(f"DELETE FROM combat_state WHERE character_id IN ({ph})", cur_char_ids)
            db.execute(f"DELETE FROM character_aliases WHERE character_id IN ({ph})", cur_char_ids)

        # Timeline and journal — delete current, will re-insert from snapshot
        cur_tl_ids = [
            r[0] for r in db.execute("SELECT id FROM timeline WHERE session_id = ?", (session_id,)).fetchall()
        ]
        cur_jn_ids = [r[0] for r in db.execute("SELECT id FROM journal WHERE session_id = ?", (session_id,)).fetchall()]

        from _vectordb import delete_embeddings, index_journal, index_timeline

        delete_embeddings(db, "timeline", cur_tl_ids)
        delete_embeddings(db, "journal", cur_jn_ids)

        if cur_tl_ids:
            ph = ",".join("?" * len(cur_tl_ids))
            db.execute(f"DELETE FROM timeline WHERE id IN ({ph})", cur_tl_ids)
        if cur_jn_ids:
            ph = ",".join("?" * len(cur_jn_ids))
            db.execute(f"DELETE FROM journal WHERE id IN ({ph})", cur_jn_ids)

        # Clean up entry_entities for this session's timeline/journal
        db.execute(
            """DELETE FROM entry_entities WHERE
               (source = 'timeline' AND source_id IN (SELECT id FROM timeline WHERE session_id = ?))
            OR (source = 'journal' AND source_id IN (SELECT id FROM journal WHERE session_id = ?))""",
            (session_id, session_id),
        )

        # Clean up encounter tables
        cur_enc_ids = [
            r[0] for r in db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (session_id,)).fetchall()
        ]
        if cur_enc_ids:
            eph = ",".join("?" * len(cur_enc_ids))
            cur_zone_ids = [
                r[0]
                for r in db.execute(
                    f"SELECT id FROM encounter_zones WHERE encounter_id IN ({eph})",
                    cur_enc_ids,
                ).fetchall()
            ]
            if cur_zone_ids:
                zph = ",".join("?" * len(cur_zone_ids))
                db.execute(f"DELETE FROM zone_adjacency WHERE zone_a IN ({zph})", cur_zone_ids)
            db.execute(f"DELETE FROM character_zone WHERE encounter_id IN ({eph})", cur_enc_ids)
            db.execute(f"DELETE FROM encounter_zones WHERE encounter_id IN ({eph})", cur_enc_ids)
        db.execute("DELETE FROM encounter_state WHERE session_id = ?", (session_id,))

        db.execute("DELETE FROM characters WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM session_meta WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM story_acts WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM stories WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM regions WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM npc_memories WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM npc_core WHERE session_id = ?", (session_id,))

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
                (r["id"], session_id, r["act_order"], r["title"], r["description"], r["goal"], r["event"], r["status"]),
            )

        # Encounter state
        for r in snapshot.get("encounter_state", []):
            db.execute(
                "INSERT INTO encounter_state (id, session_id, status, round, "
                "initiative_order, current_turn, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"],
                    session_id,
                    r["status"],
                    r["round"],
                    r["initiative_order"],
                    r["current_turn"],
                    r["created_at"],
                ),
            )

        for r in snapshot.get("encounter_zones", []):
            db.execute(
                "INSERT INTO encounter_zones (id, encounter_id, name, tags) VALUES (?, ?, ?, ?)",
                (r["id"], r["encounter_id"], r["name"], r["tags"]),
            )

        for r in snapshot.get("zone_adjacency", []):
            db.execute(
                "INSERT INTO zone_adjacency (zone_a, zone_b, weight) VALUES (?, ?, ?)",
                (r["zone_a"], r["zone_b"], r["weight"]),
            )

        for r in snapshot.get("character_zone", []):
            db.execute(
                "INSERT INTO character_zone (encounter_id, character_id, zone_id, team) VALUES (?, ?, ?, ?)",
                (r["encounter_id"], r["character_id"], r["zone_id"], r["team"]),
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
                (r["id"], session_id, r["name"], r["level"], r["status"], r["type"], r["region_id"], r["created_at"]),
            )

        # Character attributes
        for r in snapshot.get("character_attributes", []):
            db.execute(
                "INSERT INTO character_attributes (id, character_id, category, key, value) VALUES (?, ?, ?, ?, ?)",
                (r["id"], r["character_id"], r["category"], r["key"], r["value"]),
            )

        # Character inventory
        for r in snapshot.get("character_inventory", []):
            db.execute(
                "INSERT INTO character_inventory (id, character_id, name, description, quantity, equipped) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["id"], r["character_id"], r["name"], r["description"], r["quantity"], r["equipped"]),
            )

        # Character abilities
        for r in snapshot.get("character_abilities", []):
            db.execute(
                "INSERT INTO character_abilities (id, character_id, name, description, category, uses, cost) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["id"], r["character_id"], r["name"], r["description"], r["category"], r["uses"], r.get("cost", 0)),
            )

        # Combat state modifiers
        for r in snapshot.get("combat_state", []):
            db.execute(
                "INSERT INTO combat_state (id, character_id, source, target_stat, "
                "modifier_type, value, bonus_type, duration_type, duration, "
                "save_stat, save_dc, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"],
                    r["character_id"],
                    r["source"],
                    r["target_stat"],
                    r["modifier_type"],
                    r["value"],
                    r["bonus_type"],
                    r["duration_type"],
                    r["duration"],
                    r["save_stat"],
                    r["save_dc"],
                    r["created_at"],
                ),
            )

        # Character aliases
        for r in snapshot.get("character_aliases", []):
            db.execute(
                "INSERT INTO character_aliases (id, character_id, alias) VALUES (?, ?, ?)",
                (r["id"], r["character_id"], r["alias"]),
            )

        # Entry entities
        for r in snapshot.get("entry_entities", []):
            db.execute(
                "INSERT INTO entry_entities (id, source, source_id, entity_type, entity_id) VALUES (?, ?, ?, ?, ?)",
                (r["id"], r["source"], r["source_id"], r["entity_type"], r["entity_id"]),
            )

        # NPC memories
        for r in snapshot.get("npc_memories", []):
            db.execute(
                "INSERT INTO npc_memories (id, session_id, npc_id, content, importance, memory_type, "
                "entities, narrative_time, access_count, last_accessed, source_ids, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"],
                    session_id,
                    r["npc_id"],
                    r["content"],
                    r["importance"],
                    r["memory_type"],
                    r["entities"],
                    r["narrative_time"],
                    r["access_count"],
                    r["last_accessed"],
                    r["source_ids"],
                    r["created_at"],
                ),
            )

        # NPC core identity
        for r in snapshot.get("npc_core", []):
            db.execute(
                "INSERT INTO npc_core (id, session_id, npc_id, self_concept, current_goals, "
                "emotional_state, relationships, behavioral_patterns, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"],
                    session_id,
                    r["npc_id"],
                    r["self_concept"],
                    r["current_goals"],
                    r["emotional_state"],
                    r["relationships"],
                    r["behavioral_patterns"],
                    r["updated_at"],
                ),
            )

        # Timeline
        for r in snapshot.get("timeline", []):
            db.execute(
                "INSERT INTO timeline (id, session_id, entry_type, content, summary, narrative_time, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"],
                    session_id,
                    r["entry_type"],
                    r["content"],
                    r["summary"],
                    r["narrative_time"],
                    r["created_at"],
                ),
            )
            if r["summary"]:
                index_timeline(db, session_id, r["id"], r["entry_type"], r["summary"], r["created_at"])

        # Journal
        for r in snapshot.get("journal", []):
            db.execute(
                "INSERT INTO journal (id, session_id, entry_type, content, narrative_time, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["id"], session_id, r["entry_type"], r["content"], r["narrative_time"], r["created_at"]),
            )
            index_journal(db, session_id, r["id"], r["entry_type"], r["content"], r["created_at"])

        db.commit()
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _get_cursor(db, session_id):
    """Return the current cursor checkpoint ID, or the latest checkpoint if unset."""
    row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'cursor_checkpoint_id'",
        (session_id,),
    ).fetchone()
    if row:
        cp_id = int(row[0])
        # Validate it still exists
        exists = db.execute("SELECT 1 FROM checkpoints WHERE id = ?", (cp_id,)).fetchone()
        if exists:
            return cp_id
    # Fallback: latest checkpoint
    row = db.execute("SELECT MAX(id) FROM checkpoints WHERE session_id = ?", (session_id,)).fetchone()
    return row[0] if row and row[0] is not None else None


def _set_cursor(db, session_id, checkpoint_id):
    """Upsert cursor_checkpoint_id in session_meta."""
    existing = db.execute(
        "SELECT id FROM session_meta WHERE session_id = ? AND key = 'cursor_checkpoint_id'",
        (session_id,),
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE session_meta SET value = ? WHERE id = ?",
            (str(checkpoint_id), existing[0]),
        )
    else:
        db.execute(
            "INSERT INTO session_meta (session_id, key, value) VALUES (?, 'cursor_checkpoint_id', ?)",
            (session_id, str(checkpoint_id)),
        )


def create_checkpoint(db, session_id):
    """Snapshot current state and save as a checkpoint. Returns checkpoint id."""
    # Branch truncation: if cursor is behind tip, delete future checkpoints
    cursor = _get_cursor(db, session_id)
    if cursor is not None:
        tip = db.execute("SELECT MAX(id) FROM checkpoints WHERE session_id = ?", (session_id,)).fetchone()[0]
        if tip is not None and cursor < tip:
            db.execute(
                "DELETE FROM checkpoints WHERE session_id = ? AND id > ?",
                (session_id, cursor),
            )

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
        "INSERT INTO checkpoints (session_id, timeline_max_id, journal_max_id, snapshot) VALUES (?, ?, ?, ?)",
        (session_id, tl_max, jn_max, json.dumps(snap)),
    )
    new_id = cur.lastrowid
    _set_cursor(db, session_id, new_id)
    db.commit()
    return new_id


def revert_to_previous(db, session_id, steps=1):
    """Move cursor back by *steps* checkpoints and restore that state.

    Checkpoints are preserved (not deleted) so redo is possible.
    Returns a summary string.
    """
    all_cps = db.execute(
        "SELECT id FROM checkpoints WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    cp_ids = [r[0] for r in all_cps]

    if len(cp_ids) < 2:
        raise LoreKitError("Nothing to revert -- not enough checkpoints")

    cursor = _get_cursor(db, session_id)
    if cursor is None or cursor not in cp_ids:
        cursor = cp_ids[-1]

    cursor_idx = cp_ids.index(cursor)
    target_idx = cursor_idx - steps
    if target_idx < 0:
        target_idx = 0
    if target_idx == cursor_idx:
        raise LoreKitError("Nothing to revert -- already at earliest checkpoint")

    target_id = cp_ids[target_idx]
    snapshot_json = db.execute("SELECT snapshot FROM checkpoints WHERE id = ?", (target_id,)).fetchone()[0]
    snapshot = json.loads(snapshot_json)

    restore_snapshot(db, session_id, snapshot)
    _set_cursor(db, session_id, target_id)
    db.commit()

    actual_steps = cursor_idx - target_idx
    skipped = f" (skipped {actual_steps - 1})" if actual_steps > 1 else ""
    return f"TURN_REVERTED: restored to checkpoint #{target_id}{skipped}"


def advance_to_next(db, session_id, steps=1):
    """Move cursor forward by *steps* checkpoints (redo) and restore that state.

    Only works if future checkpoints exist (no new action since revert).
    Returns a summary string.
    """
    all_cps = db.execute(
        "SELECT id FROM checkpoints WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    cp_ids = [r[0] for r in all_cps]

    if not cp_ids:
        raise LoreKitError("Nothing to redo -- no checkpoints")

    cursor = _get_cursor(db, session_id)
    if cursor is None or cursor not in cp_ids:
        cursor = cp_ids[-1]

    cursor_idx = cp_ids.index(cursor)
    target_idx = cursor_idx + steps
    if target_idx >= len(cp_ids):
        target_idx = len(cp_ids) - 1
    if target_idx == cursor_idx:
        raise LoreKitError("Nothing to redo -- already at latest checkpoint")

    target_id = cp_ids[target_idx]
    snapshot_json = db.execute("SELECT snapshot FROM checkpoints WHERE id = ?", (target_id,)).fetchone()[0]
    snapshot = json.loads(snapshot_json)

    restore_snapshot(db, session_id, snapshot)
    _set_cursor(db, session_id, target_id)
    db.commit()

    actual_steps = target_idx - cursor_idx
    skipped = f" (skipped {actual_steps - 1})" if actual_steps > 1 else ""
    return f"TURN_ADVANCED: restored to checkpoint #{target_id}{skipped}"
