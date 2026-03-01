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


def test_add_player_choice(run, make_session):
    sid = make_session()
    r = run("timeline.py", "add", sid, "--type", "player_choice", "--content", "I search the room for clues.")
    assert r.returncode == 0
    assert re.search(r"TIMELINE_ADDED: \d+", r.stdout)


def test_list_all(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "The gates stood tall.")
    run("timeline.py", "add", sid, "--type", "player_choice", "--content", "I approach the gates.")
    r = run("timeline.py", "list", sid)
    assert "The gates stood tall." in r.stdout
    assert "I approach the gates." in r.stdout


def test_list_by_type(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "Rain fell.")
    run("timeline.py", "add", sid, "--type", "player_choice", "--content", "I take shelter.")
    r = run("timeline.py", "list", sid, "--type", "narration")
    assert "Rain fell." in r.stdout
    assert "I take shelter." not in r.stdout


def test_list_by_type_player_choice(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "Rain fell.")
    run("timeline.py", "add", sid, "--type", "player_choice", "--content", "I take shelter.")
    r = run("timeline.py", "list", sid, "--type", "player_choice")
    assert "I take shelter." in r.stdout
    assert "Rain fell." not in r.stdout


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


def test_player_choice_auto_indexes(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "player_choice", "--content", "I draw my sword and charge at the bandit")
    r = run("recall.py", "search", sid, "--query", "sword charge")
    assert r.returncode == 0
    assert "sword" in r.stdout


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
    r = run("timeline.py", "add", sid, "--type", "dialogue", "--content", "X")
    assert r.returncode == 1


def test_add_missing_content_fails(run, make_session):
    sid = make_session()
    r = run("timeline.py", "add", sid, "--type", "narration")
    assert r.returncode == 1
