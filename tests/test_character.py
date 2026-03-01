"""Tests for character management."""

import re

from mcp_server import (
    character_create,
    character_get_abilities,
    character_get_attr,
    character_get_items,
    character_list,
    character_remove_item,
    character_set_ability,
    character_set_attr,
    character_set_item,
    character_update,
    character_view,
)
from conftest import _extract_id


# -- Happy Path --


def test_create_pc(make_session):
    sid = make_session()
    result = character_create(session=sid, name="Gandalf", type="pc", level=1)
    assert re.search(r"CHARACTER_CREATED: \d+", result)


def test_create_npc(make_session):
    sid = make_session()
    result = character_create(session=sid, name="Shopkeeper", type="npc", level=1)
    assert re.search(r"CHARACTER_CREATED: \d+", result)


def test_create_with_region(make_session, make_region, make_character):
    sid = make_session()
    rid = make_region(sid, "Tavern")
    cid = make_character(sid, "Barkeep", "npc", rid)
    result = character_view(character_id=cid)
    assert "REGION: Tavern" in result


def test_create_with_level(make_session):
    sid = make_session()
    result = character_create(session=sid, name="Hero", level=5)
    cid = _extract_id(result)
    result = character_view(character_id=cid)
    assert "LEVEL: 5" in result


def test_view_character(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Arwen", "pc")
    result = character_view(character_id=cid)
    assert "NAME: Arwen" in result
    assert "TYPE: pc" in result
    assert "STATUS: alive" in result


def test_list_characters(make_session, make_character):
    sid = make_session()
    make_character(sid, "Alice")
    make_character(sid, "Bob")
    result = character_list(session=sid)
    assert "Alice" in result
    assert "Bob" in result


def test_list_filter_by_type(make_session, make_character):
    sid = make_session()
    make_character(sid, "Hero", "pc")
    make_character(sid, "Villager", "npc")
    result = character_list(session=sid, type="npc")
    assert "Villager" in result
    assert "Hero" not in result


def test_list_filter_by_region(make_session, make_region, make_character):
    sid = make_session()
    rid = make_region(sid, "Forest")
    make_character(sid, "Elf", "npc", rid)
    make_character(sid, "Dwarf", "npc")
    result = character_list(session=sid, region=rid)
    assert "Elf" in result
    assert "Dwarf" not in result


def test_update_level(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    character_update(character_id=cid, level=10)
    result = character_view(character_id=cid)
    assert "LEVEL: 10" in result


def test_update_status(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    character_update(character_id=cid, status="dead")
    result = character_view(character_id=cid)
    assert "STATUS: dead" in result


def test_update_name(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "OldName")
    character_update(character_id=cid, name="NewName")
    result = character_view(character_id=cid)
    assert "NAME: NewName" in result
    assert "OldName" not in result


def test_set_and_get_attribute(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    character_set_attr(character_id=cid, category="stats", key="strength", value="18")
    result = character_get_attr(character_id=cid, category="stats")
    assert "strength" in result
    assert "18" in result


def test_attribute_overwrite(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    character_set_attr(character_id=cid, category="stats", key="str", value="10")
    character_set_attr(character_id=cid, category="stats", key="str", value="20")
    result = character_get_attr(character_id=cid, category="stats")
    assert "20" in result
    assert "10" not in result


def test_get_attr_all_categories(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    character_set_attr(character_id=cid, category="stats", key="str", value="15")
    character_set_attr(character_id=cid, category="saves", key="fort", value="5")
    result = character_get_attr(character_id=cid)
    assert "stats" in result
    assert "saves" in result


def test_set_and_get_item(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    character_set_item(character_id=cid, name="Longsword", desc="A fine blade", qty=1, equipped=1)
    result = character_get_items(character_id=cid)
    assert "Longsword" in result


def test_remove_item(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    result = character_set_item(character_id=cid, name="Potion")
    item_id = _extract_id(result)
    character_remove_item(item_id=item_id)
    result = character_get_items(character_id=cid)
    assert "Potion" not in result


def test_set_and_get_ability(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Wizard")
    character_set_ability(
        character_id=cid, name="Fireball", desc="3d6 fire damage",
        category="spell", uses="3/day",
    )
    result = character_get_abilities(character_id=cid)
    assert "Fireball" in result
    assert "spell" in result


# -- Error Cases --


def test_create_invalid_type_fails(make_session):
    sid = make_session()
    result = character_create(session=sid, name="X", type="monster", level=1)
    assert "pc or npc" in result


def test_view_nonexistent_fails():
    result = character_view(character_id=9999)
    assert "not found" in result


def test_update_no_fields_fails(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    result = character_update(character_id=cid)
    assert "ERROR" in result


# -- Edge Cases --


def test_sql_escaping_in_name(make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "O'Malley")
    result = character_view(character_id=cid)
    assert "O'Malley" in result


def test_default_type_is_pc(make_session):
    sid = make_session()
    result = character_create(session=sid, name="Default", level=1)
    cid = _extract_id(result)
    result = character_view(character_id=cid)
    assert "TYPE: pc" in result
