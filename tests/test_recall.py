"""Tests for recall (semantic search)."""

import pytest

chromadb = pytest.importorskip("chromadb")

from mcp_server import (  # noqa: E402
    journal_add,
    recall_reindex,
    recall_search,
    timeline_add,
    timeline_set_summary,
)


# -- Reindex --


def test_reindex_timeline_with_summary(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration",
                 content="The party entered the ancient temple",
                 summary="Party enters temple")
    timeline_add(session_id=sid, type="player_choice", content="I look around cautiously")
    result = recall_reindex(session_id=sid)
    assert "1 timeline entries" in result


def test_reindex_skips_narration_without_summary(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration", content="The party entered the ancient temple")
    result = recall_reindex(session_id=sid)
    assert "0 timeline entries" in result
    assert "1 narrations skipped" in result


def test_reindex_journal(make_session):
    sid = make_session()
    journal_add(session_id=sid, type="note", content="Player prefers stealth")
    result = recall_reindex(session_id=sid)
    assert "0 timeline entries, 1 journal entries" in result


def test_reindex_both(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration",
                 content="Entered the city gates",
                 summary="Party enters the city")
    journal_add(session_id=sid, type="note", content="Player prefers combat")
    result = recall_reindex(session_id=sid)
    assert "1 timeline entries, 1 journal entries" in result


# -- Search --


def test_search_finds_relevant(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration",
                 content="The party entered the ancient temple",
                 summary="Party enters the ancient temple")
    timeline_add(session_id=sid, type="narration",
                 content="A merchant sold them potions",
                 summary="Merchant sells potions")
    recall_reindex(session_id=sid)
    result = recall_search(session_id=sid, query="sacred ruins")
    assert "ancient temple" in result


def test_search_returns_raw_content(make_session):
    """Search results include raw content from SQLite alongside the summary."""
    sid = make_session()
    timeline_add(session_id=sid, type="narration",
                 content="The dragon breathed fire on the village, scattering the townsfolk.",
                 summary="Dragon attacks the village")
    recall_reindex(session_id=sid)
    result = recall_search(session_id=sid, query="dragon attack")
    assert "Dragon attacks the village" in result
    assert "breathed fire" in result


def test_search_source_timeline(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration",
                 content="Discovered the lost shrine",
                 summary="Party discovers the lost shrine")
    journal_add(session_id=sid, type="note", content="The shrine holds great power")
    recall_reindex(session_id=sid)
    result = recall_search(session_id=sid, query="shrine", source="timeline")
    assert "timeline" in result
    for line in result.strip().split("\n")[2:]:
        if line.strip():
            assert line.strip().startswith("timeline")


def test_search_source_journal(make_session):
    sid = make_session()
    timeline_add(session_id=sid, type="narration",
                 content="Discovered the lost shrine",
                 summary="Party discovers the lost shrine")
    journal_add(session_id=sid, type="note", content="The shrine holds great power")
    recall_reindex(session_id=sid)
    result = recall_search(session_id=sid, query="shrine", source="journal")
    for line in result.strip().split("\n")[2:]:
        if line.strip():
            assert line.strip().startswith("journal")


def test_search_n_controls_results(make_session):
    """--n limits results when --source is specified."""
    sid = make_session()
    for i in range(5):
        timeline_add(session_id=sid, type="narration",
                     content=f"Adventure event number {i}",
                     summary=f"Adventure event {i}")
    recall_reindex(session_id=sid)
    result = recall_search(session_id=sid, query="adventure", source="timeline", n=2)
    data_lines = [l for l in result.strip().split("\n")[2:] if l.strip()]
    assert len(data_lines) == 2


def test_search_no_results(make_session):
    sid = make_session()
    recall_reindex(session_id=sid)
    result = recall_search(session_id=sid, query="something")
    assert "No results found" in result


# -- Hybrid search --


def test_search_keyword_match_surfaces(make_session):
    """A keyword match that may not rank high semantically still appears."""
    sid = make_session()
    timeline_add(session_id=sid, type="narration",
                 content="The merchant sold exotic spices from the eastern lands",
                 summary="Merchant sells exotic spices")
    timeline_add(session_id=sid, type="narration",
                 content="A cold wind blew through the empty streets at night",
                 summary="Cold wind in empty streets at night")
    recall_reindex(session_id=sid)
    result = recall_search(session_id=sid, query="spices")
    assert "spices" in result


def test_search_no_duplicates(make_session):
    """Same entry found by keyword and semantic should appear only once."""
    sid = make_session()
    timeline_add(session_id=sid, type="narration",
                 content="The ancient temple crumbled to dust",
                 summary="Ancient temple crumbles")
    recall_reindex(session_id=sid)
    result = recall_search(session_id=sid, query="ancient temple")
    lines = [l for l in result.strip().split("\n")[2:] if l.strip()]
    assert len(lines) == 1


def test_reindex_rebuilds_all_sessions(make_session):
    """Reindexing one session rebuilds vectors for all sessions."""
    sid1 = make_session()
    sid2 = make_session()
    timeline_add(session_id=sid1, type="narration",
                 content="First session event",
                 summary="First session event")
    timeline_add(session_id=sid2, type="narration",
                 content="Second session event",
                 summary="Second session event")
    result = recall_reindex(session_id=sid1)
    assert "1 timeline entries" in result
    assert "rebuilt all" in result
    result2 = recall_search(session_id=sid2, query="second session")
    assert "Second session" in result2


# -- set_summary indexes retroactively --


def test_set_summary_indexes_entry(make_session):
    """Setting a summary on an existing entry indexes it for semantic search."""
    sid = make_session()
    import re
    r = timeline_add(session_id=sid, type="narration",
                     content="The wizard cast a powerful spell that shattered the barrier.")
    tid = int(re.search(r"TIMELINE_ADDED: (\d+)", r).group(1))
    # Not indexed yet
    result = recall_search(session_id=sid, query="wizard spell", source="timeline")
    assert "No results found" in result
    # Set summary
    timeline_set_summary(timeline_id=tid, summary="Wizard shatters the barrier with a spell")
    result = recall_search(session_id=sid, query="wizard spell", source="timeline")
    assert "wizard" in result.lower() or "Wizard" in result


# -- Journal unchanged --


def test_journal_auto_indexes(make_session):
    sid = make_session()
    journal_add(session_id=sid, type="note", content="The dragon attacked the village")
    result = recall_search(session_id=sid, query="dragon attack")
    assert "dragon" in result
