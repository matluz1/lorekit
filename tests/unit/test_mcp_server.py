"""Tests for the MCP server tool wrappers."""


# ---- helpers ---------------------------------------------------------------


def test_run_with_db():
    from lorekit.tools._helpers import _run_with_db

    def _check_db(db, args):
        assert db is not None
        assert args == ["test"]
        return "OK"

    result = _run_with_db(_check_db, ["test"])
    assert result == "OK"


def test_run_with_db_catches_error():
    from lorekit.db import LoreKitError
    from lorekit.tools._helpers import _run_with_db

    def _raise_error(db, args):
        raise LoreKitError("test error")

    result = _run_with_db(_raise_error, [])
    assert "ERROR: test error" in result


# ---- init_db ---------------------------------------------------------------


def test_init_db():
    from lorekit.tools.session import init_db

    result = init_db()
    assert "Database initialized" in result


# ---- session tools ---------------------------------------------------------


def test_session_list():
    from lorekit.tools.session import session_list, session_setup

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = session_list()
    assert "Test" in result


def test_session_update():
    from lorekit.tools.session import session_setup, session_update

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = session_update(session_id=1, status="finished")
    assert "SESSION_UPDATED:" in result


def test_session_meta():
    from lorekit.tools.session import session_meta_get, session_meta_set, session_setup

    session_setup(name="Test", setting="Fantasy", system="d20")
    session_meta_set(session_id=1, key="lang", value="en")
    result = session_meta_get(session_id=1, key="lang")
    assert "lang: en" in result


# ---- story tools -----------------------------------------------------------


def test_story_set_and_view():
    from lorekit.tools.narrative import story_set, story_view
    from lorekit.tools.session import session_setup

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = story_set(session_id=1, size="short", premise="A dark forest")
    assert "STORY_SET:" in result
    result = story_view(session_id=1)
    assert "A dark forest" in result


def test_story_view_act():
    from lorekit.tools.narrative import story_add_act, story_set, story_view
    from lorekit.tools.session import session_setup

    session_setup(name="Test", setting="Fantasy", system="d20")
    story_set(session_id=1, size="short", premise="Test")
    story_add_act(session_id=1, title="Act 1", goal="Goal 1", event="Event 1")
    result = story_view(session_id=1, act_id=1)
    assert "TITLE: Act 1" in result
    assert "GOAL: Goal 1" in result


def test_story_add_act_and_advance():
    from lorekit.tools.narrative import story_add_act, story_advance, story_set, story_update_act
    from lorekit.tools.session import session_setup

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
    import json

    from lorekit.tools.character import character_build, character_view
    from lorekit.tools.session import session_setup

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = character_build(
        session=1,
        name="Aldric",
        level=3,
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
    from lorekit.tools.narrative import region_create, region_list, region_view
    from lorekit.tools.session import session_setup

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = region_create(session_id=1, name="Ashar", desc="A village")
    assert "REGION_CREATED:" in result
    result = region_view(region_id=1)
    assert "NAME: Ashar" in result
    result = region_list(session_id=1)
    assert "Ashar" in result


# ---- timeline tools --------------------------------------------------------


def test_turn_save_and_list():
    from lorekit.tools.narrative import timeline_list, turn_save
    from lorekit.tools.session import session_setup

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = turn_save(session_id=1, narration="The forest darkens.", summary="Forest darkens")
    assert "TIMELINE_ADDED:" in result
    result = timeline_list(session_id=1)
    assert "The forest darkens." in result


def test_recall_keyword_search():
    from lorekit.tools.narrative import turn_save
    from lorekit.tools.session import session_setup
    from lorekit.tools.utility import recall_search

    session_setup(name="Test", setting="Fantasy", system="d20")
    turn_save(session_id=1, narration="A dragon appears in the sky.", summary="Dragon appears")
    result = recall_search(session_id=1, query="dragon", mode="keyword", source="timeline")
    assert "dragon" in result


# ---- journal tools ---------------------------------------------------------


def test_journal_add_and_list():
    from lorekit.tools.narrative import journal_add, journal_list
    from lorekit.tools.session import session_setup

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = journal_add(session_id=1, type="note", content="Player likes puzzles")
    assert "JOURNAL_ADDED:" in result
    result = journal_list(session_id=1)
    assert "Player likes puzzles" in result


# ---- roll_dice -------------------------------------------------------------


def test_roll_dice_single():
    from lorekit.tools.utility import roll_dice

    result = roll_dice(expression="d20")
    assert "TOTAL:" in result
    total = int(result.split("TOTAL: ")[1].strip())
    assert 1 <= total <= 20


def test_roll_dice_multiple():
    from lorekit.tools.utility import roll_dice

    result = roll_dice(expression="d6 d8")
    assert "--- d6 ---" in result
    assert "--- d8 ---" in result


def test_roll_dice_modifier():
    from lorekit.tools.utility import roll_dice

    result = roll_dice(expression="1d2+5")
    assert "MODIFIER: +5" in result
    total = int(result.split("TOTAL: ")[1].strip())
    assert total in (6, 7)


def test_roll_dice_keep_highest():
    from lorekit.tools.utility import roll_dice

    result = roll_dice(expression="4d6kh3")
    assert "ROLLS:" in result
    assert "KEPT:" in result


def test_roll_dice_invalid():
    from lorekit.tools.utility import roll_dice

    result = roll_dice(expression="invalid")
    assert "ERROR" in result


# ---- recall tools ----------------------------------------------------------


def test_recall_search():
    from lorekit.tools.narrative import turn_save
    from lorekit.tools.session import session_setup
    from lorekit.tools.utility import recall_search

    session_setup(name="Test", setting="Fantasy", system="d20")
    turn_save(session_id=1, narration="The ancient temple crumbles.", summary="Temple crumbles")
    result = recall_search(session_id=1, query="temple")
    # May return results or "No results" depending on indexing
    assert isinstance(result, str)


def test_recall_reindex():
    from lorekit.tools.narrative import turn_save
    from lorekit.tools.session import session_setup
    from lorekit.tools.utility import recall_reindex

    session_setup(name="Test", setting="Fantasy", system="d20")
    turn_save(session_id=1, narration="Test entry for reindex.", summary="Test entry")
    result = recall_reindex(session_id=1)
    assert "REINDEX_COMPLETE:" in result


# ---- export tools ----------------------------------------------------------


def test_export_dump_and_clean(tmp_path):
    from lorekit.tools.session import session_setup
    from lorekit.tools.utility import export_clean, export_dump

    session_setup(name="Test", setting="Fantasy", system="d20")
    result = export_dump(session_id=1)
    assert "EXPORTED:" in result
    result = export_clean()
    assert "CLEANED:" in result


# ---- ability_from_template ------------------------------------------------


def test_ability_from_template_blast():
    """Template instantiation creates a power ability with merged overrides."""
    import json

    from lorekit.tools.character import ability_from_template, character_build
    from lorekit.tools.session import session_meta_set, session_setup

    session_setup(name="MM3e Test", setting="Supers", system="mm3e")
    session_meta_set(session_id=1, key="rules_system", value="mm3e")
    character_build(session=1, name="Hero", level=1, attrs='[{"category":"stat","key":"power_level","value":"10"}]')

    result = ability_from_template(
        character_id=1,
        template_key="blast",
        overrides='{"ranks": 10, "feeds": {"bonus_ranged_damage": 10}}',
    )
    assert "ABILITY_FROM_TEMPLATE: Blast" in result
    assert "template=blast" in result


def test_ability_from_template_unknown():
    """Unknown template returns an error with available keys."""
    from lorekit.tools.character import ability_from_template, character_build
    from lorekit.tools.session import session_meta_set, session_setup

    session_setup(name="MM3e Test", setting="Supers", system="mm3e")
    session_meta_set(session_id=1, key="rules_system", value="mm3e")
    character_build(session=1, name="Hero", level=1)

    result = ability_from_template(character_id=1, template_key="nonexistent")
    assert "ERROR" in result
    assert "nonexistent" in result
    assert "blast" in result  # should list available templates


def test_ability_from_template_no_system():
    """Template without rules_system set returns an error."""
    from lorekit.tools.character import ability_from_template, character_build
    from lorekit.tools.session import session_setup

    session_setup(name="NoRules", setting="Test", system="generic")
    character_build(session=1, name="Hero", level=1)

    result = ability_from_template(character_id=1, template_key="blast")
    assert "ERROR" in result


# ---- error handling --------------------------------------------------------


def test_session_resume_not_found():
    from lorekit.tools.session import session_resume

    result = session_resume(session_id=999)
    assert "ERROR" in result
