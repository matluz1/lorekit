"""Tests for checkpoint revert/advance skipping auto-checkpoints."""

import os

import pytest

pytest.importorskip("sqlite_vec")

from lorekit.server import (  # noqa: E402
    turn_advance,
    turn_revert,
    turn_save,
)


def _get_db():
    from lorekit.db import get_db

    return get_db(os.environ["LOREKIT_DB"])


def _checkpoint_rows(session_id):
    """Return all checkpoints as (id, kind) tuples."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, kind FROM checkpoints WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    db.close()
    return [(r[0], r[1]) for r in rows]


def _insert_auto_checkpoint(session_id):
    """Insert a kind='auto' checkpoint between turns to simulate combat auto-saves."""
    from lorekit.support.checkpoint import create_checkpoint

    db = _get_db()
    cp_id = create_checkpoint(db, session_id, force=True, kind="auto")
    db.close()
    return cp_id


class TestRevertSkipsAuto:
    def test_revert_jumps_over_auto_checkpoints(self, make_session):
        """Reverting 1 step should jump to the previous turn, not the auto-checkpoint."""
        sid = make_session()
        turn_save(session_id=sid, narration="Turn 1.", summary="T1")
        # Insert auto-checkpoint between turns
        _insert_auto_checkpoint(sid)
        turn_save(session_id=sid, narration="Turn 2.", summary="T2")

        rows = _checkpoint_rows(sid)
        # Should have: #0 (turn), #1 (turn), auto, #2 (turn)
        kinds = [r[1] for r in rows]
        assert "auto" in kinds
        assert kinds.count("turn") >= 3  # #0, turn1, turn2

        result = turn_revert(session_id=sid)
        assert "TURN_REVERTED" in result

        # Should be at Turn 1 state, not at the auto-checkpoint
        from lorekit.server import timeline_list

        listing = timeline_list(session_id=sid)
        assert "Turn 1." in listing
        assert "Turn 2." not in listing

    def test_revert_cleans_up_auto_between_turns(self, make_session):
        """Auto-checkpoints between the old and new cursor positions are cleaned up."""
        sid = make_session()
        turn_save(session_id=sid, narration="Turn 1.", summary="T1")
        auto_id = _insert_auto_checkpoint(sid)
        turn_save(session_id=sid, narration="Turn 2.", summary="T2")

        turn_revert(session_id=sid)

        # The auto-checkpoint should be deleted
        db = _get_db()
        row = db.execute("SELECT id FROM checkpoints WHERE id = ?", (auto_id,)).fetchone()
        db.close()
        assert row is None


class TestAdvanceSkipsAuto:
    def test_advance_jumps_over_auto_checkpoints(self, make_session):
        """Advancing 1 step after revert should jump to the next turn, not auto."""
        sid = make_session()
        turn_save(session_id=sid, narration="Turn 1.", summary="T1")
        turn_save(session_id=sid, narration="Turn 2.", summary="T2")
        # Insert auto-checkpoint after Turn 2
        _insert_auto_checkpoint(sid)
        turn_save(session_id=sid, narration="Turn 3.", summary="T3")

        # Revert 2 steps (to Turn 1)
        turn_revert(session_id=sid, steps=2)

        # Advance 1 step — should land on Turn 2, not auto
        result = turn_advance(session_id=sid)
        assert "TURN_ADVANCED" in result

        from lorekit.server import timeline_list

        listing = timeline_list(session_id=sid)
        assert "Turn 1." in listing
        assert "Turn 2." in listing
        assert "Turn 3." not in listing

    def test_multi_step_revert_with_autos(self, make_session):
        """Multi-step revert counts only turn checkpoints."""
        sid = make_session()
        turn_save(session_id=sid, narration="Turn 1.", summary="T1")
        _insert_auto_checkpoint(sid)
        turn_save(session_id=sid, narration="Turn 2.", summary="T2")
        _insert_auto_checkpoint(sid)
        _insert_auto_checkpoint(sid)
        turn_save(session_id=sid, narration="Turn 3.", summary="T3")

        # Revert 2 steps — should go from Turn 3 to Turn 1
        result = turn_revert(session_id=sid, steps=2)
        assert "TURN_REVERTED" in result

        from lorekit.server import timeline_list

        listing = timeline_list(session_id=sid)
        assert "Turn 1." in listing
        assert "Turn 2." not in listing
        assert "Turn 3." not in listing
