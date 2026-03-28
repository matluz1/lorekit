"""Integration tests: NPC checkpoint behaviour.

Verify that turn_revert/turn_advance correctly undoes and restores
NPC memories (npc_memories table) and NPC core identity (npc_core table).
"""

import os

import pytest

pytest.importorskip("sqlite_vec")

from lorekit.rules import resolve_system_path  # noqa: E402
from lorekit.tools.narrative import turn_advance, turn_revert, turn_save  # noqa: E402
from lorekit.tools.npc import npc_memory_add  # noqa: E402
from lorekit.tools.session import session_meta_set  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "../fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


@pytest.fixture(autouse=True)
def _patch_system_path(monkeypatch):
    """Make resolve_system_path find our test fixture for 'test_system'."""
    _real = resolve_system_path

    def _patched(name):
        if name == "test_system":
            return TEST_SYSTEM
        return _real(name)

    monkeypatch.setattr("lorekit.rules.resolve_system_path", _patched)


def _setup_session(make_session):
    sid = make_session()
    session_meta_set(session_id=sid, key="rules_system", value="test_system")
    return sid


def _get_db():
    from lorekit.db import get_db

    return get_db(os.environ["LOREKIT_DB"])


class TestNpcMemoryCheckpoint:
    """Turn revert undoes NPC memories; turn_advance brings them back."""

    def test_revert_removes_memories_advance_restores(self, make_session, make_character):
        sid = _setup_session(make_session)
        npc_id = make_character(sid, name="Aldric", char_type="npc")

        # Initial save (checkpoint #0 + #1)
        turn_save(session_id=sid, narration="Session begins.", summary="Start")

        # Add 2 memories to the NPC
        r1 = npc_memory_add(
            session_id=sid,
            npc_id=npc_id,
            content="The heroes saved the village.",
            importance=0.8,
            memory_type="experience",
            entities="[]",
            narrative_time="",
        )
        assert "NPC_MEMORY_ADDED" in r1

        r2 = npc_memory_add(
            session_id=sid,
            npc_id=npc_id,
            content="The warrior is strong and trustworthy.",
            importance=0.6,
            memory_type="observation",
            entities="[]",
            narrative_time="",
        )
        assert "NPC_MEMORY_ADDED" in r2

        # Verify memories exist before save
        db = _get_db()
        count_before = db.execute(
            "SELECT COUNT(*) FROM npc_memories WHERE npc_id = ? AND session_id = ?",
            (npc_id, sid),
        ).fetchone()[0]
        db.close()
        assert count_before == 2

        # Save the turn (checkpoint with memories)
        turn_save(session_id=sid, narration="NPC recalls events.", summary="Memories added")

        # Revert to previous turn (memories should be gone)
        result = turn_revert(session_id=sid)
        assert "TURN_REVERTED" in result

        db = _get_db()
        count_after_revert = db.execute(
            "SELECT COUNT(*) FROM npc_memories WHERE npc_id = ? AND session_id = ?",
            (npc_id, sid),
        ).fetchone()[0]
        db.close()
        assert count_after_revert == 0, f"Expected 0 memories after revert, found {count_after_revert}"

        # Advance (redo) — memories should come back
        result = turn_advance(session_id=sid)
        assert "TURN_ADVANCED" in result

        db = _get_db()
        count_after_advance = db.execute(
            "SELECT COUNT(*) FROM npc_memories WHERE npc_id = ? AND session_id = ?",
            (npc_id, sid),
        ).fetchone()[0]
        db.close()
        assert count_after_advance == 2, f"Expected 2 memories after advance, found {count_after_advance}"


class TestNpcCoreCheckpoint:
    """Turn revert undoes NPC core identity changes."""

    def test_revert_restores_emotional_state(self, make_session, make_character):
        sid = _setup_session(make_session)
        npc_id = make_character(sid, name="Mira", char_type="npc")

        # Initial save
        turn_save(session_id=sid, narration="Adventure begins.", summary="Start")

        # Insert initial npc_core identity
        db = _get_db()
        db.execute(
            "INSERT INTO npc_core (session_id, npc_id, self_concept, emotional_state) VALUES (?, ?, ?, ?)",
            (sid, npc_id, "A cautious innkeeper", "calm"),
        )
        db.commit()
        db.close()

        # Save the turn with the initial core state
        turn_save(session_id=sid, narration="Mira greets the party.", summary="Greeting")

        # Update emotional_state to a different value
        db = _get_db()
        db.execute(
            "UPDATE npc_core SET emotional_state = ? WHERE session_id = ? AND npc_id = ?",
            ("distressed", sid, npc_id),
        )
        db.commit()
        db.close()

        # Save the turn with the updated core state
        turn_save(session_id=sid, narration="Mira is alarmed by the threat.", summary="Alarmed")

        # Verify updated state before revert
        db = _get_db()
        state_before = db.execute(
            "SELECT emotional_state FROM npc_core WHERE session_id = ? AND npc_id = ?",
            (sid, npc_id),
        ).fetchone()[0]
        db.close()
        assert state_before == "distressed"

        # Revert one turn
        result = turn_revert(session_id=sid)
        assert "TURN_REVERTED" in result

        # emotional_state should be back to "calm"
        db = _get_db()
        state_after = db.execute(
            "SELECT emotional_state FROM npc_core WHERE session_id = ? AND npc_id = ?",
            (sid, npc_id),
        ).fetchone()[0]
        db.close()
        assert state_after == "calm", f"Expected emotional_state='calm' after revert, got '{state_after}'"
