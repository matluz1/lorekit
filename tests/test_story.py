"""Tests for story management."""

import re

from mcp_server import (
    story_add_act,
    story_advance,
    story_set,
    story_update_act,
    story_view,
    story_view_act,
)


# -- Helpers --


def _extract_id(result):
    m = re.search(r":\s*(\d+)", result)
    assert m, f"Could not extract ID from: {result}"
    return int(m.group(1))


def _make_story(sid, size="oneshot", premise="A test adventure"):
    result = story_set(session_id=sid, size=size, premise=premise)
    assert "STORY_SET:" in result
    return sid


def _add_act(sid, title, desc="", goal="", event=""):
    result = story_add_act(session_id=sid, title=title, desc=desc, goal=goal, event=event)
    return _extract_id(result)


# -- Happy Path --


def test_set_story(make_session):
    sid = make_session()
    result = story_set(session_id=sid, size="oneshot", premise="Heroes save the village")
    assert f"STORY_SET: {sid}" in result


def test_view_story(make_session):
    sid = make_session()
    _make_story(sid, "short", "A cursed forest")
    result = story_view(session_id=sid)
    assert "SIZE: short" in result
    assert "PREMISE: A cursed forest" in result
    assert "--- ACTS ---" in result


def test_add_act(make_session):
    sid = make_session()
    _make_story(sid)
    result = story_add_act(
        session_id=sid, title="The Call", desc="Heroes are summoned",
        goal="Reach the temple", event="The temple collapses",
    )
    assert re.search(r"ACT_ADDED: \d+", result)


def test_view_act(make_session):
    sid = make_session()
    _make_story(sid)
    act_id = _add_act(sid, "The Call", "Heroes summoned", "Reach temple", "Temple collapses")
    result = story_view_act(act_id=act_id)
    assert "TITLE: The Call" in result
    assert "DESCRIPTION: Heroes summoned" in result
    assert "GOAL: Reach temple" in result
    assert "EVENT: Temple collapses" in result
    assert "STATUS: pending" in result


def test_update_act_title(make_session):
    sid = make_session()
    _make_story(sid)
    act_id = _add_act(sid, "Old Title")
    story_update_act(act_id=act_id, title="New Title")
    result = story_view_act(act_id=act_id)
    assert "TITLE: New Title" in result


def test_update_act_status(make_session):
    sid = make_session()
    _make_story(sid)
    act_id = _add_act(sid, "Act One")
    story_update_act(act_id=act_id, status="active")
    result = story_view_act(act_id=act_id)
    assert "STATUS: active" in result


def test_update_act_multiple_fields(make_session):
    sid = make_session()
    _make_story(sid)
    act_id = _add_act(sid, "Act One")
    result = story_update_act(act_id=act_id, desc="New desc", goal="New goal", event="New event")
    assert f"ACT_UPDATED: {act_id}" in result
    result = story_view_act(act_id=act_id)
    assert "DESCRIPTION: New desc" in result
    assert "GOAL: New goal" in result
    assert "EVENT: New event" in result


def test_advance_acts(make_session):
    sid = make_session()
    _make_story(sid)
    act1 = _add_act(sid, "Act 1")
    _add_act(sid, "Act 2")
    story_update_act(act_id=act1, status="active")
    result = story_advance(session_id=sid)
    assert "completed act 1, activated act 2" in result


def test_overwrite_story(make_session):
    sid = make_session()
    _make_story(sid, "oneshot", "Original premise")
    _make_story(sid, "campaign", "New premise")
    result = story_view(session_id=sid)
    assert "SIZE: campaign" in result
    assert "PREMISE: New premise" in result


def test_auto_order(make_session):
    sid = make_session()
    _make_story(sid)
    _add_act(sid, "First")
    _add_act(sid, "Second")
    _add_act(sid, "Third")
    result = story_view(session_id=sid)
    lines = result.split("\n")
    act_lines = []
    in_acts = False
    for line in lines:
        if "--- ACTS ---" in line:
            in_acts = True
            continue
        if in_acts and line.strip() and not line.startswith("-"):
            act_lines.append(line)
    # Skip header row
    if act_lines:
        act_lines = act_lines[1:]
    assert len(act_lines) == 3


def test_advance_last_act(make_session):
    sid = make_session()
    _make_story(sid)
    act1 = _add_act(sid, "Only Act")
    story_update_act(act_id=act1, status="active")
    result = story_advance(session_id=sid)
    assert "no remaining acts" in result


def test_view_shows_acts_in_table(make_session):
    sid = make_session()
    _make_story(sid)
    act1 = _add_act(sid, "Setup")
    _add_act(sid, "Climax")
    story_update_act(act_id=act1, status="active")
    result = story_view(session_id=sid)
    assert "Setup" in result
    assert "Climax" in result
    assert "active" in result
    assert "pending" in result


# -- Error Cases --


def test_view_nonexistent_story_fails(make_session):
    sid = make_session()
    result = story_view(session_id=sid)
    assert "not found" in result.lower() or "no story" in result.lower()


def test_view_act_nonexistent_fails():
    result = story_view_act(act_id=9999)
    assert "not found" in result.lower()


def test_advance_no_active_act_fails(make_session):
    sid = make_session()
    _make_story(sid)
    _add_act(sid, "Pending Act")
    result = story_advance(session_id=sid)
    assert "no active" in result.lower()


# -- Edge Cases --


def test_special_characters_in_premise(make_session):
    sid = make_session()
    premise = "The hero's journey -- a tale of 'fire & ice'"
    _make_story(sid, "short", premise)
    result = story_view(session_id=sid)
    assert premise in result


def test_minimal_act_title_only(make_session):
    sid = make_session()
    _make_story(sid)
    act_id = _add_act(sid, "Minimal Act")
    result = story_view_act(act_id=act_id)
    assert "TITLE: Minimal Act" in result
    assert "DESCRIPTION: " in result
    assert "GOAL: " in result
    assert "EVENT: " in result
