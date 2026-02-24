"""Tests for timeline.py."""

import re

import pytest

chromadb = pytest.importorskip("chromadb")


# -- Happy Path --

def test_add_narration(run, make_session):
    sid = make_session()
    r = run("timeline.py", "add", sid, "--type", "narration", "--content", "The forest grew dark.")
    assert r.returncode == 0
    assert re.search(r"TIMELINE_ADDED: \d+", r.stdout)


def test_add_dialogue(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Merchant", "npc")
    r = run("timeline.py", "add", sid, "--type", "dialogue", "--npc", npc_id, "--speaker", "Merchant", "--content", "Welcome to my shop!")
    assert r.returncode == 0
    assert re.search(r"TIMELINE_ADDED: \d+", r.stdout)


def test_list_all(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Guard", "npc")
    run("timeline.py", "add", sid, "--type", "narration", "--content", "The gates stood tall.")
    run("timeline.py", "add", sid, "--type", "dialogue", "--npc", npc_id, "--speaker", "Guard", "--content", "Halt!")
    r = run("timeline.py", "list", sid)
    assert "The gates stood tall." in r.stdout
    assert "Halt!" in r.stdout


def test_list_by_type(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Guard", "npc")
    run("timeline.py", "add", sid, "--type", "narration", "--content", "Rain fell.")
    run("timeline.py", "add", sid, "--type", "dialogue", "--npc", npc_id, "--speaker", "Guard", "--content", "Who goes there?")
    r = run("timeline.py", "list", sid, "--type", "narration")
    assert "Rain fell." in r.stdout
    assert "Who goes there?" not in r.stdout


def test_list_by_npc(run, make_session, make_character):
    sid = make_session()
    npc1 = make_character(sid, "NPC1", "npc")
    npc2 = make_character(sid, "NPC2", "npc")
    run("timeline.py", "add", sid, "--type", "dialogue", "--npc", npc1, "--speaker", "NPC1", "--content", "Line from NPC1")
    run("timeline.py", "add", sid, "--type", "dialogue", "--npc", npc2, "--speaker", "NPC2", "--content", "Line from NPC2")
    r = run("timeline.py", "list", sid, "--npc", npc1)
    assert "Line from NPC1" in r.stdout
    assert "Line from NPC2" not in r.stdout


def test_list_last_n(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "First")
    run("timeline.py", "add", sid, "--type", "narration", "--content", "Second")
    run("timeline.py", "add", sid, "--type", "narration", "--content", "Third")
    r = run("timeline.py", "list", sid, "--last", "1")
    assert "Third" in r.stdout
    assert "First" not in r.stdout


def test_search(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "The prophecy speaks of doom")
    run("timeline.py", "add", sid, "--type", "narration", "--content", "The sun was shining")
    r = run("timeline.py", "search", sid, "--query", "prophecy")
    assert "prophecy" in r.stdout
    assert "sun" not in r.stdout


def test_search_case_insensitive(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "The DRAGON awaits")
    r = run("timeline.py", "search", sid, "--query", "dragon")
    assert "DRAGON" in r.stdout


# -- Auto-indexing --

def test_narration_auto_indexes(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "The dragon attacked the village")
    r = run("recall.py", "search", sid, "--query", "dragon attack")
    assert r.returncode == 0
    assert "dragon" in r.stdout


def test_dialogue_auto_indexes(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Wizard", "npc")
    run("timeline.py", "add", sid, "--type", "dialogue", "--npc", npc_id, "--speaker", "Wizard", "--content", "The spell requires moonstone")
    r = run("recall.py", "search", sid, "--query", "magical ingredients")
    assert r.returncode == 0
    assert "moonstone" in r.stdout


# -- Validation Errors --

def test_no_action_fails(run):
    r = run("timeline.py")
    assert r.returncode == 1


def test_add_missing_type_fails(run, make_session):
    sid = make_session()
    r = run("timeline.py", "add", sid, "--content", "X")
    assert r.returncode == 1


def test_add_invalid_type_fails(run, make_session):
    sid = make_session()
    r = run("timeline.py", "add", sid, "--type", "event", "--content", "X")
    assert r.returncode == 1


def test_add_dialogue_missing_npc_fails(run, make_session):
    sid = make_session()
    r = run("timeline.py", "add", sid, "--type", "dialogue", "--speaker", "X", "--content", "Y")
    assert r.returncode == 1


def test_add_dialogue_missing_speaker_fails(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "NPC", "npc")
    r = run("timeline.py", "add", sid, "--type", "dialogue", "--npc", npc_id, "--content", "Y")
    assert r.returncode == 1


def test_add_missing_content_fails(run, make_session):
    sid = make_session()
    r = run("timeline.py", "add", sid, "--type", "narration")
    assert r.returncode == 1
