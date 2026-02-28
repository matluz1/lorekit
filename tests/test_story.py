"""Tests for story.py."""

import re


# -- Fixtures --

def _make_story(run, sid, size="oneshot", premise="A test adventure"):
    r = run("story.py", "set", sid, "--size", size, "--premise", premise)
    assert r.returncode == 0
    return sid


def _add_act(run, sid, title, desc="", goal="", event=""):
    args = ["story.py", "add-act", sid, "--title", title]
    if desc:
        args.extend(["--desc", desc])
    if goal:
        args.extend(["--goal", goal])
    if event:
        args.extend(["--event", event])
    r = run(*args)
    assert r.returncode == 0
    return r.stdout.strip().split(": ")[1]


# -- Happy Path --

def test_set_story(run, make_session):
    sid = make_session()
    r = run("story.py", "set", sid, "--size", "oneshot", "--premise", "Heroes save the village")
    assert r.returncode == 0
    assert f"STORY_SET: {sid}" in r.stdout


def test_view_story(run, make_session):
    sid = make_session()
    _make_story(run, sid, "short", "A cursed forest")
    r = run("story.py", "view", sid)
    assert r.returncode == 0
    assert "SIZE: short" in r.stdout
    assert "PREMISE: A cursed forest" in r.stdout
    assert "--- ACTS ---" in r.stdout


def test_add_act(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    r = run("story.py", "add-act", sid, "--title", "The Call", "--desc", "Heroes are summoned",
            "--goal", "Reach the temple", "--event", "The temple collapses")
    assert r.returncode == 0
    assert re.search(r"ACT_ADDED: \d+", r.stdout)


def test_view_act(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    act_id = _add_act(run, sid, "The Call", "Heroes summoned", "Reach temple", "Temple collapses")
    r = run("story.py", "view-act", act_id)
    assert r.returncode == 0
    assert "TITLE: The Call" in r.stdout
    assert "DESCRIPTION: Heroes summoned" in r.stdout
    assert "GOAL: Reach temple" in r.stdout
    assert "EVENT: Temple collapses" in r.stdout
    assert "STATUS: pending" in r.stdout


def test_update_act_title(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    act_id = _add_act(run, sid, "Old Title")
    run("story.py", "update-act", act_id, "--title", "New Title")
    r = run("story.py", "view-act", act_id)
    assert "TITLE: New Title" in r.stdout


def test_update_act_status(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    act_id = _add_act(run, sid, "Act One")
    run("story.py", "update-act", act_id, "--status", "active")
    r = run("story.py", "view-act", act_id)
    assert "STATUS: active" in r.stdout


def test_update_act_multiple_fields(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    act_id = _add_act(run, sid, "Act One")
    r = run("story.py", "update-act", act_id, "--desc", "New desc", "--goal", "New goal", "--event", "New event")
    assert f"ACT_UPDATED: {act_id}" in r.stdout
    r = run("story.py", "view-act", act_id)
    assert "DESCRIPTION: New desc" in r.stdout
    assert "GOAL: New goal" in r.stdout
    assert "EVENT: New event" in r.stdout


def test_advance_acts(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    act1 = _add_act(run, sid, "Act 1")
    _add_act(run, sid, "Act 2")
    run("story.py", "update-act", act1, "--status", "active")
    r = run("story.py", "advance", sid)
    assert r.returncode == 0
    assert "completed act 1, activated act 2" in r.stdout


def test_overwrite_story(run, make_session):
    sid = make_session()
    _make_story(run, sid, "oneshot", "Original premise")
    _make_story(run, sid, "campaign", "New premise")
    r = run("story.py", "view", sid)
    assert "SIZE: campaign" in r.stdout
    assert "PREMISE: New premise" in r.stdout


def test_auto_order(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    _add_act(run, sid, "First")
    _add_act(run, sid, "Second")
    _add_act(run, sid, "Third")
    r = run("story.py", "view", sid)
    lines = r.stdout.split("\n")
    # Find the act rows after the ACTS header
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


def test_advance_last_act(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    act1 = _add_act(run, sid, "Only Act")
    run("story.py", "update-act", act1, "--status", "active")
    r = run("story.py", "advance", sid)
    assert "no remaining acts" in r.stdout


def test_view_shows_acts_in_table(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    act1 = _add_act(run, sid, "Setup")
    _add_act(run, sid, "Climax")
    run("story.py", "update-act", act1, "--status", "active")
    r = run("story.py", "view", sid)
    assert "Setup" in r.stdout
    assert "Climax" in r.stdout
    assert "active" in r.stdout
    assert "pending" in r.stdout


# -- Error Cases --

def test_no_action_fails(run):
    r = run("story.py")
    assert r.returncode == 1


def test_set_missing_session_fails(run):
    r = run("story.py", "set")
    assert r.returncode == 1


def test_set_missing_size_fails(run, make_session):
    sid = make_session()
    r = run("story.py", "set", sid, "--premise", "A premise")
    assert r.returncode == 1


def test_set_missing_premise_fails(run, make_session):
    sid = make_session()
    r = run("story.py", "set", sid, "--size", "oneshot")
    assert r.returncode == 1


def test_view_nonexistent_story_fails(run, make_session):
    sid = make_session()
    r = run("story.py", "view", sid)
    assert r.returncode == 1
    assert "not found" in r.stderr.lower() or "no story" in r.stderr.lower()


def test_view_act_nonexistent_fails(run):
    r = run("story.py", "view-act", "9999")
    assert r.returncode == 1
    assert "not found" in r.stderr.lower()


def test_advance_no_active_act_fails(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    _add_act(run, sid, "Pending Act")
    r = run("story.py", "advance", sid)
    assert r.returncode == 1
    assert "no active" in r.stderr.lower()


def test_add_act_missing_title_fails(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    r = run("story.py", "add-act", sid)
    assert r.returncode == 1


# -- Edge Cases --

def test_special_characters_in_premise(run, make_session):
    sid = make_session()
    premise = "The hero's journey -- a tale of 'fire & ice'"
    _make_story(run, sid, "short", premise)
    r = run("story.py", "view", sid)
    assert premise in r.stdout


def test_minimal_act_title_only(run, make_session):
    sid = make_session()
    _make_story(run, sid)
    act_id = _add_act(run, sid, "Minimal Act")
    r = run("story.py", "view-act", act_id)
    assert "TITLE: Minimal Act" in r.stdout
    assert "DESCRIPTION: " in r.stdout
    assert "GOAL: " in r.stdout
    assert "EVENT: " in r.stdout
