"""Tests for recall.py and _vectordb.py."""

import re

import pytest

chromadb = pytest.importorskip("chromadb")


# -- Reindex --

def test_reindex_journal(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "event", "--content", "The party entered the ancient temple")
    run("journal.py", "add", sid, "--type", "combat", "--content", "Ambushed by skeleton warriors")
    r = run("recall.py", "reindex", sid)
    assert r.returncode == 0
    assert "REINDEX_COMPLETE: 2 journal entries, 0 dialogues" in r.stdout


def test_reindex_dialogues(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Merchant", "npc")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Merchant", "--content", "I have rare wares")
    r = run("recall.py", "reindex", sid)
    assert r.returncode == 0
    assert "1 dialogues" in r.stdout


def test_reindex_both(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Guard", "npc")
    run("journal.py", "add", sid, "--type", "event", "--content", "Entered the city gates")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Guard", "--content", "State your business")
    r = run("recall.py", "reindex", sid)
    assert r.returncode == 0
    assert "1 journal entries, 1 dialogues" in r.stdout


# -- Search --

def test_search_finds_relevant(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "event", "--content", "The party entered the ancient temple")
    run("journal.py", "add", sid, "--type", "event", "--content", "A merchant sold them potions")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "sacred ruins")
    assert r.returncode == 0
    assert "ancient temple" in r.stdout


def test_search_source_journal(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Elder", "npc")
    run("journal.py", "add", sid, "--type", "event", "--content", "Discovered the lost shrine")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Elder", "--content", "The shrine holds great power")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "shrine", "--source", "journal")
    assert r.returncode == 0
    assert "journal" in r.stdout
    # All results should be from journal only
    for line in r.stdout.strip().split("\n")[2:]:  # skip header + dashes
        if line.strip():
            assert line.strip().startswith("journal")


def test_search_source_dialogues(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Elder", "npc")
    run("journal.py", "add", sid, "--type", "event", "--content", "Discovered the lost shrine")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Elder", "--content", "The shrine holds great power")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "shrine", "--source", "dialogues")
    assert r.returncode == 0
    for line in r.stdout.strip().split("\n")[2:]:
        if line.strip():
            assert line.strip().startswith("dialogues")


def test_search_n_controls_results(run, make_session):
    sid = make_session()
    for i in range(5):
        run("journal.py", "add", sid, "--type", "event", "--content", f"Adventure event number {i}")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "adventure", "--n", "2")
    assert r.returncode == 0
    # Count data rows (skip header + dash separator)
    data_lines = [l for l in r.stdout.strip().split("\n")[2:] if l.strip()]
    assert len(data_lines) == 2


def test_search_no_results(run, make_session):
    sid = make_session()
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "something")
    assert r.returncode == 0
    assert "No results found" in r.stdout


# -- Auto-indexing --

def test_journal_auto_indexes(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "event", "--content", "The dragon attacked the village")
    # Search without reindex -- should find via auto-indexing
    r = run("recall.py", "search", sid, "--query", "dragon attack")
    assert r.returncode == 0
    assert "dragon" in r.stdout


def test_dialogue_auto_indexes(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Wizard", "npc")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Wizard", "--content", "The spell requires moonstone")
    # Search without reindex -- should find via auto-indexing
    r = run("recall.py", "search", sid, "--query", "magical ingredients")
    assert r.returncode == 0
    assert "moonstone" in r.stdout


# -- Error Cases --

def test_no_action_fails(run):
    r = run("recall.py")
    assert r.returncode == 1


def test_search_missing_query_fails(run, make_session):
    sid = make_session()
    r = run("recall.py", "search", sid)
    assert r.returncode == 1


def test_search_missing_session_fails(run):
    r = run("recall.py", "search")
    assert r.returncode == 1


def test_reindex_missing_session_fails(run):
    r = run("recall.py", "reindex")
    assert r.returncode == 1
