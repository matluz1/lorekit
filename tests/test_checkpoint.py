"""Tests for checkpoint/turn undo-redo system with branching and save/load."""

import os
import sqlite3

import pytest

pytest.importorskip("sqlite_vec")

from lorekit.tools.character import character_build, character_sheet_update, character_view  # noqa: E402
from lorekit.tools.narrative import (  # noqa: E402
    journal_add,
    journal_list,
    manual_save,
    save_delete,
    save_list,
    save_load,
    save_rename,
    timeline_list,
    turn_advance,
    turn_revert,
    turn_save,
)
from lorekit.tools.session import session_meta_get  # noqa: E402


def _get_db():
    from lorekit.db import get_db

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
    assert "hit_points" not in view


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
    from lorekit.tools.narrative import time_get, time_set

    time_set(session_id=sid, datetime="1347-03-15T08:00")
    turn_save(session_id=sid, narration="Morning.", summary="Morning")
    # Advance time between turns
    from lorekit.tools.narrative import time_advance

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
    """Revert preserves checkpoints (cursor-based), fails at earliest."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_save(session_id=sid, narration="Turn 3.", summary="T3")
    # 4 checkpoints: #0, #1, #2, #3
    assert _checkpoint_count(sid) == 4
    # First revert: cursor moves back from #3 to #2
    result = turn_revert(session_id=sid)
    assert "TURN_REVERTED" in result
    # Second revert: cursor moves from #2 to #1
    result = turn_revert(session_id=sid)
    assert "TURN_REVERTED" in result
    listing = timeline_list(session_id=sid)
    assert "Turn 1." in listing
    assert "Turn 2." not in listing
    assert "Turn 3." not in listing
    # Checkpoints are preserved (not deleted)
    assert _checkpoint_count(sid) == 4
    # Third revert: cursor moves from #1 to #0
    result = turn_revert(session_id=sid)
    assert "TURN_REVERTED" in result
    # Fourth revert: already at #0, should fail
    result = turn_revert(session_id=sid)
    assert "ERROR" in result


def test_revert_then_save_forks(make_session):
    """After reverting, saving creates a new branch (fork-on-save)."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Bad turn.", summary="Bad")
    # 3 checkpoints: #0, #1, #2
    assert _checkpoint_count(sid) == 3
    turn_revert(session_id=sid)
    # Still 3 checkpoints (cursor moved back, nothing deleted)
    assert _checkpoint_count(sid) == 3
    turn_save(session_id=sid, narration="Good turn.", summary="Good")
    # Fork: old branch preserved, new checkpoint on new branch → 4 checkpoints
    assert _checkpoint_count(sid) == 4
    listing = timeline_list(session_id=sid)
    assert "Turn 1." in listing
    assert "Good turn." in listing
    assert "Bad turn." not in listing


# -- Redo (turn_advance) --


def test_redo_after_revert(make_session):
    """Revert then advance restores the later state."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_revert(session_id=sid)
    listing = timeline_list(session_id=sid)
    assert "Turn 2." not in listing
    # Redo
    result = turn_advance(session_id=sid)
    assert "TURN_ADVANCED" in result
    listing = timeline_list(session_id=sid)
    assert "Turn 2." in listing


def test_redo_at_tip_fails(make_session):
    """Advance without a prior revert should fail."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    result = turn_advance(session_id=sid)
    assert "ERROR" in result


def test_revert_then_save_creates_branch(make_session):
    """Revert then save should fork — not fail or truncate."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_revert(session_id=sid)
    result = turn_save(session_id=sid, narration="Turn 3.", summary="T3")
    assert "ERROR" not in result
    # A new branch should exist
    db = _get_db()
    branches = db.execute("SELECT COUNT(*) FROM checkpoint_branches WHERE session_id = ?", (sid,)).fetchone()[0]
    db.close()
    assert branches == 2


def test_multi_step_redo(make_session):
    """Revert 3, advance 2 — should land at correct intermediate state."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_save(session_id=sid, narration="Turn 3.", summary="T3")
    # Revert 3 steps (back to checkpoint #0)
    turn_revert(session_id=sid, steps=3)
    listing = timeline_list(session_id=sid)
    assert "Turn 1." not in listing
    # Advance 2 steps (to checkpoint #2)
    result = turn_advance(session_id=sid, steps=2)
    assert "TURN_ADVANCED" in result
    listing = timeline_list(session_id=sid)
    assert "Turn 1." in listing
    assert "Turn 2." in listing
    assert "Turn 3." not in listing


def test_cursor_in_session_meta(make_session):
    """Cursor is persisted in session_meta and excluded from snapshots."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    # Cursor should be set
    db = _get_db()
    row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'cursor_checkpoint_id'",
        (sid,),
    ).fetchone()
    assert row is not None
    cursor_val = int(row[0])
    # Cursor should point to the latest checkpoint
    tip = db.execute("SELECT MAX(id) FROM checkpoints WHERE session_id = ?", (sid,)).fetchone()[0]
    assert cursor_val == tip
    # Cursor should NOT appear in any snapshot
    snap_json = db.execute("SELECT snapshot FROM checkpoints WHERE id = ?", (tip,)).fetchone()[0]
    import json

    snap = json.loads(snap_json)
    meta_keys = [m["key"] for m in snap.get("session_meta", [])]
    assert "cursor_checkpoint_id" not in meta_keys
    assert "cursor_branch_id" not in meta_keys
    db.close()


# -- Branching --


def _branch_count(session_id):
    db = _get_db()
    count = db.execute("SELECT COUNT(*) FROM checkpoint_branches WHERE session_id = ?", (session_id,)).fetchone()[0]
    db.close()
    return count


def test_first_save_creates_branch(make_session):
    """First turn_save should create a default branch."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    assert _branch_count(sid) == 1


def test_fork_creates_second_branch(make_session):
    """Revert + save should fork into a second branch."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_revert(session_id=sid)
    turn_save(session_id=sid, narration="Alt turn.", summary="Alt")
    assert _branch_count(sid) == 2


def test_fork_preserves_old_branch_data(make_session, make_character):
    """After forking, the old branch's checkpoints still exist."""
    sid = make_session()
    cid = make_character(sid, name="Hero", level=1)
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    character_sheet_update(character_id=cid, level=5)
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    # Revert to Turn 1 state
    turn_revert(session_id=sid)
    # Fork
    character_sheet_update(character_id=cid, level=10)
    turn_save(session_id=sid, narration="Alt turn.", summary="Alt")
    # Current state should show level 10
    view = character_view(character_id=cid)
    assert "LEVEL: 10" in view
    # Old branch checkpoints are preserved (not deleted)
    assert _checkpoint_count(sid) == 4  # #0, #1, #2 (old), #3 (new branch)


def test_revert_past_fork_stays_on_branch(make_session):
    """Reverting past a fork point should stay on the current branch."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_revert(session_id=sid)
    turn_save(session_id=sid, narration="Alt.", summary="Alt")
    # Now on branch 2 with Alt turn. Revert to checkpoint #0 (pre-game)
    turn_revert(session_id=sid, steps=2)
    # Should still be on branch 2
    db = _get_db()
    row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'cursor_branch_id'",
        (sid,),
    ).fetchone()
    branch_id = int(row[0])
    # Advance should follow branch 2, not branch 1
    turn_advance(session_id=sid, steps=2)
    listing = timeline_list(session_id=sid)
    assert "Alt." in listing
    assert "Turn 2." not in listing
    db.close()


def test_advance_follows_current_branch(make_session):
    """Advance after revert should follow the current branch's checkpoints."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_save(session_id=sid, narration="Turn 3.", summary="T3")
    turn_revert(session_id=sid, steps=2)
    turn_advance(session_id=sid)
    listing = timeline_list(session_id=sid)
    assert "Turn 2." in listing
    assert "Turn 3." not in listing


# -- Save/Load --


def test_manual_save_creates_named_checkpoint(make_session):
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    result = manual_save(session_id=sid, name="Before boss")
    assert "Before boss" in result


def test_manual_save_auto_names(make_session):
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    result = manual_save(session_id=sid)
    assert "Save 1" in result
    result = manual_save(session_id=sid)
    assert "Save 2" in result


def test_save_list_shows_only_named(make_session):
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    manual_save(session_id=sid, name="My Save")
    result = save_list(session_id=sid)
    assert "My Save" in result
    # Auto-saves should not appear
    assert "Turn 1" not in result


def test_save_load_restores_state(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, name="Hero", level=1)
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    manual_save(session_id=sid, name="Early game")
    character_sheet_update(character_id=cid, level=10)
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    # Load the save — should restore level 1
    result = save_load(session_id=sid, name="Early game")
    assert "SAVE_LOADED" in result
    view = character_view(character_id=cid)
    assert "LEVEL: 1" in view


def test_save_load_across_branches(make_session):
    """Loading a save on a different branch should work."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    manual_save(session_id=sid, name="Checkpoint A")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    # Revert and fork
    turn_revert(session_id=sid, steps=2)
    turn_save(session_id=sid, narration="Alt.", summary="Alt")
    # Now on branch 2. Load save from branch 1.
    result = save_load(session_id=sid, name="Checkpoint A")
    assert "SAVE_LOADED" in result
    listing = timeline_list(session_id=sid)
    assert "Turn 1." in listing
    assert "Alt." not in listing


def test_save_rename(make_session):
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    manual_save(session_id=sid, name="Old Name")
    result = save_rename(session_id=sid, old_name="Old Name", new_name="New Name")
    assert "SAVE_RENAMED" in result
    listing = save_list(session_id=sid)
    assert "New Name" in listing
    assert "Old Name" not in listing


def test_save_delete_removes_from_list(make_session):
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    manual_save(session_id=sid, name="Temp Save")
    result = save_delete(session_id=sid, name="Temp Save")
    assert "SAVE_DELETED" in result
    listing = save_list(session_id=sid)
    assert "Temp Save" not in listing


def test_save_delete_preserves_checkpoint(make_session):
    """Deleting a save should preserve the underlying checkpoint for undo."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    count_before = _checkpoint_count(sid)
    manual_save(session_id=sid, name="Temp")
    save_delete(session_id=sid, name="Temp")
    # Checkpoint count should not decrease
    assert _checkpoint_count(sid) >= count_before


def test_save_load_then_play_forks(make_session):
    """Playing after a load should fork automatically."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    manual_save(session_id=sid, name="Save Point")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    save_load(session_id=sid, name="Save Point")
    turn_save(session_id=sid, narration="New path.", summary="New")
    assert _branch_count(sid) == 2
    listing = timeline_list(session_id=sid)
    assert "New path." in listing
    assert "Turn 2." not in listing
