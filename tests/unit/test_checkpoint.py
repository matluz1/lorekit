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


def test_revert_then_save_truncates_without_named_saves(make_session):
    """After reverting, saving truncates future checkpoints if no named saves exist."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Bad turn.", summary="Bad")
    # 3 checkpoints: #0, #1, #2
    assert _checkpoint_count(sid) == 3
    turn_revert(session_id=sid)
    # Still 3 checkpoints (cursor moved back, nothing deleted yet)
    assert _checkpoint_count(sid) == 3
    turn_save(session_id=sid, narration="Good turn.", summary="Good")
    # Truncate: #2 deleted, new checkpoint created → 3 checkpoints
    assert _checkpoint_count(sid) == 3
    assert _branch_count(sid) == 1  # no fork
    listing = timeline_list(session_id=sid)
    assert "Turn 1." in listing
    assert "Good turn." in listing
    assert "Bad turn." not in listing


def test_revert_then_save_forks_with_named_saves(make_session):
    """After reverting, saving forks if named saves exist on the old path."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    manual_save(session_id=sid, name="Important Save")
    # Revert past the named save
    turn_revert(session_id=sid, steps=2)
    turn_save(session_id=sid, narration="Alt turn.", summary="Alt")
    # Fork: old branch preserved because it has a named save
    assert _branch_count(sid) == 2
    listing = timeline_list(session_id=sid)
    assert "Alt turn." in listing
    assert "Turn 2." not in listing


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


def test_revert_then_save_truncates_no_error(make_session):
    """Revert then save should succeed (truncate, no fork without named saves)."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_revert(session_id=sid)
    result = turn_save(session_id=sid, narration="Turn 3.", summary="T3")
    assert "ERROR" not in result
    # No fork — truncation happened
    assert _branch_count(sid) == 1


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
    from lorekit.support.checkpoint import reconstruct_state

    snap = reconstruct_state(db, tip)
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


def test_fork_requires_named_save(make_session):
    """Revert + save without named saves should truncate, not fork."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    turn_revert(session_id=sid)
    turn_save(session_id=sid, narration="Alt turn.", summary="Alt")
    assert _branch_count(sid) == 1  # truncated, no fork


def test_fork_with_named_save_preserves_old_data(make_session, make_character):
    """After forking (named save on old path), the old branch's checkpoints still exist."""
    sid = make_session()
    cid = make_character(sid, name="Hero", level=1)
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    character_sheet_update(character_id=cid, level=5)
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    manual_save(session_id=sid, name="Level 5 save")
    # Revert to Turn 1 state
    turn_revert(session_id=sid, steps=2)
    # Fork (named save exists on old path)
    character_sheet_update(character_id=cid, level=10)
    turn_save(session_id=sid, narration="Alt turn.", summary="Alt")
    # Current state should show level 10
    view = character_view(character_id=cid)
    assert "LEVEL: 10" in view
    # Old branch checkpoints are preserved
    assert _branch_count(sid) == 2


def test_revert_past_fork_stays_on_branch(make_session):
    """Reverting past a fork point should stay on the current branch."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    manual_save(session_id=sid, name="Keep this")  # named save so fork happens
    turn_revert(session_id=sid, steps=2)
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


def test_save_load_then_play_truncates_without_named(make_session):
    """Playing after loading truncates if no named saves ahead."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    manual_save(session_id=sid, name="Save Point")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    save_load(session_id=sid, name="Save Point")
    turn_save(session_id=sid, narration="New path.", summary="New")
    assert _branch_count(sid) == 1  # truncated, no fork
    listing = timeline_list(session_id=sid)
    assert "New path." in listing
    assert "Turn 2." not in listing


def test_save_load_then_play_forks_with_named_ahead(make_session):
    """Playing after loading forks if named saves exist ahead."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    manual_save(session_id=sid, name="Early Save")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    manual_save(session_id=sid, name="Late Save")
    save_load(session_id=sid, name="Early Save")
    turn_save(session_id=sid, narration="New path.", summary="New")
    assert _branch_count(sid) == 2  # forked to preserve "Late Save"
    listing = timeline_list(session_id=sid)
    assert "New path." in listing
    assert "Turn 2." not in listing


# -- Compression & Deltas --


def test_snapshots_are_compressed(make_session):
    """Checkpoint snapshots should be stored as compressed BLOB, not TEXT."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    db = _get_db()
    row = db.execute(
        "SELECT typeof(snapshot), snapshot FROM checkpoints WHERE session_id = ? LIMIT 1", (sid,)
    ).fetchone()
    db.close()
    assert row[0] == "blob"
    import zlib

    # Should decompress without error
    zlib.decompress(row[1])


def test_delta_round_trip():
    """compute_delta + apply_delta_forward should reconstruct the new snapshot."""
    from lorekit.support.checkpoint import apply_delta_forward, compute_delta

    old = {
        "characters": [{"id": 1, "name": "Hero", "level": 1}],
        "character_attributes": [{"id": 10, "character_id": 1, "category": "stat", "key": "hp", "value": "50"}],
        "timeline": [{"id": 100, "entry_type": "narration", "content": "Hello"}],
    }
    new = {
        "characters": [{"id": 1, "name": "Hero", "level": 5}],  # modified
        "character_attributes": [],  # removed
        "timeline": [
            {"id": 100, "entry_type": "narration", "content": "Hello"},
            {"id": 101, "entry_type": "narration", "content": "World"},  # added
        ],
    }
    delta = compute_delta(old, new)
    reconstructed = apply_delta_forward(old, delta)

    # Compare by converting to sorted key sets
    for table in new:
        new_keys = {r.get("id") for r in new[table]}
        rec_keys = {r.get("id") for r in reconstructed[table]}
        assert new_keys == rec_keys
    # Check the modification
    hero = [r for r in reconstructed["characters"] if r["id"] == 1][0]
    assert hero["level"] == 5


def test_delta_composite_keys():
    """Delta should work with composite-key tables (character_zone, zone_adjacency)."""
    from lorekit.support.checkpoint import apply_delta_forward, compute_delta

    old = {
        "character_zone": [
            {"encounter_id": 1, "character_id": 1, "zone_id": 1, "team": "ally"},
            {"encounter_id": 1, "character_id": 2, "zone_id": 1, "team": "enemy"},
        ],
        "zone_adjacency": [{"zone_a": 1, "zone_b": 2, "weight": 1}],
    }
    new = {
        "character_zone": [
            {"encounter_id": 1, "character_id": 1, "zone_id": 2, "team": "ally"},  # moved zone
        ],
        "zone_adjacency": [
            {"zone_a": 1, "zone_b": 2, "weight": 1},
            {"zone_a": 2, "zone_b": 3, "weight": 1},  # added
        ],
    }
    delta = compute_delta(old, new)
    reconstructed = apply_delta_forward(old, delta)

    assert len(reconstructed["character_zone"]) == 1
    assert reconstructed["character_zone"][0]["zone_id"] == 2
    assert len(reconstructed["zone_adjacency"]) == 2


def test_delta_composite_keys_after_json_roundtrip():
    """Delta with composite keys must survive JSON serialization (tuples become lists)."""
    import json

    from lorekit.support.checkpoint import apply_delta_forward, compute_delta

    old = {
        "character_zone": [
            {"encounter_id": 1, "character_id": 1, "zone_id": 1, "team": "ally"},
            {"encounter_id": 1, "character_id": 2, "zone_id": 1, "team": "enemy"},
        ],
        "zone_adjacency": [{"zone_a": 1, "zone_b": 2, "weight": 1}],
    }
    new = {
        "character_zone": [
            {"encounter_id": 1, "character_id": 1, "zone_id": 2, "team": "ally"},
        ],
        "zone_adjacency": [
            {"zone_a": 1, "zone_b": 2, "weight": 1},
            {"zone_a": 2, "zone_b": 3, "weight": 1},
        ],
    }
    delta = compute_delta(old, new)
    # Simulate DB round-trip: JSON serialize then deserialize (tuples → lists)
    delta = json.loads(json.dumps(delta))
    reconstructed = apply_delta_forward(old, delta)

    assert len(reconstructed["character_zone"]) == 1
    assert reconstructed["character_zone"][0]["zone_id"] == 2
    assert len(reconstructed["zone_adjacency"]) == 2


def test_reconstruct_state_resolves_deltas(make_session, make_character):
    """reconstruct_state should resolve delta chains correctly."""
    sid = make_session()
    cid = make_character(sid, name="Hero", level=1)
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    # Make small changes each turn so deltas are stored (< 50% of full)
    for i in range(2, 5):
        character_sheet_update(character_id=cid, level=i)
        turn_save(session_id=sid, narration=f"Turn {i}.", summary=f"T{i}")

    # Verify some checkpoints are deltas
    db = _get_db()
    delta_count = db.execute(
        "SELECT COUNT(*) FROM checkpoints WHERE session_id = ? AND is_anchor = 0",
        (sid,),
    ).fetchone()[0]
    anchor_count = db.execute(
        "SELECT COUNT(*) FROM checkpoints WHERE session_id = ? AND is_anchor = 1",
        (sid,),
    ).fetchone()[0]
    # Should have at least one anchor and possibly some deltas
    assert anchor_count >= 1

    # reconstruct_state should work regardless of anchor/delta mix
    from lorekit.support.checkpoint import reconstruct_state

    tip_id = db.execute("SELECT MAX(id) FROM checkpoints WHERE session_id = ?", (sid,)).fetchone()[0]
    snap = reconstruct_state(db, tip_id)
    db.close()
    # Should contain the latest character level
    hero = [c for c in snap["characters"] if c["id"] == cid][0]
    assert hero["level"] == 4


def test_fork_point_is_anchor(make_session):
    """Fork points should be promoted to anchors."""
    sid = make_session()
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    manual_save(session_id=sid, name="Preserve this")  # named save so fork happens
    # Revert then save → fork
    turn_revert(session_id=sid)
    turn_save(session_id=sid, narration="Alt.", summary="Alt")
    # The fork point should be an anchor
    db = _get_db()
    # Fork point is the checkpoint we reverted to (parent of the new branch)
    fork_cp = db.execute(
        "SELECT fork_checkpoint_id FROM checkpoint_branches WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (sid,),
    ).fetchone()[0]
    is_anchor = db.execute("SELECT is_anchor FROM checkpoints WHERE id = ?", (fork_cp,)).fetchone()[0]
    db.close()
    assert is_anchor == 1


def test_revert_advance_with_compressed_deltas(make_session, make_character):
    """Full revert/advance cycle should work with compressed delta checkpoints."""
    sid = make_session()
    cid = make_character(sid, name="Hero", level=1)
    turn_save(session_id=sid, narration="Turn 1.", summary="T1")
    character_sheet_update(character_id=cid, level=5)
    turn_save(session_id=sid, narration="Turn 2.", summary="T2")
    character_sheet_update(character_id=cid, level=10)
    turn_save(session_id=sid, narration="Turn 3.", summary="T3")

    # Revert 2 steps
    turn_revert(session_id=sid, steps=2)
    view = character_view(character_id=cid)
    assert "LEVEL: 1" in view

    # Advance 1 step
    turn_advance(session_id=sid)
    view = character_view(character_id=cid)
    assert "LEVEL: 5" in view

    # Advance 1 more step
    turn_advance(session_id=sid)
    view = character_view(character_id=cid)
    assert "LEVEL: 10" in view
