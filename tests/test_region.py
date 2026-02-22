"""Tests for region.py."""

import re


# -- Happy Path --

def test_create_region(run, make_session):
    sid = make_session()
    r = run("region.py", "create", sid, "--name", "Darkwood", "--desc", "A dense forest")
    assert r.returncode == 0
    assert re.search(r"REGION_CREATED: \d+", r.stdout)


def test_view_region(run, make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "Ironforge", "Dwarven city")
    r = run("region.py", "view", rid)
    assert "NAME: Ironforge" in r.stdout
    assert "DESCRIPTION: Dwarven city" in r.stdout


def test_list_regions(run, make_session, make_region):
    sid = make_session()
    make_region(sid, "Town")
    make_region(sid, "Dungeon")
    r = run("region.py", "list", sid)
    assert "Town" in r.stdout
    assert "Dungeon" in r.stdout


def test_update_region_name(run, make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "OldName")
    run("region.py", "update", rid, "--name", "NewName")
    r = run("region.py", "view", rid)
    assert "NAME: NewName" in r.stdout


def test_update_region_desc(run, make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "Place", "Old desc")
    run("region.py", "update", rid, "--desc", "New desc")
    r = run("region.py", "view", rid)
    assert "DESCRIPTION: New desc" in r.stdout


def test_view_shows_npcs(run, make_session, make_region, make_character):
    sid = make_session()
    rid = make_region(sid, "Village")
    make_character(sid, "Guard", "npc", rid)
    r = run("region.py", "view", rid)
    assert "NPCs IN THIS REGION" in r.stdout
    assert "Guard" in r.stdout


def test_view_excludes_pcs(run, make_session, make_region, make_character):
    sid = make_session()
    rid = make_region(sid, "Camp")
    make_character(sid, "Hero", "pc", rid)
    make_character(sid, "Merchant", "npc", rid)
    r = run("region.py", "view", rid)
    assert "Merchant" in r.stdout
    assert "Hero" not in r.stdout


def test_create_without_desc(run, make_session):
    sid = make_session()
    r = run("region.py", "create", sid, "--name", "EmptyPlace")
    assert r.returncode == 0
    assert re.search(r"REGION_CREATED: \d+", r.stdout)


# -- Error Cases --

def test_no_action_fails(run):
    r = run("region.py")
    assert r.returncode == 1


def test_create_missing_session_fails(run):
    r = run("region.py", "create")
    assert r.returncode == 1


def test_create_missing_name_fails(run, make_session):
    sid = make_session()
    r = run("region.py", "create", sid)
    assert r.returncode == 1


def test_view_nonexistent_fails(run):
    r = run("region.py", "view", "9999")
    assert r.returncode == 1
    assert "not found" in r.stderr


# -- Edge Cases --

def test_sql_escaping_in_region_name(run, make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "Dragon's Lair", "It's dangerous")
    r = run("region.py", "view", rid)
    assert "Dragon's Lair" in r.stdout


def test_update_both_name_and_desc(run, make_session, make_region):
    sid = make_session()
    rid = make_region(sid, "Old", "old desc")
    run("region.py", "update", rid, "--name", "New", "--desc", "new desc")
    r = run("region.py", "view", rid)
    assert "NAME: New" in r.stdout
    assert "DESCRIPTION: new desc" in r.stdout
