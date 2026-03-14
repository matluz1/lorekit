"""Tests for checkpoint/turn revert system."""

import os
import sqlite3

import pytest

pytest.importorskip("sqlite_vec")

from mcp_server import (  # noqa: E402
    character_build,
    character_sheet_update,
    character_view,
    journal_add,
    journal_list,
    session_meta_get,
    timeline_list,
    turn_revert,
    turn_save,
)


def _get_db():
    from _db import get_db

    return get_db(os.environ["LOREKIT_DB"])


def _checkpoint_count(session_id):
    db = _get_db()
    count = db.execute("SELECT COUNT(*) FROM checkpoints WHERE session_id = ?", (session_id,)).fetchone()[0]
    db.close()
    return count


# -- Checkpoint creation --


def test_first_turn_save_creates_two_checkpoints(make_session):
    """First turn_save creates checkpoint #0 (pre-game) and #1 (after turn)."""
    sid = make_session()
    turn_save(session_id=sid, narration="Hello world.", summary="Greeting")
    assert _checkpoint_count(sid) == 2


def test_subsequent_turn_save_creates_one_checkpoint(make_session):
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    assert _checkpoint_count(sid) == 3  # #0, #1, #2


# -- Revert restores mutable state --


def test_revert_restores_character_level(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, name="Hero", level=1)
    turn_save(session_id=sid, narration="Adventure begins.", summary="Start")
    # Level up between turns
    character_sheet_update(character_id=cid, level=5)
    turn_save(session_id=sid, narration="Hero is stronger.", summary="Level up")
    # Revert -- should restore level to 1
    turn_revert(session_id=sid)
    view = character_view(character_id=cid)
    assert "LEVEL: 1" in view


def test_revert_restores_character_items(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, name="Hero")
    turn_save(session_id=sid, narration="Start.", summary="Start")
    # Add item between turns
    character_sheet_update(character_id=cid, items='[{"name":"Magic Sword","desc":"Glows"}]')
    turn_save(session_id=sid, narration="Found a sword.", summary="Sword found")
    # Revert -- item should be gone
    turn_revert(session_id=sid)
    view = character_view(character_id=cid)
    assert "Magic Sword" not in view


def test_revert_restores_character_attributes(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, name="Hero")
    turn_save(session_id=sid, narration="Start.", summary="Start")
    # Change attribute between turns
    character_sheet_update(character_id=cid, attrs='[{"category":"combat","key":"hit_points","value":"50"}]')
    turn_save(session_id=sid, narration="Took damage.", summary="Damage")
    # Revert -- attribute should be gone
    turn_revert(session_id=sid)
    view = character_view(character_id=cid)
    assert "50" not in view


# -- Revert removes journal entries --


def test_revert_removes_journal_entries(make_session):
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    journal_add(session_id=sid, type="note", content="Important note")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    # Revert -- journal entry should be gone
    turn_revert(session_id=sid)
    listing = journal_list(session_id=sid)
    assert "Important note" not in listing


# -- Revert restores session metadata --


def test_revert_restores_narrative_time(make_session):
    sid = make_session()
    from mcp_server import time_get, time_set

    time_set(session_id=sid, datetime="1347-03-15T08:00")
    turn_save(session_id=sid, narration="Morning.", summary="Morning")
    # Advance time between turns
    from mcp_server import time_advance

    time_advance(session_id=sid, amount=12, unit="hours")
    turn_save(session_id=sid, narration="Evening.", summary="Evening")
    # Revert -- time should go back to morning
    turn_revert(session_id=sid)
    result = time_get(session_id=sid)
    assert "08:00" in result


# -- Edge cases --


def test_revert_error_no_checkpoints(make_session):
    sid = make_session()
    result = turn_revert(session_id=sid)
    assert "ERROR" in result


def test_revert_twice_works_then_fails(make_session):
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_save(session_id=sid, narration="Turn 3.", summary="T3")
    # First revert: removes turn 3
    result = turn_revert(session_id=sid)
    assert "TURN_REVERTED" in result
    # Second revert: removes turn 2
    result = turn_revert(session_id=sid)
    assert "TURN_REVERTED" in result
    listing = timeline_list(session_id=sid)
    assert "Turn 1." in listing
    assert "Turn 2." not in listing
    assert "Turn 3." not in listing
    # Third revert: removes turn 1 (restores to checkpoint #0)
    result = turn_revert(session_id=sid)
    assert "TURN_REVERTED" in result
    # Fourth revert: should fail (only checkpoint #0 remains)
    result = turn_revert(session_id=sid)
    assert "ERROR" in result


def test_revert_then_save_works(make_session):
    """After reverting, saving a new turn should work normally."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Bad turn.", summary="Bad")
    turn_revert(session_id=sid)
    turn_save(session_id=sid, narration="Good turn.", summary="Good")
    listing = timeline_list(session_id=sid)
    assert "Turn 1." in listing
    assert "Good turn." in listing
    assert "Bad turn." not in listing
