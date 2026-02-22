"""Tests for character.py."""

import re


# -- Happy Path --

def test_create_pc(run, make_session):
    sid = make_session()
    r = run("character.py", "create", "--session", sid, "--name", "Gandalf", "--type", "pc")
    assert r.returncode == 0
    assert re.search(r"CHARACTER_CREATED: \d+", r.stdout)


def test_create_npc(run, make_session):
    sid = make_session()
    r = run("character.py", "create", "--session", sid, "--name", "Shopkeeper", "--type", "npc")
    assert r.returncode == 0
    assert re.search(r"CHARACTER_CREATED: \d+", r.stdout)


def test_create_with_region(run, make_session, make_region, make_character):
    sid = make_session()
    rid = make_region(sid, "Tavern")
    cid = make_character(sid, "Barkeep", "npc", rid)
    r = run("character.py", "view", cid)
    assert "REGION: Tavern" in r.stdout


def test_create_with_level(run, make_session):
    sid = make_session()
    r = run("character.py", "create", "--session", sid, "--name", "Hero", "--level", "5")
    cid = r.stdout.strip().split(": ")[1]
    r = run("character.py", "view", cid)
    assert "LEVEL: 5" in r.stdout


def test_view_character(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Arwen", "pc")
    r = run("character.py", "view", cid)
    assert "NAME: Arwen" in r.stdout
    assert "TYPE: pc" in r.stdout
    assert "STATUS: alive" in r.stdout


def test_list_characters(run, make_session, make_character):
    sid = make_session()
    make_character(sid, "Alice")
    make_character(sid, "Bob")
    r = run("character.py", "list", "--session", sid)
    assert "Alice" in r.stdout
    assert "Bob" in r.stdout


def test_list_filter_by_type(run, make_session, make_character):
    sid = make_session()
    make_character(sid, "Hero", "pc")
    make_character(sid, "Villager", "npc")
    r = run("character.py", "list", "--session", sid, "--type", "npc")
    assert "Villager" in r.stdout
    assert "Hero" not in r.stdout


def test_list_filter_by_region(run, make_session, make_region, make_character):
    sid = make_session()
    rid = make_region(sid, "Forest")
    make_character(sid, "Elf", "npc", rid)
    make_character(sid, "Dwarf", "npc")
    r = run("character.py", "list", "--session", sid, "--region", rid)
    assert "Elf" in r.stdout
    assert "Dwarf" not in r.stdout


def test_update_level(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    run("character.py", "update", cid, "--level", "10")
    r = run("character.py", "view", cid)
    assert "LEVEL: 10" in r.stdout


def test_update_status(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    run("character.py", "update", cid, "--status", "dead")
    r = run("character.py", "view", cid)
    assert "STATUS: dead" in r.stdout


def test_update_name(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "OldName")
    run("character.py", "update", cid, "--name", "NewName")
    r = run("character.py", "view", cid)
    assert "NAME: NewName" in r.stdout
    assert "OldName" not in r.stdout


def test_set_and_get_attribute(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    run("character.py", "set-attr", cid, "--category", "stats", "--key", "strength", "--value", "18")
    r = run("character.py", "get-attr", cid, "--category", "stats")
    assert "strength" in r.stdout
    assert "18" in r.stdout


def test_attribute_overwrite(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    run("character.py", "set-attr", cid, "--category", "stats", "--key", "str", "--value", "10")
    run("character.py", "set-attr", cid, "--category", "stats", "--key", "str", "--value", "20")
    r = run("character.py", "get-attr", cid, "--category", "stats")
    assert "20" in r.stdout
    assert "10" not in r.stdout


def test_get_attr_all_categories(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    run("character.py", "set-attr", cid, "--category", "stats", "--key", "str", "--value", "15")
    run("character.py", "set-attr", cid, "--category", "saves", "--key", "fort", "--value", "5")
    r = run("character.py", "get-attr", cid)
    assert "stats" in r.stdout
    assert "saves" in r.stdout


def test_set_and_get_item(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    run("character.py", "set-item", cid, "--name", "Longsword", "--desc", "A fine blade", "--qty", "1", "--equipped", "1")
    r = run("character.py", "get-items", cid)
    assert "Longsword" in r.stdout


def test_remove_item(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    r = run("character.py", "set-item", cid, "--name", "Potion")
    item_id = r.stdout.strip().split(": ")[1]
    run("character.py", "remove-item", item_id)
    r = run("character.py", "get-items", cid)
    assert "Potion" not in r.stdout


def test_set_and_get_ability(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Wizard")
    run("character.py", "set-ability", cid, "--name", "Fireball", "--desc", "3d6 fire damage", "--category", "spell", "--uses", "3/day")
    r = run("character.py", "get-abilities", cid)
    assert "Fireball" in r.stdout
    assert "spell" in r.stdout


# -- Error Cases --

def test_no_action_fails(run):
    r = run("character.py")
    assert r.returncode == 1


def test_create_missing_session_fails(run):
    r = run("character.py", "create", "--name", "X")
    assert r.returncode == 1


def test_create_missing_name_fails(run, make_session):
    sid = make_session()
    r = run("character.py", "create", "--session", sid)
    assert r.returncode == 1


def test_create_invalid_type_fails(run, make_session):
    sid = make_session()
    r = run("character.py", "create", "--session", sid, "--name", "X", "--type", "monster")
    assert r.returncode == 1
    assert "pc or npc" in r.stderr


def test_view_missing_id_fails(run):
    r = run("character.py", "view")
    assert r.returncode == 1


def test_view_nonexistent_fails(run):
    r = run("character.py", "view", "9999")
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_list_missing_session_fails(run):
    r = run("character.py", "list")
    assert r.returncode == 1


def test_update_no_fields_fails(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "Hero")
    r = run("character.py", "update", cid)
    assert r.returncode == 1


# -- Edge Cases --

def test_sql_escaping_in_name(run, make_session, make_character):
    sid = make_session()
    cid = make_character(sid, "O'Malley")
    r = run("character.py", "view", cid)
    assert "O'Malley" in r.stdout


def test_default_type_is_pc(run, make_session):
    sid = make_session()
    r = run("character.py", "create", "--session", sid, "--name", "Default")
    cid = r.stdout.strip().split(": ")[1]
    r = run("character.py", "view", cid)
    assert "TYPE: pc" in r.stdout


def test_default_level_is_one(run, make_session):
    sid = make_session()
    r = run("character.py", "create", "--session", sid, "--name", "Newbie")
    cid = r.stdout.strip().split(": ")[1]
    r = run("character.py", "view", cid)
    assert "LEVEL: 1" in r.stdout
