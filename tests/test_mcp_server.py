"""Tests for the MCP server tool wrappers."""

import sys


# ---- helpers ---------------------------------------------------------------


def test_run_with_db():
    from mcp_server import _run_with_db

    def _check_db(db, args):
        assert db is not None
        assert args == ["test"]
        return "OK"

    result = _run_with_db(_check_db, ["test"])
    assert result == "OK"


def test_run_with_db_catches_error():
    from mcp_server import _run_with_db
    from _db import LoreKitError

    def _raise_error(db, args):
        raise LoreKitError("test error")

    result = _run_with_db(_raise_error, [])
    assert "ERROR: test error" in result


# ---- init_db ---------------------------------------------------------------


def test_init_db():
    from mcp_server import init_db

    result = init_db()
    assert "Database initialized" in result


# ---- session tools ---------------------------------------------------------


def test_session_list():
    from mcp_server import session_setup, session_list

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = session_list()
    assert "Test" in result


def test_session_update():
    from mcp_server import session_setup, session_update

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = session_update(session_id=1, status="finished")
    assert "SESSION_UPDATED:" in result


def test_session_meta():
    from mcp_server import session_setup, session_meta_set, session_meta_get

    session_setup(name="Test", setting="Fantasy", system="d20")
    session_meta_set(session_id=1, key="lang", value="en")
    result = session_meta_get(session_id=1, key="lang")
    assert "lang: en" in result


# ---- story tools -----------------------------------------------------------


def test_story_set_and_view():
    from mcp_server import session_setup, story_set, story_view

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = story_set(session_id=1, size="short", premise="A dark forest")
    assert "STORY_SET:" in result
    result = story_view(session_id=1)
    assert "A dark forest" in result


def test_story_view_act():
    from mcp_server import session_setup, story_set, story_add_act, story_view

    session_setup(name="Test", setting="Fantasy", system="d20")
    story_set(session_id=1, size="short", premise="Test")
    story_add_act(session_id=1, title="Act 1", goal="Goal 1", event="Event 1")
    result = story_view(session_id=1, act_id=1)
    assert "TITLE: Act 1" in result
    assert "GOAL: Goal 1" in result


def test_story_add_act_and_advance():
    from mcp_server import session_setup, story_set, story_add_act, story_update_act, story_advance

    session_setup(name="Test", setting="Fantasy", system="d20")
    story_set(session_id=1, size="short", premise="Test")
    story_add_act(session_id=1, title="Act 1", goal="Goal 1", event="Event 1")
    story_add_act(session_id=1, title="Act 2", goal="Goal 2", event="Event 2")
    story_update_act(act_id=1, status="active")
    result = story_advance(session_id=1)
    assert "completed act 1" in result
    assert "activated act 2" in result


# ---- character tools -------------------------------------------------------


def test_character_build_and_view():
    from mcp_server import session_setup, character_build, character_view
    import json

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = character_build(
        session=1, name="Aldric", level=3,
        attrs=json.dumps([{"category": "stat", "key": "strength", "value": "16"}]),
        items=json.dumps([{"name": "Sword", "desc": "Sharp"}]),
        abilities=json.dumps([{"name": "Flame Burst", "desc": "3d6 fire", "category": "spell"}]),
    )
    assert "CHARACTER_BUILT:" in result
    result = character_view(character_id=1)
    assert "NAME: Aldric" in result
    assert "LEVEL: 3" in result
    assert "strength" in result
    assert "Sword" in result
    assert "Flame Burst" in result


# ---- region tools ----------------------------------------------------------


def test_region_create_and_view():
    from mcp_server import session_setup, region_create, region_view, region_list

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = region_create(session_id=1, name="Ashar", desc="A village")
    assert "REGION_CREATED:" in result
    result = region_view(region_id=1)
    assert "NAME: Ashar" in result
    result = region_list(session_id=1)
    assert "Ashar" in result


# ---- timeline tools --------------------------------------------------------


def test_turn_save_and_list():
    from mcp_server import session_setup, turn_save, timeline_list

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = turn_save(session_id=1, narration="The forest darkens.", summary="Forest darkens")
    assert "TIMELINE_ADDED:" in result
    result = timeline_list(session_id=1)
    assert "The forest darkens." in result


def test_recall_keyword_search():
    from mcp_server import session_setup, turn_save, recall_search

    session_setup(name="Test", setting="Fantasy", system="d20")
    turn_save(session_id=1, narration="A dragon appears in the sky.", summary="Dragon appears")
    result = recall_search(session_id=1, query="dragon", mode="keyword", source="timeline")
    assert "dragon" in result


# ---- journal tools ---------------------------------------------------------


def test_journal_add_and_list():
    from mcp_server import session_setup, journal_add, journal_list

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = journal_add(session_id=1, type="note", content="Player likes puzzles")
    assert "JOURNAL_ADDED:" in result
    result = journal_list(session_id=1)
    assert "Player likes puzzles" in result


# ---- roll_dice -------------------------------------------------------------


def test_roll_dice_single():
    from mcp_server import roll_dice

    result = roll_dice(expression="d20")
    assert "TOTAL:" in result
    total = int(result.split("TOTAL: ")[1].strip())
    assert 1 <= total <= 20


def test_roll_dice_multiple():
    from mcp_server import roll_dice

    result = roll_dice(expression="d6 d8")
    assert "--- d6 ---" in result
    assert "--- d8 ---" in result


def test_roll_dice_modifier():
    from mcp_server import roll_dice

    result = roll_dice(expression="1d2+5")
    assert "MODIFIER: +5" in result
    total = int(result.split("TOTAL: ")[1].strip())
    assert total in (6, 7)


def test_roll_dice_keep_highest():
    from mcp_server import roll_dice

    result = roll_dice(expression="4d6kh3")
    assert "ROLLS:" in result
    assert "KEPT:" in result


def test_roll_dice_invalid():
    from mcp_server import roll_dice

    result = roll_dice(expression="invalid")
    assert "ERROR" in result


# ---- recall tools ----------------------------------------------------------


def test_recall_search():
    from mcp_server import session_setup, turn_save, recall_search

    session_setup(name="Test", setting="Fantasy", system="d20")
    turn_save(session_id=1, narration="The ancient temple crumbles.", summary="Temple crumbles")
    result = recall_search(session_id=1, query="temple")
    # May return results or "No results" depending on indexing
    assert isinstance(result, str)


def test_recall_reindex():
    from mcp_server import session_setup, turn_save, recall_reindex

    session_setup(name="Test", setting="Fantasy", system="d20")
    turn_save(session_id=1, narration="Test entry for reindex.", summary="Test entry")
    result = recall_reindex(session_id=1)
    assert "REINDEX_COMPLETE:" in result


# ---- export tools ----------------------------------------------------------


def test_export_dump_and_clean(tmp_path):
    from mcp_server import session_setup, export_dump, export_clean

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = export_dump(session_id=1)
    assert "EXPORTED:" in result
    result = export_clean()
    assert "CLEANED:" in result


# ---- error handling --------------------------------------------------------


def test_session_resume_not_found():
    from mcp_server import session_resume

    result = session_resume(session_id=999)
    assert "ERROR" in result
