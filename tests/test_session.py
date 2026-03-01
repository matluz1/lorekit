"""Tests for session management."""

import re

from mcp_server import (
    session_create,
    session_list,
    session_meta_get,
    session_meta_set,
    session_update,
    session_view,
)


# -- Happy Path --


def test_create_session():
    result = session_create(name="Quest", setting="Fantasy", system="d20 Fantasy")
    assert re.search(r"SESSION_CREATED: \d+", result)


def test_view_session(make_session):
    sid = make_session("My Campaign", "Dark World", "PF2e")
    result = session_view(session_id=sid)
    assert "NAME: My Campaign" in result
    assert "SETTING: Dark World" in result
    assert "SYSTEM: PF2e" in result
    assert "STATUS: active" in result


def test_list_sessions(make_session):
    make_session("Camp A")
    make_session("Camp B")
    result = session_list()
    assert "Camp A" in result
    assert "Camp B" in result


def test_list_filter_status(make_session):
    make_session("Active Camp")
    s2 = make_session("Done Camp")
    session_update(session_id=s2, status="finished")
    result = session_list(status="active")
    assert "Active Camp" in result
    assert "Done Camp" not in result


def test_update_status(make_session):
    sid = make_session()
    session_update(session_id=sid, status="finished")
    result = session_view(session_id=sid)
    assert "STATUS: finished" in result


def test_meta_set_and_get(make_session):
    sid = make_session()
    session_meta_set(session_id=sid, key="difficulty", value="hard")
    result = session_meta_get(session_id=sid, key="difficulty")
    assert "difficulty: hard" in result


def test_meta_overwrite(make_session):
    sid = make_session()
    session_meta_set(session_id=sid, key="level", value="5")
    session_meta_set(session_id=sid, key="level", value="10")
    result = session_meta_get(session_id=sid, key="level")
    assert "level: 10" in result


def test_meta_get_all(make_session):
    sid = make_session()
    session_meta_set(session_id=sid, key="a", value="1")
    session_meta_set(session_id=sid, key="b", value="2")
    result = session_meta_get(session_id=sid)
    assert "a" in result
    assert "b" in result


# -- Error Cases --


def test_view_nonexistent_fails():
    result = session_view(session_id=9999)
    assert "not found" in result


# -- Edge Cases --


def test_special_characters_in_name(make_session):
    sid = make_session("O'Brien's Quest", 'Land of "Quotes"', "d20 Fantasy")
    result = session_view(session_id=sid)
    assert "O'Brien's Quest" in result
