"""Tests for region management."""

import re

from lorekit.tools.narrative import (
    region_create,
    region_list,
    region_update,
    region_view,
)

# -- Happy Path --


def test_create_region(make_session):
    sid = make_session()
    result = region_create(session_id=sid, name="Darkwood", desc="A dense forest")
    assert re.search(r"REGION_CREATED: \d+", result)


def test_view_region(make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "Ironforge", "Dwarven city")
    result = region_view(region_id=rid)
    assert "NAME: Ironforge" in result
    assert "DESCRIPTION: Dwarven city" in result


def test_list_regions(make_session, make_region):
    sid = make_session()
    make_region(sid, "Town")
    make_region(sid, "Dungeon")
    result = region_list(session_id=sid)
    assert "Town" in result
    assert "Dungeon" in result


def test_update_region_name(make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "OldName")
    region_update(region_id=rid, name="NewName")
    result = region_view(region_id=rid)
    assert "NAME: NewName" in result


def test_update_region_desc(make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "Place", "Old desc")
    region_update(region_id=rid, desc="New desc")
    result = region_view(region_id=rid)
    assert "DESCRIPTION: New desc" in result


def test_view_shows_npcs(make_session, make_region, make_character):
    sid = make_session()
    rid = make_region(sid, "Village")
    make_character(sid, "Guard", "npc", rid)
    result = region_view(region_id=rid)
    assert "NPCs IN THIS REGION" in result
    assert "Guard" in result


def test_view_excludes_pcs(make_session, make_region, make_character):
    sid = make_session()
    rid = make_region(sid, "Camp")
    make_character(sid, "Hero", "pc", rid)
    make_character(sid, "Merchant", "npc", rid)
    result = region_view(region_id=rid)
    assert "Merchant" in result
    assert "Hero" not in result


def test_create_without_desc(make_session):
    sid = make_session()
    result = region_create(session_id=sid, name="EmptyPlace")
    assert re.search(r"REGION_CREATED: \d+", result)


# -- Error Cases --


def test_view_nonexistent_fails():
    result = region_view(region_id=9999)
    assert "not found" in result


# -- Edge Cases --


def test_sql_escaping_in_region_name(make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "Dragon's Lair", "It's dangerous")
    result = region_view(region_id=rid)
    assert "Dragon's Lair" in result


def test_update_both_name_and_desc(make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "Old", "old desc")
    region_update(region_id=rid, name="New", desc="new desc")
    result = region_view(region_id=rid)
    assert "NAME: New" in result
    assert "DESCRIPTION: new desc" in result


# -- Hierarchy --


def test_create_with_parent(make_session, make_region):
    sid = make_session()
    parent = make_region(sid, "Kingdom")
    result = region_create(session_id=sid, name="City", parent_id=parent)
    assert "REGION_CREATED" in result


def test_view_shows_parent(make_session, make_region):
    sid = make_session()
    parent = make_region(sid, "Kingdom")
    child_id = int(region_create(session_id=sid, name="City", parent_id=parent).split(": ")[1])
    result = region_view(region_id=child_id)
    assert "PARENT: Kingdom" in result


def test_view_shows_sub_regions(make_session, make_region):
    sid = make_session()
    parent = make_region(sid, "Kingdom")
    region_create(session_id=sid, name="City A", parent_id=parent)
    region_create(session_id=sid, name="City B", parent_id=parent)
    result = region_view(region_id=parent)
    assert "SUB-REGIONS" in result
    assert "City A" in result
    assert "City B" in result


def test_list_shows_parent_column(make_session, make_region):
    sid = make_session()
    parent = make_region(sid, "Kingdom")
    region_create(session_id=sid, name="City", parent_id=parent)
    result = region_list(session_id=sid)
    assert "parent" in result
    assert "Kingdom" in result


def test_update_parent(make_session, make_region):
    sid = make_session()
    r1 = make_region(sid, "Region A")
    r2 = make_region(sid, "Region B")
    region_update(region_id=r2, parent_id=r1)
    result = region_view(region_id=r2)
    assert "PARENT: Region A" in result


def test_view_no_parent_no_parent_line(make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "Standalone")
    result = region_view(region_id=rid)
    assert "PARENT" not in result
