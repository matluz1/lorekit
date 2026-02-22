"""Tests for journal.py."""

import re


# -- Happy Path --

def test_add_entry(run, make_session):
    sid = make_session()
    r = run("journal.py", "add", sid, "--type", "event", "--content", "The party entered the dungeon")
    assert r.returncode == 0
    assert re.search(r"JOURNAL_ADDED: \d+", r.stdout)


def test_list_entries(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "event", "--content", "Entered dungeon")
    run("journal.py", "add", sid, "--type", "combat", "--content", "Fought goblins")
    r = run("journal.py", "list", sid)
    assert "Entered dungeon" in r.stdout
    assert "Fought goblins" in r.stdout


def test_list_filter_by_type(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "event", "--content", "Event entry")
    run("journal.py", "add", sid, "--type", "combat", "--content", "Combat entry")
    r = run("journal.py", "list", sid, "--type", "combat")
    assert "Combat entry" in r.stdout
    assert "Event entry" not in r.stdout


def test_list_last_n(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "note", "--content", "First note")
    run("journal.py", "add", sid, "--type", "note", "--content", "Second note")
    run("journal.py", "add", sid, "--type", "note", "--content", "Third note")
    r = run("journal.py", "list", sid, "--last", "1")
    assert "Third note" in r.stdout
    assert "First note" not in r.stdout


def test_search_entries(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "discovery", "--content", "Found a magical artifact")
    run("journal.py", "add", sid, "--type", "event", "--content", "Talked to the king")
    r = run("journal.py", "search", sid, "--query", "artifact")
    assert "magical artifact" in r.stdout
    assert "king" not in r.stdout


def test_search_case_insensitive(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "event", "--content", "The DRAGON attacked")
    r = run("journal.py", "search", sid, "--query", "dragon")
    assert "DRAGON" in r.stdout


# -- Error Cases --

def test_no_action_fails(run):
    r = run("journal.py")
    assert r.returncode == 1


def test_add_missing_type_fails(run, make_session):
    sid = make_session()
    r = run("journal.py", "add", sid, "--content", "X")
    assert r.returncode == 1


def test_add_missing_content_fails(run, make_session):
    sid = make_session()
    r = run("journal.py", "add", sid, "--type", "event")
    assert r.returncode == 1


# -- Edge Cases --

def test_quotes_in_content(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "npc", "--content", "The innkeeper said 'welcome'")
    r = run("journal.py", "search", sid, "--query", "innkeeper")
    assert "innkeeper" in r.stdout


def test_multiple_types(run, make_session):
    sid = make_session()
    for t in ["event", "combat", "discovery", "npc", "decision", "note"]:
        run("journal.py", "add", sid, "--type", t, "--content", f"Entry of type {t}")
    r = run("journal.py", "list", sid)
    for t in ["event", "combat", "discovery", "npc", "decision", "note"]:
        assert t in r.stdout


def test_list_last_with_type_filter(run, make_session):
    sid = make_session()
    run("journal.py", "add", sid, "--type", "combat", "--content", "Combat 1")
    run("journal.py", "add", sid, "--type", "event", "--content", "Event 1")
    run("journal.py", "add", sid, "--type", "combat", "--content", "Combat 2")
    r = run("journal.py", "list", sid, "--type", "combat", "--last", "1")
    assert "Combat 2" in r.stdout
    assert "Combat 1" not in r.stdout
