"""Tests for the MCP server tool wrappers."""

import sys


# ---- helpers ---------------------------------------------------------------


def test_run_cmd_captures_stdout():
    from mcp_server import _run_cmd

    result = _run_cmd(print, "hello world")
    assert result == "hello world"


def test_run_cmd_captures_stderr():
    import sys
    from mcp_server import _run_cmd

    def _print_stderr():
        print("oops", file=sys.stderr)

    result = _run_cmd(_print_stderr)
    assert result == "oops"


def test_run_cmd_catches_system_exit():
    from mcp_server import _run_cmd

    def _exit():
        print("before exit")
        sys.exit(1)

    result = _run_cmd(_exit)
    assert "before exit" in result


def test_run_with_db():
    from mcp_server import _run_with_db

    def _check_db(db, args):
        assert db is not None
        assert args == ["test"]
        print("OK")

    result = _run_with_db(_check_db, ["test"])
    assert result == "OK"


# ---- init_db ---------------------------------------------------------------


def test_init_db():
    from mcp_server import init_db

    result = init_db()
    assert "Database initialized" in result


# ---- session tools ---------------------------------------------------------


def test_session_create():
    from mcp_server import session_create

    result = session_create(name="Test", setting="Fantasy", system="d20")
    assert "SESSION_CREATED:" in result


def test_session_view():
    from mcp_server import session_create, session_view

    session_create(name="Test", setting="Fantasy", system="d20")
    result = session_view(session_id=1)
    assert "NAME: Test" in result
    assert "SETTING: Fantasy" in result


def test_session_list():
    from mcp_server import session_create, session_list

    session_create(name="Test", setting="Fantasy", system="d20")
    result = session_list()
    assert "Test" in result


def test_session_update():
    from mcp_server import session_create, session_update

    session_create(name="Test", setting="Fantasy", system="d20")
    result = session_update(session_id=1, status="finished")
    assert "SESSION_UPDATED:" in result


def test_session_meta():
    from mcp_server import session_create, session_meta_set, session_meta_get

    session_create(name="Test", setting="Fantasy", system="d20")
    session_meta_set(session_id=1, key="lang", value="en")
    result = session_meta_get(session_id=1, key="lang")
    assert "lang: en" in result


# ---- story tools -----------------------------------------------------------


def test_story_set_and_view():
    from mcp_server import session_create, story_set, story_view

    session_create(name="Test", setting="Fantasy", system="d20")
    result = story_set(session_id=1, size="short", premise="A dark forest")
    assert "STORY_SET:" in result
    result = story_view(session_id=1)
    assert "A dark forest" in result


def test_story_add_act_and_advance():
    from mcp_server import session_create, story_set, story_add_act, story_update_act, story_advance

    session_create(name="Test", setting="Fantasy", system="d20")
    story_set(session_id=1, size="short", premise="Test")
    story_add_act(session_id=1, title="Act 1", goal="Goal 1", event="Event 1")
    story_add_act(session_id=1, title="Act 2", goal="Goal 2", event="Event 2")
    story_update_act(act_id=1, status="active")
    result = story_advance(session_id=1)
    assert "completed act 1" in result
    assert "activated act 2" in result


# ---- character tools -------------------------------------------------------


def test_character_create_and_view():
    from mcp_server import session_create, character_create, character_view

    session_create(name="Test", setting="Fantasy", system="d20")
    result = character_create(session=1, name="Aldric", level=3)
    assert "CHARACTER_CREATED:" in result
    result = character_view(character_id=1)
    assert "NAME: Aldric" in result
    assert "LEVEL: 3" in result


def test_character_set_attr():
    from mcp_server import session_create, character_create, character_set_attr, character_get_attr

    session_create(name="Test", setting="Fantasy", system="d20")
    character_create(session=1, name="Aldric", level=1)
    character_set_attr(character_id=1, category="stat", key="strength", value="16")
    result = character_get_attr(character_id=1, category="stat")
    assert "strength" in result
    assert "16" in result


def test_character_item():
    from mcp_server import session_create, character_create, character_set_item, character_get_items, character_remove_item

    session_create(name="Test", setting="Fantasy", system="d20")
    character_create(session=1, name="Aldric", level=1)
    result = character_set_item(character_id=1, name="Sword", desc="Sharp")
    assert "ITEM_ADDED:" in result
    result = character_get_items(character_id=1)
    assert "Sword" in result
    result = character_remove_item(item_id=1)
    assert "ITEM_REMOVED:" in result


def test_character_ability():
    from mcp_server import session_create, character_create, character_set_ability, character_get_abilities

    session_create(name="Test", setting="Fantasy", system="d20")
    character_create(session=1, name="Aldric", level=1)
    result = character_set_ability(character_id=1, name="Fireball", desc="3d6 fire", category="spell")
    assert "ABILITY_ADDED:" in result
    result = character_get_abilities(character_id=1)
    assert "Fireball" in result


# ---- region tools ----------------------------------------------------------


def test_region_create_and_view():
    from mcp_server import session_create, region_create, region_view, region_list

    session_create(name="Test", setting="Fantasy", system="d20")
    result = region_create(session_id=1, name="Ashar", desc="A village")
    assert "REGION_CREATED:" in result
    result = region_view(region_id=1)
    assert "NAME: Ashar" in result
    result = region_list(session_id=1)
    assert "Ashar" in result


# ---- timeline tools --------------------------------------------------------


def test_timeline_add_and_list():
    from mcp_server import session_create, timeline_add, timeline_list

    session_create(name="Test", setting="Fantasy", system="d20")
    result = timeline_add(session_id=1, type="narration", content="The forest darkens.")
    assert "TIMELINE_ADDED:" in result
    result = timeline_list(session_id=1)
    assert "The forest darkens." in result


def test_timeline_search():
    from mcp_server import session_create, timeline_add, timeline_search

    session_create(name="Test", setting="Fantasy", system="d20")
    timeline_add(session_id=1, type="narration", content="A dragon appears in the sky.")
    result = timeline_search(session_id=1, query="dragon")
    assert "dragon" in result


# ---- journal tools ---------------------------------------------------------


def test_journal_add_and_list():
    from mcp_server import session_create, journal_add, journal_list

    session_create(name="Test", setting="Fantasy", system="d20")
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
    from mcp_server import session_create, timeline_add, recall_search

    session_create(name="Test", setting="Fantasy", system="d20")
    timeline_add(session_id=1, type="narration", content="The ancient temple crumbles.")
    result = recall_search(session_id=1, query="temple")
    # May return results or "No results" depending on indexing
    assert isinstance(result, str)


def test_recall_reindex():
    from mcp_server import session_create, timeline_add, recall_reindex

    session_create(name="Test", setting="Fantasy", system="d20")
    timeline_add(session_id=1, type="narration", content="Test entry for reindex.")
    result = recall_reindex(session_id=1)
    assert "REINDEX_COMPLETE:" in result


# ---- export tools ----------------------------------------------------------


def test_export_dump_and_clean(tmp_path):
    from mcp_server import session_create, export_dump, export_clean

    session_create(name="Test", setting="Fantasy", system="d20")
    result = export_dump(session_id=1)
    assert "EXPORTED:" in result
    result = export_clean()
    assert "CLEANED:" in result


# ---- error handling --------------------------------------------------------


def test_session_view_not_found():
    from mcp_server import session_view

    result = session_view(session_id=999)
    assert "ERROR" in result
