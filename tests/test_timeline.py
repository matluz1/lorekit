"""Tests for timeline management."""

import re

import pytest

chromadb = pytest.importorskip("chromadb")

from mcp_server import (  # noqa: E402
    recall_search,
    timeline_add,
    timeline_list,
    timeline_search,
)


# -- Happy Path --


def test_add_narration(make_session):
    sid = make_session()
    result = timeline_add(session_id=sid, type="narration", content="The forest grew dark.")
    assert re.search(r"TIMELINE_ADDED: \d+", result)


def test_add_player_choice(make_session):
    sid = make_session()
    result = timeline_add(session_id=sid, type="player_choice", content="I search the room for clues.")
    assert re.search(r"TIMELINE_ADDED: \d+", result)


def test_list_all(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="The gates stood tall.")
    timeline_add(session_id=sid, type="player_choice", content="I approach the gates.")
    result = timeline_list(session_id=sid)
    assert "The gates stood tall." in result
    assert "I approach the gates." in result


def test_list_by_type(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="Rain fell.")
    timeline_add(session_id=sid, type="player_choice", content="I take shelter.")
    result = timeline_list(session_id=sid, type="narration")
    assert "Rain fell." in result
    assert "I take shelter." not in result


def test_list_by_type_player_choice(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="Rain fell.")
    timeline_add(session_id=sid, type="player_choice", content="I take shelter.")
    result = timeline_list(session_id=sid, type="player_choice")
    assert "I take shelter." in result
    assert "Rain fell." not in result


def test_list_last_n(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="First")
    timeline_add(session_id=sid, type="narration", content="Second")
    timeline_add(session_id=sid, type="narration", content="Third")
    result = timeline_list(session_id=sid, last=1)
    assert "Third" in result
    assert "First" not in result


def test_search(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="The prophecy speaks of doom")
    timeline_add(session_id=sid, type="narration", content="The sun was shining")
    result = timeline_search(session_id=sid, query="prophecy")
    assert "prophecy" in result
    assert "sun" not in result


def test_search_case_insensitive(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="The DRAGON awaits")
    result = timeline_search(session_id=sid, query="dragon")
    assert "DRAGON" in result


# -- Auto-indexing --


def test_narration_auto_indexes(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="The dragon attacked the village")
    result = recall_search(session_id=sid, query="dragon attack")
    assert "dragon" in result


def test_player_choice_auto_indexes(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="player_choice", content="I draw my sword and charge at the bandit")
    result = recall_search(session_id=sid, query="draw my sword")
    assert "sword" in result


# -- Validation Errors --


def test_add_invalid_type_fails(make_session):
    sid = make_session()
    result = timeline_add(session_id=sid, type="dialogue", content="X")
    assert "ERROR" in result
