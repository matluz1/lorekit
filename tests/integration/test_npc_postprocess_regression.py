"""Integration tests: NPC postprocess regression.

Verify that process_npc_response correctly parses metadata blocks,
stores memories, applies state changes, and returns clean narrative.
"""

import json
import os

import pytest

pytest.importorskip("sqlite_vec")

from lorekit.npc.postprocess import process_npc_response  # noqa: E402


def _get_db():
    from lorekit.db import get_db

    return get_db(os.environ["LOREKIT_DB"])


class TestParseAndStoreMemories:
    def test_parse_and_store_memories(self, make_session, make_character):
        sid = make_session()
        npc_id = make_character(sid, name="Guard", char_type="npc")

        response = """\
*The guard eyes you warily.*

"State your business, traveler."

[MEMORIES]
- content: "A group of armed travelers arrived at the gate" | importance: 0.8 | type: experience | entities: ["travelers"]
- content: "They seem well-equipped but lack official papers" | importance: 0.6 | type: observation | entities: ["travelers"]
"""

        db = _get_db()
        try:
            narrative = process_npc_response(db, sid, npc_id, response, "Guard", "1347-03-15T14:00")
        finally:
            db.close()

        assert "[MEMORIES]" not in narrative
        assert "State your business" in narrative

        db = _get_db()
        rows = db.execute(
            "SELECT content, importance, memory_type, entities FROM npc_memories "
            "WHERE npc_id = ? AND session_id = ? ORDER BY importance DESC",
            (npc_id, sid),
        ).fetchall()
        db.close()

        assert len(rows) == 2

        contents = {r[0] for r in rows}
        assert "A group of armed travelers arrived at the gate" in contents
        assert "They seem well-equipped but lack official papers" in contents

        by_content = {r[0]: r for r in rows}
        high = by_content["A group of armed travelers arrived at the gate"]
        assert abs(high[1] - 0.8) < 0.001
        assert high[2] == "experience"
        assert "travelers" in json.loads(high[3])

        low = by_content["They seem well-equipped but lack official papers"]
        assert abs(low[1] - 0.6) < 0.001
        assert low[2] == "observation"


class TestParseAndApplyStateChanges:
    def test_parse_and_apply_state_changes(self, make_session, make_character):
        sid = make_session()
        npc_id = make_character(sid, name="Guard", char_type="npc")

        db = _get_db()
        db.execute(
            "INSERT INTO npc_core (session_id, npc_id, self_concept, emotional_state, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (sid, npc_id, "A veteran city guard", "suspicious"),
        )
        db.commit()
        db.close()

        response = """\
*The guard relaxes slightly.*

[STATE_CHANGES]
- emotional_state: "cautiously friendly"
- relationship.Valeros: "potential ally, showed proper respect"
"""

        db = _get_db()
        try:
            process_npc_response(db, sid, npc_id, response, "Guard", "1347-03-15T14:00")
        finally:
            db.close()

        db = _get_db()
        row = db.execute(
            "SELECT emotional_state, relationships FROM npc_core WHERE session_id = ? AND npc_id = ?",
            (sid, npc_id),
        ).fetchone()
        db.close()

        assert row is not None
        assert row[0] == "cautiously friendly"

        rels = json.loads(row[1])
        assert "Valeros" in rels
        assert "respect" in rels["Valeros"].lower() or "ally" in rels["Valeros"].lower()


class TestFallbackMemoryOnNoBlocks:
    def test_fallback_memory_on_no_blocks(self, make_session, make_character):
        sid = make_session()
        npc_id = make_character(sid, name="Guard", char_type="npc")

        response = "*The guard nods curtly and waves you through.*"

        db = _get_db()
        try:
            narrative = process_npc_response(db, sid, npc_id, response, "Guard", "1347-03-15T14:00")
        finally:
            db.close()

        assert narrative

        db = _get_db()
        rows = db.execute(
            "SELECT content, importance, memory_type FROM npc_memories WHERE npc_id = ? AND session_id = ?",
            (npc_id, sid),
        ).fetchall()
        db.close()

        assert len(rows) >= 1
        fallback = rows[0]
        assert abs(fallback[1] - 0.7) < 0.001
        assert fallback[2] == "experience"
        assert "guard" in fallback[0].lower() or "nods" in fallback[0].lower()


class TestCombinedMemoriesAndStateChanges:
    def test_combined_memories_and_state_changes(self, make_session, make_character):
        sid = make_session()
        npc_id = make_character(sid, name="Merchant", char_type="npc")

        response = """\
*The merchant beams.*

"A fine choice! That blade has seen many battles."

[MEMORIES]
- content: "Sold the enchanted longsword to the adventurer" | importance: 0.9 | type: experience | entities: ["adventurer"]

[STATE_CHANGES]
- emotional_state: "pleased with the profitable sale"
- relationship.adventurer: "valued customer"
"""

        db = _get_db()
        try:
            narrative = process_npc_response(db, sid, npc_id, response, "Merchant", "1347-03-15T14:00")
        finally:
            db.close()

        assert "[MEMORIES]" not in narrative
        assert "[STATE_CHANGES]" not in narrative
        assert "fine choice" in narrative

        db = _get_db()
        mem_rows = db.execute(
            "SELECT content FROM npc_memories WHERE npc_id = ? AND session_id = ?",
            (npc_id, sid),
        ).fetchall()
        core_row = db.execute(
            "SELECT emotional_state, relationships FROM npc_core WHERE session_id = ? AND npc_id = ?",
            (sid, npc_id),
        ).fetchone()
        db.close()

        assert len(mem_rows) == 1
        assert "enchanted longsword" in mem_rows[0][0]

        assert core_row is not None
        assert core_row[0] == "pleased with the profitable sale"
        rels = json.loads(core_row[1])
        assert "adventurer" in rels
