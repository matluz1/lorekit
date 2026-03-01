"""Tests for journal management."""

import re

from mcp_server import (
    journal_add,
    journal_list,
    journal_search,
)


# -- Happy Path --


def test_add_entry(make_session):
    sid = make_session()
    result = journal_add(session_id=sid, type="event", content="The party entered the dungeon")
    assert re.search(r"JOURNAL_ADDED: \d+", result)


def test_list_entries(make_session):
    sid = make_session()
    journal_add(session_id=sid, type="event", content="Entered dungeon")
    journal_add(session_id=sid, type="combat", content="Fought goblins")
    result = journal_list(session_id=sid)
    assert "Entered dungeon" in result
    assert "Fought goblins" in result


def test_list_filter_by_type(make_session):
    sid = make_session()
    journal_add(session_id=sid, type="event", content="Event entry")
    journal_add(session_id=sid, type="combat", content="Combat entry")
    result = journal_list(session_id=sid, type="combat")
    assert "Combat entry" in result
    assert "Event entry" not in result


def test_list_last_n(make_session):
    sid = make_session()
    journal_add(session_id=sid, type="note", content="First note")
    journal_add(session_id=sid, type="note", content="Second note")
    journal_add(session_id=sid, type="note", content="Third note")
    result = journal_list(session_id=sid, last=1)
    assert "Third note" in result
    assert "First note" not in result


def test_search_entries(make_session):
    sid = make_session()
    journal_add(session_id=sid, type="discovery", content="Found a magical artifact")
    journal_add(session_id=sid, type="event", content="Talked to the king")
    result = journal_search(session_id=sid, query="artifact")
    assert "magical artifact" in result
    assert "king" not in result


def test_search_case_insensitive(make_session):
    sid = make_session()
    journal_add(session_id=sid, type="event", content="The DRAGON attacked")
    result = journal_search(session_id=sid, query="dragon")
    assert "DRAGON" in result


# -- Edge Cases --


def test_quotes_in_content(make_session):
    sid = make_session()
    journal_add(session_id=sid, type="npc", content="The innkeeper said 'welcome'")
    result = journal_search(session_id=sid, query="innkeeper")
    assert "innkeeper" in result


def test_multiple_types(make_session):
    sid = make_session()
    for t in ["event", "combat", "discovery", "npc", "decision", "note"]:
        journal_add(session_id=sid, type=t, content=f"Entry of type {t}")
    result = journal_list(session_id=sid)
    for t in ["event", "combat", "discovery", "npc", "decision", "note"]:
        assert t in result


def test_list_last_with_type_filter(make_session):
    sid = make_session()
    journal_add(session_id=sid, type="combat", content="Combat 1")
    journal_add(session_id=sid, type="event", content="Event 1")
    journal_add(session_id=sid, type="combat", content="Combat 2")
    result = journal_list(session_id=sid, type="combat", last=1)
    assert "Combat 2" in result
    assert "Combat 1" not in result
