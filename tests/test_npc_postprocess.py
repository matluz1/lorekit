"""Tests for core/npc_postprocess.py -- NPC response post-processing pipeline."""

import json

import pytest

from lorekit.npc.postprocess import parse_npc_metadata, process_npc_response

# ---------------------------------------------------------------------------
# parse_npc_metadata -- parser tests
# ---------------------------------------------------------------------------


class TestParseMemories:
    def test_single_memory(self):
        text = (
            "Hello adventurer!\n\n"
            "[MEMORIES]\n"
            '- content: "Met a brave adventurer" | importance: 0.8 | type: experience | entities: ["adventurer"]\n'
        )
        narrative, memories, state_changes = parse_npc_metadata(text)
        assert len(memories) == 1
        assert memories[0]["content"] == "Met a brave adventurer"
        assert memories[0]["importance"] == 0.8
        assert memories[0]["type"] == "experience"
        assert memories[0]["entities"] == ["adventurer"]
        assert state_changes == {}

    def test_multiple_memories(self):
        text = (
            "Some dialogue.\n\n"
            "[MEMORIES]\n"
            '- content: "First memory" | importance: 0.5 | type: observation | entities: []\n'
            '- content: "Second memory" | importance: 0.9 | type: relationship | entities: ["Mira", "Theron"]\n'
        )
        _, memories, _ = parse_npc_metadata(text)
        assert len(memories) == 2
        assert memories[0]["content"] == "First memory"
        assert memories[1]["entities"] == ["Mira", "Theron"]


class TestParseStateChanges:
    def test_emotional_state(self):
        text = 'I feel uneasy.\n\n[STATE_CHANGES]\n- emotional_state: "anxious and suspicious"\n'
        _, _, state_changes = parse_npc_metadata(text)
        assert state_changes["emotional_state"] == "anxious and suspicious"

    def test_relationship_dot_notation(self):
        text = (
            "We part ways.\n\n"
            "[STATE_CHANGES]\n"
            '- relationship.Mira: "growing trust"\n'
            '- relationship.Theron: "deep suspicion"\n'
        )
        _, _, state_changes = parse_npc_metadata(text)
        assert state_changes["relationship.Mira"] == "growing trust"
        assert state_changes["relationship.Theron"] == "deep suspicion"


class TestMixedBlocks:
    def test_both_blocks(self):
        text = (
            "The merchant nods slowly.\n\n"
            "[MEMORIES]\n"
            '- content: "Negotiated a fair price" | importance: 0.6 | type: experience | entities: ["merchant"]\n'
            "\n"
            "[STATE_CHANGES]\n"
            '- emotional_state: "satisfied"\n'
            '- relationship.Merchant: "respectful"\n'
        )
        narrative, memories, state_changes = parse_npc_metadata(text)
        assert len(memories) == 1
        assert memories[0]["content"] == "Negotiated a fair price"
        assert state_changes["emotional_state"] == "satisfied"
        assert state_changes["relationship.Merchant"] == "respectful"
        assert "[MEMORIES]" not in narrative
        assert "[STATE_CHANGES]" not in narrative


class TestMissingBlocks:
    def test_no_metadata(self):
        text = "Just a normal response with no metadata."
        narrative, memories, state_changes = parse_npc_metadata(text)
        assert narrative == text
        assert memories == []
        assert state_changes == {}

    def test_only_memories(self):
        text = 'Hi.\n\n[MEMORIES]\n- content: "test" | importance: 0.5 | type: experience | entities: []\n'
        _, memories, state_changes = parse_npc_metadata(text)
        assert len(memories) == 1
        assert state_changes == {}

    def test_only_state_changes(self):
        text = 'Hi.\n\n[STATE_CHANGES]\n- emotional_state: "happy"\n'
        _, memories, state_changes = parse_npc_metadata(text)
        assert memories == []
        assert state_changes["emotional_state"] == "happy"


class TestMalformedLines:
    def test_malformed_memory_skipped(self):
        text = (
            "Text.\n\n"
            "[MEMORIES]\n"
            "- this is not valid\n"
            '- content: "Valid one" | importance: 0.5 | type: experience | entities: []\n'
            "- also broken | no content key\n"
        )
        _, memories, _ = parse_npc_metadata(text)
        assert len(memories) == 1
        assert memories[0]["content"] == "Valid one"

    def test_missing_importance_defaults(self):
        text = '[MEMORIES]\n- content: "No importance given" | type: observation | entities: []\n'
        _, memories, _ = parse_npc_metadata(text)
        assert len(memories) == 1
        assert memories[0]["importance"] == 0.5

    def test_invalid_type_defaults_to_experience(self):
        text = '[MEMORIES]\n- content: "Bad type" | importance: 0.5 | type: bogus | entities: []\n'
        _, memories, _ = parse_npc_metadata(text)
        assert len(memories) == 1
        assert memories[0]["type"] == "experience"

    def test_importance_clamped(self):
        text = '[MEMORIES]\n- content: "Over" | importance: 5.0 | type: experience | entities: []\n'
        _, memories, _ = parse_npc_metadata(text)
        assert memories[0]["importance"] == 1.0

    def test_empty_state_line_skipped(self):
        text = '[STATE_CHANGES]\n- : \n- emotional_state: "ok"\n'
        _, _, state_changes = parse_npc_metadata(text)
        assert len(state_changes) == 1


class TestNarrativeStripping:
    def test_metadata_removed(self):
        text = (
            "I greet you warmly.\n\n"
            "[MEMORIES]\n"
            '- content: "Greeting" | importance: 0.3 | type: experience | entities: []\n'
            "\n"
            "[STATE_CHANGES]\n"
            '- emotional_state: "warm"\n'
        )
        narrative, _, _ = parse_npc_metadata(text)
        assert "[MEMORIES]" not in narrative
        assert "[STATE_CHANGES]" not in narrative
        assert "I greet you warmly." in narrative


# ---------------------------------------------------------------------------
# process_npc_response -- integration tests with in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    """Create an in-memory SQLite DB with the required tables."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE npc_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER, npc_id INTEGER, content TEXT,
            importance REAL, memory_type TEXT, entities TEXT,
            narrative_time TEXT, source_ids TEXT,
            access_count INTEGER DEFAULT 0, last_accessed TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )"""
    )
    conn.execute(
        """CREATE TABLE npc_core (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER, npc_id INTEGER,
            self_concept TEXT, current_goals TEXT,
            emotional_state TEXT, relationships TEXT,
            behavioral_patterns TEXT,
            updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )"""
    )
    conn.commit()
    yield conn
    conn.close()


class TestProcessNpcResponse:
    def test_memories_stored(self, db):
        text = (
            "I'll help you.\n\n"
            "[MEMORIES]\n"
            '- content: "Agreed to help the party" | importance: 0.8 | type: experience | entities: ["party"]\n'
        )
        result = process_npc_response(db, 1, 10, text, "Elara", "Day 3, morning")
        assert "I'll help you." in result
        assert "[MEMORIES]" not in result

        rows = db.execute("SELECT * FROM npc_memories WHERE npc_id = 10").fetchall()
        # 1 parsed memory + 1 interaction summary = 2
        assert len(rows) == 2

    def test_state_changes_stored(self, db):
        text = 'Fine.\n\n[STATE_CHANGES]\n- emotional_state: "annoyed"\n'
        process_npc_response(db, 1, 10, text, "Grimjaw", "")
        core = db.execute("SELECT emotional_state FROM npc_core WHERE session_id = 1 AND npc_id = 10").fetchone()
        assert core is not None
        assert core[0] == "annoyed"

    def test_relationship_merge(self, db):
        # Pre-existing relationship
        db.execute(
            "INSERT INTO npc_core (session_id, npc_id, relationships) VALUES (1, 10, ?)",
            (json.dumps({"Aldric": "neutral"}),),
        )
        db.commit()

        text = 'Goodbye.\n\n[STATE_CHANGES]\n- relationship.Mira: "growing trust"\n'
        process_npc_response(db, 1, 10, text, "Elara", "")
        core = db.execute("SELECT relationships FROM npc_core WHERE session_id = 1 AND npc_id = 10").fetchone()
        rels = json.loads(core[0])
        assert rels["Aldric"] == "neutral"
        assert rels["Mira"] == "growing trust"

    def test_interaction_summary_always_stored(self, db):
        text = "Just chatting, nothing special."
        process_npc_response(db, 1, 10, text, "Barkeep", "Evening")
        rows = db.execute("SELECT content, importance, memory_type FROM npc_memories WHERE npc_id = 10").fetchall()
        assert len(rows) == 1
        assert rows[0][1] == 0.7  # importance
        assert rows[0][2] == "experience"
        assert "[Barkeep interaction]" in rows[0][0]

    def test_fallback_no_metadata_no_crash(self, db):
        text = "Normal response without any metadata blocks."
        result = process_npc_response(db, 1, 10, text, "NPC", "")
        assert result == text
        # Only the interaction summary should be stored
        rows = db.execute("SELECT * FROM npc_memories WHERE npc_id = 10").fetchall()
        assert len(rows) == 1

    def test_core_field_cap_respected(self, db):
        long_value = "x" * 3000
        text = f'Ok.\n\n[STATE_CHANGES]\n- emotional_state: "{long_value}"\n'
        process_npc_response(db, 1, 10, text, "NPC", "")
        core = db.execute("SELECT emotional_state FROM npc_core WHERE session_id = 1 AND npc_id = 10").fetchone()
        # npc_memory.set_core enforces CORE_FIELD_CAP = 2000
        assert len(core[0]) <= 2000
