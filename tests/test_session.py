"""Tests for session.py."""

import re


# -- Happy Path --

def test_create_session(run):
    r = run("session.py", "create", "--name", "Quest", "--setting", "Fantasy", "--system", "d20 Fantasy")
    assert r.returncode == 0
    assert re.search(r"SESSION_CREATED: \d+", r.stdout)


def test_view_session(run, make_session):
    sid = make_session("My Campaign", "Dark World", "PF2e")
    r = run("session.py", "view", sid)
    assert r.returncode == 0
    assert "NAME: My Campaign" in r.stdout
    assert "SETTING: Dark World" in r.stdout
    assert "SYSTEM: PF2e" in r.stdout
    assert "STATUS: active" in r.stdout


def test_list_sessions(run, make_session):
    make_session("Camp A")
    make_session("Camp B")
    r = run("session.py", "list")
    assert "Camp A" in r.stdout
    assert "Camp B" in r.stdout


def test_list_filter_status(run, make_session):
    make_session("Active Camp")
    s2 = make_session("Done Camp")
    run("session.py", "update", s2, "--status", "finished")
    r = run("session.py", "list", "--status", "active")
    assert "Active Camp" in r.stdout
    assert "Done Camp" not in r.stdout


def test_update_status(run, make_session):
    sid = make_session()
    run("session.py", "update", sid, "--status", "finished")
    r = run("session.py", "view", sid)
    assert "STATUS: finished" in r.stdout


def test_meta_set_and_get(run, make_session):
    sid = make_session()
    run("session.py", "meta-set", sid, "--key", "difficulty", "--value", "hard")
    r = run("session.py", "meta-get", sid, "--key", "difficulty")
    assert "difficulty: hard" in r.stdout


def test_meta_overwrite(run, make_session):
    sid = make_session()
    run("session.py", "meta-set", sid, "--key", "level", "--value", "5")
    run("session.py", "meta-set", sid, "--key", "level", "--value", "10")
    r = run("session.py", "meta-get", sid, "--key", "level")
    assert "level: 10" in r.stdout


def test_meta_get_all(run, make_session):
    sid = make_session()
    run("session.py", "meta-set", sid, "--key", "a", "--value", "1")
    run("session.py", "meta-set", sid, "--key", "b", "--value", "2")
    r = run("session.py", "meta-get", sid)
    assert "a" in r.stdout
    assert "b" in r.stdout


# -- Error Cases --

def test_no_action_fails(run):
    r = run("session.py")
    assert r.returncode == 1


def test_unknown_action_fails(run):
    r = run("session.py", "foobar")
    assert r.returncode == 1
    assert "ERROR" in r.stderr


def test_create_missing_name_fails(run):
    r = run("session.py", "create", "--setting", "X", "--system", "Y")
    assert r.returncode == 1


def test_create_missing_setting_fails(run):
    r = run("session.py", "create", "--name", "X", "--system", "Y")
    assert r.returncode == 1


def test_create_missing_system_fails(run):
    r = run("session.py", "create", "--name", "X", "--setting", "Y")
    assert r.returncode == 1


def test_view_missing_id_fails(run):
    r = run("session.py", "view")
    assert r.returncode == 1


def test_view_nonexistent_fails(run):
    r = run("session.py", "view", "9999")
    assert r.returncode == 1
    assert "not found" in r.stderr


# -- Edge Cases --

def test_special_characters_in_name(run, make_session):
    sid = make_session("O'Brien's Quest", 'Land of "Quotes"', "d20 Fantasy")
    r = run("session.py", "view", sid)
    assert "O'Brien's Quest" in r.stdout
