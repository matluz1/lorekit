"""Tests for NPC Memory Architecture."""

import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "core"))


def _extract_id(result):
    m = re.search(r":\s*(\d+)", result)
    assert m, f"Could not extract ID from: {result}"
    return int(m.group(1))


@pytest.fixture
def make_npc(make_session):
    """Factory that creates an NPC and returns (session_id, npc_id)."""

    def _make(name="Test NPC", session_id=None):
        if session_id is None:
            session_id = make_session()
        from mcp_server import character_build

        result = character_build(session=session_id, name=name, level=1, type="npc")
        npc_id = _extract_id(result)
        return session_id, npc_id

    return _make


# ---------------------------------------------------------------------------
# Scoring formula tests
# ---------------------------------------------------------------------------


class TestScoreMemories:
    def test_basic_scoring(self):
        """Min-max normalization with different importance values."""
        from npc_memory import score_memories

        memories = [
            {"importance": 0.9, "last_accessed": None, "created_at": "2026-01-01T00:00:00Z"},
            {"importance": 0.3, "last_accessed": None, "created_at": "2026-01-01T00:00:00Z"},
            {"importance": 0.6, "last_accessed": None, "created_at": "2026-01-01T00:00:00Z"},
        ]
        results = score_memories(memories, query_embedding=None, narrative_now="")
        # Highest importance should rank first
        assert results[0][0]["importance"] == 0.9
        assert results[-1][0]["importance"] == 0.3

    def test_single_memory(self):
        """Single memory edge case — should not crash on min-max normalization."""
        from npc_memory import score_memories

        memories = [{"importance": 0.5, "last_accessed": None, "created_at": "2026-01-01T00:00:00Z"}]
        results = score_memories(memories, query_embedding=None, narrative_now="")
        assert len(results) == 1
        # With single memory, all normalized values should be 0.5 (midpoint)
        assert results[0][1] == pytest.approx(1.5, abs=0.1)

    def test_all_equal_scores(self):
        """All-equal scores should produce equal final scores."""
        from npc_memory import score_memories

        memories = [
            {"importance": 0.5, "last_accessed": None, "created_at": "2026-01-01T00:00:00Z"},
            {"importance": 0.5, "last_accessed": None, "created_at": "2026-01-01T00:00:00Z"},
        ]
        results = score_memories(memories, query_embedding=None, narrative_now="")
        assert results[0][1] == pytest.approx(results[1][1])

    def test_noise_changes_scores(self):
        """With noise > 0, scores should vary across runs (probabilistic)."""
        from npc_memory import score_memories

        memories = [
            {"importance": 0.5, "last_accessed": None, "created_at": "2026-01-01T00:00:00Z"},
            {"importance": 0.5, "last_accessed": None, "created_at": "2026-01-01T00:00:00Z"},
        ]
        scores_sets = set()
        for _ in range(10):
            results = score_memories(memories, query_embedding=None, narrative_now="", noise=0.5)
            scores_sets.add(round(results[0][1], 4))
        # With noise, we should see some variation
        assert len(scores_sets) > 1

    def test_cosine_similarity(self):
        """Test relevance dimension via cosine similarity."""
        from npc_memory import score_memories

        memories = [
            {
                "importance": 0.5,
                "last_accessed": None,
                "created_at": "2026-01-01T00:00:00Z",
                "embedding": [1.0, 0.0, 0.0],
            },
            {
                "importance": 0.5,
                "last_accessed": None,
                "created_at": "2026-01-01T00:00:00Z",
                "embedding": [0.0, 1.0, 0.0],
            },
        ]
        query = [1.0, 0.0, 0.0]
        results = score_memories(memories, query_embedding=query, narrative_now="")
        # First memory should rank higher (exact match with query)
        assert results[0][0]["embedding"] == [1.0, 0.0, 0.0]

    def test_empty_memories(self):
        """Empty list should return empty."""
        from npc_memory import score_memories

        assert score_memories([], None, "") == []


# ---------------------------------------------------------------------------
# npc_memory_add round-trip
# ---------------------------------------------------------------------------


class TestNpcMemoryAdd:
    def test_add_and_verify(self, make_npc):
        """Add memory, verify in DB, verify embedding created."""
        session_id, npc_id = make_npc()

        from mcp_server import npc_memory_add

        result = npc_memory_add(
            session_id=session_id,
            npc_id=npc_id,
            content="The hero saved my village",
            importance=0.8,
            memory_type="experience",
            entities='["Hero", "Village"]',
            narrative_time="1347-03-15T14:00",
        )
        assert "NPC_MEMORY_ADDED" in result
        memory_id = _extract_id(result)

        # Verify in DB
        from _db import require_db

        db = require_db()
        row = db.execute(
            "SELECT content, importance, memory_type FROM npc_memories WHERE id = ?", (memory_id,)
        ).fetchone()
        db.close()
        assert row is not None
        assert row[0] == "The hero saved my village"
        assert row[1] == 0.8
        assert row[2] == "experience"

    def test_add_by_name(self, make_npc):
        """Can add memory by NPC name instead of ID."""
        session_id, npc_id = make_npc(name="Bartender Bob")

        from mcp_server import npc_memory_add

        result = npc_memory_add(
            session_id=session_id,
            npc_id="Bartender Bob",
            content="A stranger arrived at my tavern",
            narrative_time="1347-03-15",
        )
        assert "NPC_MEMORY_ADDED" in result

    def test_invalid_memory_type(self, make_npc):
        """Invalid memory_type should error."""
        session_id, npc_id = make_npc()

        from mcp_server import npc_memory_add

        result = npc_memory_add(
            session_id=session_id,
            npc_id=npc_id,
            content="test",
            memory_type="invalid",
            narrative_time="",
        )
        assert "ERROR" in result

    def test_pc_rejected(self, make_session, make_character):
        """Adding memory to a PC should fail."""
        sid = make_session()
        pc_id = make_character(sid, name="PC Hero", char_type="pc")

        from mcp_server import npc_memory_add

        result = npc_memory_add(session_id=sid, npc_id=pc_id, content="test", narrative_time="")
        assert "ERROR" in result
        assert "not an NPC" in result


# ---------------------------------------------------------------------------
# character_view NPC extension
# ---------------------------------------------------------------------------


class TestCharacterViewNpc:
    def test_view_includes_core_and_memories(self, make_npc):
        """character_view for NPC includes core identity and top memories."""
        session_id, npc_id = make_npc()

        # Set core identity
        from mcp_server import character_sheet_update

        result = character_sheet_update(
            character_id=npc_id,
            core=json.dumps(
                {
                    "self_concept": "I am a wise old sage",
                    "current_goals": "Find the ancient tome",
                    "emotional_state": "contemplative",
                }
            ),
        )
        assert "NPC_CORE_SET" in result

        # Add some memories
        from mcp_server import npc_memory_add

        npc_memory_add(
            session_id=session_id,
            npc_id=npc_id,
            content="Met the hero at the crossroads",
            importance=0.9,
            narrative_time="day 1",
        )
        npc_memory_add(
            session_id=session_id,
            npc_id=npc_id,
            content="Heard rumors of dragon attacks",
            importance=0.7,
            narrative_time="day 2",
        )

        from mcp_server import character_view

        view = character_view(npc_id)
        assert "--- NPC CORE ---" in view
        assert "I am a wise old sage" in view
        assert "Find the ancient tome" in view
        assert "--- NPC MEMORIES ---" in view
        assert "Met the hero at the crossroads" in view

    def test_pc_view_no_npc_sections(self, make_session, make_character):
        """PC view should NOT include NPC sections."""
        sid = make_session()
        pc_id = make_character(sid, name="Hero")

        from mcp_server import character_view

        view = character_view(pc_id)
        assert "--- NPC CORE ---" not in view
        assert "--- NPC MEMORIES ---" not in view


# ---------------------------------------------------------------------------
# character_sheet_update with core param
# ---------------------------------------------------------------------------


class TestSheetUpdateCore:
    def test_core_update(self, make_npc):
        """character_sheet_update with core sets npc_core."""
        session_id, npc_id = make_npc()

        from mcp_server import character_sheet_update

        result = character_sheet_update(
            character_id=npc_id,
            core=json.dumps({"self_concept": "A humble blacksmith"}),
        )
        assert "NPC_CORE_SET" in result

        # Verify in DB
        from _db import require_db
        from npc_memory import get_core

        db = require_db()
        core = get_core(db, session_id, npc_id)
        db.close()
        assert core is not None
        assert core["self_concept"] == "A humble blacksmith"

    def test_core_cap_enforcement(self, make_npc):
        """Core fields are truncated to 2,000 chars."""
        session_id, npc_id = make_npc()

        long_text = "x" * 3000

        from mcp_server import character_sheet_update

        character_sheet_update(
            character_id=npc_id,
            core=json.dumps({"self_concept": long_text}),
        )

        from _db import require_db
        from npc_memory import get_core

        db = require_db()
        core = get_core(db, session_id, npc_id)
        db.close()
        assert len(core["self_concept"]) == 2000

    def test_core_upsert(self, make_npc):
        """Setting core twice updates existing row."""
        session_id, npc_id = make_npc()

        from mcp_server import character_sheet_update

        character_sheet_update(
            character_id=npc_id,
            core=json.dumps({"self_concept": "version 1"}),
        )
        character_sheet_update(
            character_id=npc_id,
            core=json.dumps({"self_concept": "version 2", "current_goals": "new goal"}),
        )

        from _db import require_db
        from npc_memory import get_core

        db = require_db()
        core = get_core(db, session_id, npc_id)
        db.close()
        assert core["self_concept"] == "version 2"
        assert core["current_goals"] == "new goal"


# ---------------------------------------------------------------------------
# character_build with core param
# ---------------------------------------------------------------------------


class TestBuildWithCore:
    def test_build_npc_with_core(self, make_session):
        """character_build with core creates npc_core row."""
        sid = make_session()

        from mcp_server import character_build

        result = character_build(
            session=sid,
            name="Elder Sage",
            level=5,
            type="npc",
            core=json.dumps(
                {
                    "self_concept": "Ancient keeper of secrets",
                    "emotional_state": "serene",
                }
            ),
        )
        assert "CHARACTER_BUILT" in result
        assert "core_set=True" in result

        npc_id = _extract_id(result)

        from _db import require_db
        from npc_memory import get_core

        db = require_db()
        core = get_core(db, sid, npc_id)
        db.close()
        assert core is not None
        assert core["self_concept"] == "Ancient keeper of secrets"

    def test_build_pc_ignores_core(self, make_session):
        """character_build for PC ignores core param."""
        sid = make_session()

        from mcp_server import character_build

        result = character_build(
            session=sid,
            name="Hero",
            level=1,
            type="pc",
            core=json.dumps({"self_concept": "should be ignored"}),
        )
        assert "CHARACTER_BUILT" in result
        assert "core_set" not in result


# ---------------------------------------------------------------------------
# Checkpoint snapshot/restore
# ---------------------------------------------------------------------------


class TestCheckpointNpcMemory:
    def test_snapshot_restore(self, make_npc):
        """Snapshot captures npc_memories and npc_core; restore recovers them."""
        session_id, npc_id = make_npc()

        from _db import require_db

        # Set up core and memories
        from mcp_server import character_sheet_update, npc_memory_add

        character_sheet_update(
            character_id=npc_id,
            core=json.dumps({"self_concept": "A tavern keeper"}),
        )
        npc_memory_add(
            session_id=session_id,
            npc_id=npc_id,
            content="First memory",
            importance=0.8,
            narrative_time="day 1",
        )

        # Take snapshot
        from checkpoint import snapshot_session

        db = require_db()
        snap = snapshot_session(db, session_id)
        db.close()

        assert len(snap["npc_memories"]) == 1
        assert snap["npc_memories"][0]["content"] == "First memory"
        assert len(snap["npc_core"]) == 1
        assert snap["npc_core"][0]["self_concept"] == "A tavern keeper"

        # Add more data, then restore
        npc_memory_add(
            session_id=session_id,
            npc_id=npc_id,
            content="Second memory",
            importance=0.5,
            narrative_time="day 2",
        )

        db = require_db()
        # Verify 2 memories exist before restore
        count = db.execute("SELECT COUNT(*) FROM npc_memories WHERE session_id = ?", (session_id,)).fetchone()[0]
        assert count == 2

        from checkpoint import restore_snapshot

        restore_snapshot(db, session_id, snap)

        # After restore, should be back to 1 memory
        count = db.execute("SELECT COUNT(*) FROM npc_memories WHERE session_id = ?", (session_id,)).fetchone()[0]
        assert count == 1
        row = db.execute("SELECT content FROM npc_memories WHERE session_id = ?", (session_id,)).fetchone()
        assert row[0] == "First memory"

        # Core should still be present
        core = db.execute(
            "SELECT self_concept FROM npc_core WHERE session_id = ? AND npc_id = ?",
            (session_id, npc_id),
        ).fetchone()
        assert core[0] == "A tavern keeper"
        db.close()


# ---------------------------------------------------------------------------
# Narrative-time scoring tests
# ---------------------------------------------------------------------------


def test_score_memories_uses_narrative_time():
    """Recency decays based on narrative hours, not wall-clock."""
    from npc_memory import score_memories

    # Two memories: one from 1 narrative hour ago, one from 500 hours ago
    memories = [
        {"importance": 0.5, "narrative_time": "1347-03-15T09:00", "last_accessed": ""},
        {"importance": 0.5, "narrative_time": "1347-02-22T10:00", "last_accessed": ""},
    ]

    scored = score_memories(memories, query_embedding=None, narrative_now="1347-03-15T10:00")

    # The recent memory (1 hour ago) should score higher than the old one (500+ hours)
    recent_mem = scored[0][0]
    assert recent_mem["narrative_time"] == "1347-03-15T09:00"


def test_score_memories_last_accessed_resets_recency():
    """Accessing a memory resets its recency clock (Park's approach)."""
    from npc_memory import score_memories

    # Old memory that was recently accessed vs old memory never accessed
    memories = [
        {
            "importance": 0.5,
            "narrative_time": "1347-01-01T10:00",
            "last_accessed": "1347-03-15T09:00",  # accessed 1 hour ago
        },
        {
            "importance": 0.5,
            "narrative_time": "1347-01-01T10:00",
            "last_accessed": "",  # never accessed → falls back to narrative_time (old)
        },
    ]

    scored = score_memories(memories, query_embedding=None, narrative_now="1347-03-15T10:00")

    # The recently-accessed memory should rank higher
    top = scored[0][0]
    assert top["last_accessed"] == "1347-03-15T09:00"


def test_score_memories_falls_back_to_wallclock_without_narrative_now():
    """When narrative_now is empty, falls back to wall-clock (backward compat)."""
    from datetime import datetime, timezone

    from npc_memory import score_memories

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    memories = [
        {"importance": 0.5, "narrative_time": now_str, "last_accessed": ""},
    ]

    # Should not crash with empty narrative_now
    scored = score_memories(memories, query_embedding=None, narrative_now="")
    assert len(scored) == 1
