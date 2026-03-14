"""Tests for aggregate wrapper tools."""

import json

# ---- turn_save -------------------------------------------------------------


def test_turn_save_narration_only(make_session):
    from mcp_server import session_meta_get, timeline_list, turn_save

    sid = make_session()
    result = turn_save(session_id=sid, narration="The forest darkens.", summary="Forest gets dark")
    assert "TIMELINE_ADDED:" in result
    assert "META_SET: last_gm_message" in result

    tl = timeline_list(session_id=sid)
    assert "The forest darkens." in tl

    meta = session_meta_get(session_id=sid, key="last_gm_message")
    assert "The forest darkens." in meta


def test_turn_save_player_choice_only(make_session):
    from mcp_server import timeline_list, turn_save

    sid = make_session()
    result = turn_save(session_id=sid, player_choice="I attack the goblin")
    assert "TIMELINE_ADDED:" in result

    tl = timeline_list(session_id=sid)
    assert "I attack the goblin" in tl


def test_turn_save_both(make_session):
    from mcp_server import session_meta_get, timeline_list, turn_save

    sid = make_session()
    result = turn_save(
        session_id=sid,
        narration="A dragon swoops down.",
        summary="Dragon attacks",
        player_choice="I dodge!",
    )
    lines = result.strip().split("\n")
    assert len(lines) == 3
    assert "META_SET: last_gm_message" in result

    tl = timeline_list(session_id=sid)
    assert "A dragon swoops down." in tl
    assert "I dodge!" in tl


def test_turn_save_requires_at_least_one():
    from mcp_server import session_create, turn_save

    session_create(name="Test", setting="Fantasy", system="d20")
    result = turn_save(session_id=1)
    assert "ERROR" in result


# ---- character_build -------------------------------------------------------


def test_character_build_full(make_session):
    from mcp_server import character_build, character_view

    sid = make_session()
    result = character_build(
        session=sid,
        name="Aldric",
        level=3,
        attrs=json.dumps(
            [
                {"category": "stat", "key": "strength", "value": "16"},
                {"category": "stat", "key": "dexterity", "value": "14"},
            ]
        ),
        items=json.dumps(
            [
                {"name": "Longsword", "desc": "A fine blade", "qty": 1, "equipped": 1},
            ]
        ),
        abilities=json.dumps(
            [
                {"name": "Battle Surge", "desc": "Regain HP", "category": "feat", "uses": "1/rest"},
            ]
        ),
    )
    assert "CHARACTER_BUILT:" in result
    assert "attrs=2" in result
    assert "items=1" in result
    assert "abilities=1" in result

    # Verify the character was fully created
    cid = int(result.split(": ")[1].split(" ")[0])
    view = character_view(character_id=cid)
    assert "NAME: Aldric" in view
    assert "LEVEL: 3" in view
    assert "strength" in view
    assert "Longsword" in view
    assert "Battle Surge" in view


def test_character_build_minimal(make_session):
    from mcp_server import character_build

    sid = make_session()
    result = character_build(session=sid, name="Bob", level=1)
    assert "CHARACTER_BUILT:" in result
    assert "attrs=0" in result


def test_character_build_npc_with_region(make_session, make_region):
    from mcp_server import character_build, character_view

    sid = make_session()
    rid = make_region(sid)
    result = character_build(session=sid, name="Elder", level=5, type="npc", region=rid)
    assert "CHARACTER_BUILT:" in result

    cid = int(result.split(": ")[1].split(" ")[0])
    view = character_view(character_id=cid)
    assert "TYPE: npc" in view


def test_character_build_invalid_json():
    from mcp_server import character_build, session_create

    session_create(name="Test", setting="Fantasy", system="d20")
    result = character_build(session=1, name="Bad", level=1, attrs="not json")
    assert "ERROR" in result


# ---- session_setup ---------------------------------------------------------


def test_session_setup_full():
    from mcp_server import region_list, session_meta_get, session_setup, session_view, story_view

    result = session_setup(
        name="Dark Forest",
        setting="dark fantasy",
        system="d20 fantasy",
        meta=json.dumps({"language": "English", "house_rule": "max crit dmg"}),
        story_size="short",
        story_premise="A cursed forest threatens the village",
        acts=json.dumps(
            [
                {"title": "The Call", "goal": "Reach the temple", "event": "Temple collapses"},
                {"title": "The Descent", "goal": "Find the cure", "event": "Boss fight"},
            ]
        ),
        regions=json.dumps(
            [
                {
                    "name": "Village",
                    "desc": "A small village",
                    "children": [
                        {"name": "Market Square", "desc": "The town center"},
                    ],
                },
                {"name": "Dark Forest", "desc": "A cursed forest"},
            ]
        ),
    )
    assert "SESSION_CREATED:" in result
    assert "META_SET: 2 keys" in result
    assert "STORY_SET:" in result
    assert "ACTS_ADDED: 2 (first act set to active)" in result
    assert "REGIONS_CREATED: 3" in result

    # Verify story
    story = story_view(session_id=1)
    assert "The Call" in story
    assert "active" in story

    # Verify metadata
    meta = session_meta_get(session_id=1, key="language")
    assert "English" in meta

    # Verify regions (3: Village, Market Square, Dark Forest)
    regions = region_list(session_id=1)
    assert "Village" in regions
    assert "Market Square" in regions
    assert "Dark Forest" in regions


def test_session_setup_minimal():
    from mcp_server import session_setup, session_view

    result = session_setup(name="Quick", setting="sci-fi", system="2d6")
    assert "SESSION_CREATED:" in result

    view = session_view(session_id=1)
    assert "NAME: Quick" in view
    assert "SETTING: sci-fi" in view


def test_session_setup_invalid_json():
    from mcp_server import session_setup

    result = session_setup(name="Bad", setting="X", system="Y", meta="not json")
    assert "ERROR" in result


# ---- session_resume --------------------------------------------------------


def test_session_resume(make_session, make_character):
    from mcp_server import (
        journal_add,
        region_create,
        session_meta_set,
        session_resume,
        story_add_act,
        story_set,
        story_update_act,
        timeline_add,
    )

    sid = make_session()
    make_character(sid, name="Hero")
    region_create(session_id=sid, name="Town")
    story_set(session_id=sid, size="short", premise="Test premise")
    story_add_act(session_id=sid, title="Act 1", goal="Goal 1")
    story_update_act(act_id=1, status="active")
    timeline_add(session_id=sid, type="narration", content="The adventure begins.")
    session_meta_set(session_id=sid, key="last_gm_message", value="The adventure begins.")
    journal_add(session_id=sid, type="note", content="Test note")

    result = session_resume(session_id=sid)

    assert "=== SESSION ===" in result
    assert "=== METADATA ===" in result
    assert "=== STORY ===" in result
    assert "ACTIVE ACT:" in result
    assert "=== PLAYER CHARACTERS ===" in result
    assert "Hero" in result
    assert "=== REGIONS ===" in result
    assert "Town" in result
    assert "=== RECENT TIMELINE" in result
    assert "The adventure begins." in result
    assert "=== RECENT JOURNAL" in result
    assert "Test note" in result


def test_session_resume_no_story(make_session):
    from mcp_server import session_resume

    sid = make_session()
    result = session_resume(session_id=sid)
    assert "=== SESSION ===" in result
    assert "(no story set)" in result


# ---- character_sheet_update ------------------------------------------------


def test_character_sheet_update_attrs(make_session, make_character):
    from mcp_server import character_sheet_update, character_view

    sid = make_session()
    cid = make_character(sid)
    result = character_sheet_update(
        character_id=cid,
        attrs=json.dumps(
            [
                {"category": "combat", "key": "hp", "value": "25"},
                {"category": "stat", "key": "str", "value": "18"},
            ]
        ),
    )
    assert "ATTRS_SET: 2" in result

    view = character_view(character_id=cid)
    assert "hp" in view
    assert "25" in view


def test_character_sheet_update_level_and_items(make_session, make_character):
    from mcp_server import character_sheet_update, character_view

    sid = make_session()
    cid = make_character(sid)
    result = character_sheet_update(
        character_id=cid,
        level=5,
        items=json.dumps([{"name": "Shield", "desc": "A wooden shield", "qty": 1}]),
    )
    assert "CHARACTER_UPDATED:" in result
    assert "ITEMS_SET: 1" in result

    view = character_view(character_id=cid)
    assert "LEVEL: 5" in view
    assert "Shield" in view


def test_character_sheet_update_remove_items_by_name(make_session, make_character):
    from mcp_server import character_set_item, character_sheet_update, character_view

    sid = make_session()
    cid = make_character(sid)
    character_set_item(character_id=cid, name="Rusty Sword", desc="Old")
    character_set_item(character_id=cid, name="Potion", desc="Healing")

    result = character_sheet_update(
        character_id=cid,
        remove_items=json.dumps(["Rusty Sword"]),
    )
    assert "ITEMS_REMOVED: 1" in result

    view = character_view(character_id=cid)
    assert "Rusty Sword" not in view
    assert "Potion" in view


def test_character_sheet_update_remove_items_by_id(make_session, make_character):
    from mcp_server import character_set_item, character_sheet_update, character_view

    sid = make_session()
    cid = make_character(sid)
    r = character_set_item(character_id=cid, name="Dagger", desc="Small")
    item_id = int(r.split(": ")[1])

    result = character_sheet_update(
        character_id=cid,
        remove_items=json.dumps([item_id]),
    )
    assert "ITEMS_REMOVED: 1" in result

    view = character_view(character_id=cid)
    assert "Dagger" not in view


def test_character_sheet_update_no_changes(make_session, make_character):
    from mcp_server import character_sheet_update

    sid = make_session()
    cid = make_character(sid)
    result = character_sheet_update(character_id=cid)
    assert "NO_CHANGES" in result


def test_character_sheet_update_abilities(make_session, make_character):
    from mcp_server import character_sheet_update, character_view

    sid = make_session()
    cid = make_character(sid)
    result = character_sheet_update(
        character_id=cid,
        abilities=json.dumps(
            [
                {"name": "Flame Bolt", "desc": "3d6 fire", "category": "spell", "uses": "3/day"},
            ]
        ),
    )
    assert "ABILITIES_SET: 1" in result

    view = character_view(character_id=cid)
    assert "Flame Bolt" in view
