"""Tests for dialogue.py."""

import re


# -- Happy Path --

def test_add_dialogue(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Merchant", "npc")
    r = run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Merchant", "--content", "Welcome to my shop!")
    assert r.returncode == 0
    assert re.search(r"DIALOGUE_ADDED: \d+", r.stdout)


def test_list_dialogue(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Guard", "npc")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Guard", "--content", "Halt!")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Player", "--content", "I mean no harm")
    r = run("dialogue.py", "list", sid, "--npc", npc_id)
    assert "Halt!" in r.stdout
    assert "I mean no harm" in r.stdout


def test_list_last_n(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Sage", "npc")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Sage", "--content", "First line")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Sage", "--content", "Second line")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Sage", "--content", "Third line")
    r = run("dialogue.py", "list", sid, "--npc", npc_id, "--last", "1")
    assert "Third line" in r.stdout
    assert "First line" not in r.stdout


def test_search_dialogue(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Oracle", "npc")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Oracle", "--content", "The prophecy speaks of doom")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Player", "--content", "Tell me more")
    r = run("dialogue.py", "search", sid, "--query", "prophecy")
    assert "prophecy" in r.stdout
    assert "Tell me more" not in r.stdout


def test_search_case_insensitive(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Bard", "npc")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Bard", "--content", "The DRAGON awaits")
    r = run("dialogue.py", "search", sid, "--query", "dragon")
    assert "DRAGON" in r.stdout


# -- Error Cases --

def test_no_action_fails(run):
    r = run("dialogue.py")
    assert r.returncode == 1


def test_add_missing_npc_fails(run, make_session):
    sid = make_session()
    r = run("dialogue.py", "add", sid, "--speaker", "X", "--content", "Y")
    assert r.returncode == 1


def test_add_missing_speaker_fails(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "NPC", "npc")
    r = run("dialogue.py", "add", sid, "--npc", npc_id, "--content", "Y")
    assert r.returncode == 1


def test_add_missing_content_fails(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "NPC", "npc")
    r = run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "X")
    assert r.returncode == 1


def test_list_missing_npc_fails(run, make_session):
    sid = make_session()
    r = run("dialogue.py", "list", sid)
    assert r.returncode == 1


# -- Edge Cases --

def test_quotes_in_content(run, make_session, make_character):
    sid = make_session()
    npc_id = make_character(sid, "Innkeeper", "npc")
    run("dialogue.py", "add", sid, "--npc", npc_id, "--speaker", "Innkeeper", "--content", "He said 'hello' to me")
    r = run("dialogue.py", "list", sid, "--npc", npc_id)
    assert "said" in r.stdout


def test_multiple_npcs_isolated(run, make_session, make_character):
    sid = make_session()
    npc1 = make_character(sid, "NPC1", "npc")
    npc2 = make_character(sid, "NPC2", "npc")
    run("dialogue.py", "add", sid, "--npc", npc1, "--speaker", "NPC1", "--content", "Line from NPC1")
    run("dialogue.py", "add", sid, "--npc", npc2, "--speaker", "NPC2", "--content", "Line from NPC2")
    r = run("dialogue.py", "list", sid, "--npc", npc1)
    assert "Line from NPC1" in r.stdout
    assert "Line from NPC2" not in r.stdout
