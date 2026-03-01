"""Tests for timeline management."""

import re

import pytest

chromadb = pytest.importorskip("chromadb")

from mcp_server import (  # noqa: E402
    recall_search,
    timeline_add,
    timeline_list,
    timeline_search,
    timeline_set_summary,
)


# -- Happy Path --


def test_add_narration(make_session):
    sid = make_session()
    result = timeline_add(session_id=sid, type="narration", content="The forest grew dark.")
    assert re.search(r"TIMELINE_ADDED: \d+", result)


def test_add_narration_with_summary(make_session):
    sid = make_session()
    result = timeline_add(
        session_id=sid, type="narration",
        content="The forest grew dark.",
        summary="The forest darkens.",
    )
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


def test_list_by_id(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="Alpha event")
    r2 = timeline_add(session_id=sid, type="narration", content="Beta event")
    tid = int(re.search(r"TIMELINE_ADDED: (\d+)", r2).group(1))
    result = timeline_list(session_id=sid, id=str(tid))
    assert "Beta event" in result
    assert "Alpha event" not in result


def test_list_by_id_range(make_session):
    sid = make_session()
    r1 = timeline_add(session_id=sid, type="narration", content="First event")
    timeline_add(session_id=sid, type="narration", content="Second event")
    r3 = timeline_add(session_id=sid, type="narration", content="Third event")
    timeline_add(session_id=sid, type="narration", content="Fourth event")
    id1 = int(re.search(r"TIMELINE_ADDED: (\d+)", r1).group(1))
    id3 = int(re.search(r"TIMELINE_ADDED: (\d+)", r3).group(1))
    result = timeline_list(session_id=sid, id=f"{id1}-{id3}")
    assert "First event" in result
    assert "Second event" in result
    assert "Third event" in result
    assert "Fourth event" not in result


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


def test_narration_with_summary_auto_indexes(make_session):
    sid = make_session()
    timeline_add(
        session_id=sid, type="narration",
        content="The dragon attacked the village, burning houses and scattering the townsfolk.",
        summary="Dragon attacks the village",
    )
    result = recall_search(session_id=sid, query="dragon attack")
    assert "Dragon attacks" in result


def test_narration_without_summary_skips_vector_indexing(make_session):
    """Narration without summary is not in the vector index (only keyword)."""
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="The dragon attacked the village")
    # Semantic-only query that won't keyword-match
    result = recall_search(session_id=sid, query="fire-breathing beast", source="timeline")
    assert "No results found" in result


def test_player_choice_keyword_search(make_session):
    """Player choices are not in the vector index but found via keyword search."""
    sid = make_session()
    timeline_add(session_id=sid, type="player_choice", content="I draw my sword and charge at the bandit")
    result = recall_search(session_id=sid, query="draw my sword")
    assert "sword" in result


def test_set_summary(make_session):
    """timeline_set_summary updates the summary and indexes the entry."""
    sid = make_session()
    r = timeline_add(session_id=sid, type="narration", content="The old wizard spoke of ancient prophecies.")
    tid = int(re.search(r"TIMELINE_ADDED: (\d+)", r).group(1))
    # No summary yet -- not in vector index
    result = recall_search(session_id=sid, query="wizard prophecy", source="timeline")
    assert "No results found" in result
    # Set summary -- now indexed
    timeline_set_summary(timeline_id=tid, summary="The wizard reveals ancient prophecies")
    result = recall_search(session_id=sid, query="wizard prophecy", source="timeline")
    assert "wizard" in result


# -- Validation Errors --


def test_add_invalid_type_fails(make_session):
    sid = make_session()
    result = timeline_add(session_id=sid, type="dialogue", content="X")
    assert "ERROR" in result
