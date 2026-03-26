"""checkpoint.py -- Turn checkpoint system for precise undo.

Each turn_save creates a checkpoint capturing the full mutable session state.
turn_revert pops the latest checkpoint and restores the previous one, undoing
all changes (timeline, journal, characters, items, attributes, abilities,
stories, acts, regions, metadata) made since that checkpoint.
"""

import json

from lorekit.db import LoreKitError
from lorekit.npc.memory import NPC_CORE_FIELDS


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
        "SELECT id, name, gender, level, status, type, prefetch, region_id, created_at FROM characters WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    char_ids = [r[0] for r in char_rows]
    snap["characters"] = [
        {
            "id": r[0],
            "name": r[1],
            "gender": r[2],
            "level": r[3],
            "status": r[4],
            "type": r[5],
            "prefetch": r[6],
            "region_id": r[7],
            "created_at": r[8],
        }
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
    _core_cols = ", ".join(NPC_CORE_FIELDS)
    snap["npc_core"] = [
        {
            "id": r[0],
            "npc_id": r[1],
            **{f: r[i + 2] for i, f in enumerate(NPC_CORE_FIELDS)},
            "updated_at": r[len(NPC_CORE_FIELDS) + 2],
        }
        for r in db.execute(
            f"SELECT id, npc_id, {_core_cols}, updated_at FROM npc_core WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # Timeline
    snap["timeline"] = [
        {
            "id": r[0],
            "entry_type": r[1],
            "content": r[2],
            "summary": r[3],
            "narrative_time": r[4],
            "scope": r[5],
            "created_at": r[6],
        }
        for r in db.execute(
            "SELECT id, entry_type, content, summary, narrative_time, scope, created_at FROM timeline WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    ]

    # Journal
    snap["journal"] = [
        {"id": r[0], "entry_type": r[1], "content": r[2], "narrative_time": r[3], "scope": r[4], "created_at": r[5]}
        for r in db.execute(
            "SELECT id, entry_type, content, narrative_time, scope, created_at FROM journal WHERE session_id = ?",
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

        from lorekit.support.vectordb import delete_embeddings, index_journal, index_timeline

        delete_embeddings(db, "timeline", cur_tl_ids)
        delete_embeddings(db, "journal", cur_jn_ids)

        # Clean up entry_entities BEFORE deleting timeline/journal rows
        # (the subquery depends on those rows still existing)
        if cur_tl_ids:
            ph = ",".join("?" * len(cur_tl_ids))
            db.execute(f"DELETE FROM entry_entities WHERE source = 'timeline' AND source_id IN ({ph})", cur_tl_ids)
        if cur_jn_ids:
            ph = ",".join("?" * len(cur_jn_ids))
            db.execute(f"DELETE FROM entry_entities WHERE source = 'journal' AND source_id IN ({ph})", cur_jn_ids)

        if cur_tl_ids:
            ph = ",".join("?" * len(cur_tl_ids))
            db.execute(f"DELETE FROM timeline WHERE id IN ({ph})", cur_tl_ids)
        if cur_jn_ids:
            ph = ",".join("?" * len(cur_jn_ids))
            db.execute(f"DELETE FROM journal WHERE id IN ({ph})", cur_jn_ids)

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
                "INSERT INTO characters (id, session_id, name, gender, level, status, type, prefetch, region_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"],
                    session_id,
                    r["name"],
                    r.get("gender", ""),
                    r["level"],
                    r["status"],
                    r["type"],
                    r.get("prefetch", 1 if r["type"] == "pc" else 0),
                    r["region_id"],
                    r["created_at"],
                ),
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

        # Entry entities — use INSERT OR REPLACE to handle orphaned rows
        # left behind by previous buggy restores where cleanup was skipped
        for r in snapshot.get("entry_entities", []):
            db.execute(
                "INSERT OR REPLACE INTO entry_entities (id, source, source_id, entity_type, entity_id) VALUES (?, ?, ?, ?, ?)",
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
        _core_cols = ", ".join(NPC_CORE_FIELDS)
        _core_placeholders = ", ".join("?" for _ in range(len(NPC_CORE_FIELDS) + 4))
        for r in snapshot.get("npc_core", []):
            db.execute(
                f"INSERT INTO npc_core (id, session_id, npc_id, {_core_cols}, updated_at) "
                f"VALUES ({_core_placeholders})",
                (r["id"], session_id, r["npc_id"], *(r[f] for f in NPC_CORE_FIELDS), r["updated_at"]),
            )

        # Timeline
        for r in snapshot.get("timeline", []):
            db.execute(
                "INSERT INTO timeline (id, session_id, entry_type, content, summary, narrative_time, scope, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"],
                    session_id,
                    r["entry_type"],
                    r["content"],
                    r["summary"],
                    r["narrative_time"],
                    r.get("scope", "participants"),
                    r["created_at"],
                ),
            )
            if r["summary"]:
                index_timeline(db, session_id, r["id"], r["entry_type"], r["summary"], r["created_at"])

        # Journal
        for r in snapshot.get("journal", []):
            db.execute(
                "INSERT INTO journal (id, session_id, entry_type, content, narrative_time, scope, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"],
                    session_id,
                    r["entry_type"],
                    r["content"],
                    r["narrative_time"],
                    r.get("scope", "participants"),
                    r["created_at"],
                ),
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


def create_checkpoint(db, session_id, *, force: bool = False, kind: str = "auto"):
    """Snapshot current state and save as a checkpoint. Returns checkpoint id.

    kind: 'turn' for turn_save checkpoints (stable narrative+mechanical boundary),
          'auto' for combat auto-checkpoints (undo points within a turn).
    """
    # Branch truncation: if cursor is behind tip, delete future checkpoints
    cursor = _get_cursor(db, session_id)
    if cursor is not None:
        tip = db.execute("SELECT MAX(id) FROM checkpoints WHERE session_id = ?", (session_id,)).fetchone()[0]
        if tip is not None and cursor < tip:
            if not force:
                raise LoreKitError(
                    "Cursor is behind tip — calling turn_save will delete future checkpoints. "
                    "Use turn_advance to move forward, or pass force=True to confirm."
                )
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
        "INSERT INTO checkpoints (session_id, timeline_max_id, journal_max_id, snapshot, kind) VALUES (?, ?, ?, ?, ?)",
        (session_id, tl_max, jn_max, json.dumps(snap), kind),
    )
    new_id = cur.lastrowid
    _set_cursor(db, session_id, new_id)
    db.commit()
    return new_id


def _find_turn_index(turn_ids: list[int], cursor: int | None) -> int:
    """Find the index in turn_ids that the cursor is at or just after.

    If the cursor sits on a turn checkpoint, return that index.
    If it sits on an auto-checkpoint between two turns, return the
    index of the preceding turn checkpoint.
    If cursor is None or before all turns, return the last index.
    """
    if cursor is None:
        return len(turn_ids) - 1
    # Exact match — cursor is on a turn checkpoint
    if cursor in turn_ids:
        return turn_ids.index(cursor)
    # Cursor is on an auto-checkpoint — find the preceding turn
    for i in range(len(turn_ids) - 1, -1, -1):
        if turn_ids[i] < cursor:
            return i
    return len(turn_ids) - 1


def _delete_auto_checkpoints_between(db, session_id: int, after_id: int, up_to_id: int | None):
    """Delete auto-checkpoints (kind != 'turn') in the range (after_id, up_to_id].

    Called after revert to clean up within-turn undo points that are no longer
    meaningful once the turn boundary is restored.
    """
    if up_to_id is None:
        return
    db.execute(
        "DELETE FROM checkpoints WHERE session_id = ? AND kind != 'turn' AND id > ? AND id <= ?",
        (session_id, after_id, up_to_id),
    )


def revert_to_previous(db, session_id, steps=1):
    """Move cursor back by *steps* turn checkpoints and restore that state.

    Only kind='turn' checkpoints count as steps — auto-checkpoints (within-turn
    undo points) are skipped. Turn checkpoints are preserved (not deleted) so
    redo is possible, but auto-checkpoints between the old and new cursor
    positions are cleaned up.

    Returns a summary string.
    """
    turn_cps = db.execute(
        "SELECT id FROM checkpoints WHERE session_id = ? AND kind = 'turn' ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    turn_ids = [r[0] for r in turn_cps]

    if len(turn_ids) < 2:
        raise LoreKitError("Nothing to revert -- not enough checkpoints")

    cursor = _get_cursor(db, session_id)
    # Find which turn checkpoint the cursor is at or just after
    current_turn_idx = _find_turn_index(turn_ids, cursor)

    target_idx = current_turn_idx - steps
    if target_idx < 0:
        target_idx = 0
    if target_idx == current_turn_idx:
        raise LoreKitError("Nothing to revert -- already at earliest checkpoint")

    target_id = turn_ids[target_idx]
    snapshot_json = db.execute("SELECT snapshot FROM checkpoints WHERE id = ?", (target_id,)).fetchone()[0]
    snapshot = json.loads(snapshot_json)

    restore_snapshot(db, session_id, snapshot)
    _set_cursor(db, session_id, target_id)

    # Clean up auto-checkpoints between target and the previous cursor position
    _delete_auto_checkpoints_between(db, session_id, target_id, cursor)

    db.commit()

    actual_steps = current_turn_idx - target_idx
    skipped = f" (skipped {actual_steps - 1})" if actual_steps > 1 else ""
    return f"TURN_REVERTED: restored to checkpoint #{target_id}{skipped}"


def restore_to_last_turn(db, session_id):
    """Roll back to the most recent kind='turn' checkpoint if the cursor is past it.

    Called on session_resume to discard dirty mechanical state left by an
    interrupted turn (e.g. Ctrl+C after NPC combat but before turn_save).
    Returns a message if a rollback happened, or None if state was clean.
    """
    cursor = _get_cursor(db, session_id)
    if cursor is None:
        return None

    # Find the most recent turn checkpoint
    row = db.execute(
        "SELECT id FROM checkpoints WHERE session_id = ? AND kind = 'turn' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None:
        return None

    last_turn_id = row[0]
    if cursor <= last_turn_id:
        # Cursor is at or before the last turn checkpoint — no dirty state
        return None

    # Dirty state detected: auto-checkpoints exist past the last turn checkpoint.
    # Restore to the turn checkpoint and delete the orphan auto-checkpoints.
    snapshot_json = db.execute("SELECT snapshot FROM checkpoints WHERE id = ?", (last_turn_id,)).fetchone()[0]
    snapshot = json.loads(snapshot_json)

    restore_snapshot(db, session_id, snapshot)
    _set_cursor(db, session_id, last_turn_id)
    db.execute(
        "DELETE FROM checkpoints WHERE session_id = ? AND id > ?",
        (session_id, last_turn_id),
    )
    db.commit()

    return f"⚠ RECOVERY: rolled back to last stable checkpoint #{last_turn_id} (discarded uncommitted combat state)"


def advance_to_next(db, session_id, steps=1):
    """Move cursor forward by *steps* turn checkpoints (redo) and restore that state.

    Only kind='turn' checkpoints count as steps. Only works if future turn
    checkpoints exist (no new action since revert).
    Returns a summary string.
    """
    turn_cps = db.execute(
        "SELECT id FROM checkpoints WHERE session_id = ? AND kind = 'turn' ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    turn_ids = [r[0] for r in turn_cps]

    if not turn_ids:
        raise LoreKitError("Nothing to redo -- no checkpoints")

    cursor = _get_cursor(db, session_id)
    current_turn_idx = _find_turn_index(turn_ids, cursor)

    target_idx = current_turn_idx + steps
    if target_idx >= len(turn_ids):
        target_idx = len(turn_ids) - 1
    if target_idx == current_turn_idx:
        raise LoreKitError("Nothing to redo -- already at latest checkpoint")

    target_id = turn_ids[target_idx]
    snapshot_json = db.execute("SELECT snapshot FROM checkpoints WHERE id = ?", (target_id,)).fetchone()[0]
    snapshot = json.loads(snapshot_json)

    restore_snapshot(db, session_id, snapshot)
    _set_cursor(db, session_id, target_id)
    db.commit()

    actual_steps = target_idx - current_turn_idx
    skipped = f" (skipped {actual_steps - 1})" if actual_steps > 1 else ""
    return f"TURN_ADVANCED: restored to checkpoint #{target_id}{skipped}"
