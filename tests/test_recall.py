"""Tests for recall.py and _vectordb.py."""

import re

import pytest

chromadb = pytest.importorskip("chromadb")


# -- Reindex --

def test_reindex_timeline(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "The party entered the ancient temple")
    run("timeline.py", "add", sid, "--type", "player_choice", "--content", "I look around cautiously")
    r = run("recall.py", "reindex", sid)
    assert r.returncode == 0
    assert "2 timeline entries, 0 journal entries" in r.stdout


def test_reindex_journal(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "note", "--content", "Player prefers stealth")
    r = run("recall.py", "reindex", sid)
    assert r.returncode == 0
    assert "0 timeline entries, 1 journal entries" in r.stdout


def test_reindex_both(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "Entered the city gates")
    run("journal.py", "add", sid, "--type", "note", "--content", "Player prefers combat")
    r = run("recall.py", "reindex", sid)
    assert r.returncode == 0
    assert "1 timeline entries, 1 journal entries" in r.stdout


# -- Search --

def test_search_finds_relevant(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "The party entered the ancient temple")
    run("timeline.py", "add", sid, "--type", "narration", "--content", "A merchant sold them potions")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "sacred ruins")
    assert r.returncode == 0
    assert "ancient temple" in r.stdout


def test_search_source_timeline(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "Discovered the lost shrine")
    run("journal.py", "add", sid, "--type", "note", "--content", "The shrine holds great power")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "shrine", "--source", "timeline")
    assert r.returncode == 0
    assert "timeline" in r.stdout
    for line in r.stdout.strip().split("\n")[2:]:
        if line.strip():
            assert line.strip().startswith("timeline")


def test_search_source_journal(run, make_session):
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration", "--content", "Discovered the lost shrine")
    run("journal.py", "add", sid, "--type", "note", "--content", "The shrine holds great power")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "shrine", "--source", "journal")
    assert r.returncode == 0
    for line in r.stdout.strip().split("\n")[2:]:
        if line.strip():
            assert line.strip().startswith("journal")


def test_search_n_controls_results(run, make_session):
    """--n limits results when --source is specified."""
    sid = make_session()
    for i in range(5):
        run("timeline.py", "add", sid, "--type", "narration", "--content", f"Adventure event number {i}")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "adventure", "--source", "timeline", "--n", "2")
    assert r.returncode == 0
    data_lines = [l for l in r.stdout.strip().split("\n")[2:] if l.strip()]
    assert len(data_lines) == 2


def test_search_no_results(run, make_session):
    sid = make_session()
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "something")
    assert r.returncode == 0
    assert "No results found" in r.stdout


# -- Hybrid search --

def test_search_keyword_match_surfaces(run, make_session):
    """A keyword match that may not rank high semantically still appears."""
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration",
        "--content", "The merchant sold exotic spices from the eastern lands")
    run("timeline.py", "add", sid, "--type", "narration",
        "--content", "A cold wind blew through the empty streets at night")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "spices")
    assert r.returncode == 0
    assert "spices" in r.stdout


def test_search_no_duplicates(run, make_session):
    """Same entry found by keyword and semantic should appear only once."""
    sid = make_session()
    run("timeline.py", "add", sid, "--type", "narration",
        "--content", "The ancient temple crumbled to dust")
    run("recall.py", "reindex", sid)
    r = run("recall.py", "search", sid, "--query", "ancient temple")
    assert r.returncode == 0
    lines = [l for l in r.stdout.strip().split("\n")[2:] if l.strip()]
    assert len(lines) == 1


def test_reindex_rebuilds_all_sessions(run, make_session):
    """Reindexing one session rebuilds vectors for all sessions."""
    sid1 = make_session()
    sid2 = make_session()
    run("timeline.py", "add", sid1, "--type", "narration", "--content", "First session event")
    run("timeline.py", "add", sid2, "--type", "narration", "--content", "Second session event")
    r = run("recall.py", "reindex", sid1)
    assert r.returncode == 0
    assert "1 timeline entries" in r.stdout
    assert "rebuilt all" in r.stdout
    # Verify second session is still searchable after reindex
    r2 = run("recall.py", "search", sid2, "--query", "second session")
    assert r2.returncode == 0
    assert "Second session" in r2.stdout


# -- Auto-indexing --

def test_journal_auto_indexes(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "note", "--content", "The dragon attacked the village")
    r = run("recall.py", "search", sid, "--query", "dragon attack")
    assert r.returncode == 0
    assert "dragon" in r.stdout


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
