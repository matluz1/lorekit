"""Shared pytest fixtures for LoreKit tests."""

import os
import subprocess
import sys

import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")


@pytest.fixture
def db_path(tmp_path):
    """Create a fresh database in a temp directory and return its path."""
    db = str(tmp_path / "game.db")
    env = os.environ.copy()
    env["LOREKIT_DB_DIR"] = str(tmp_path)
    env["LOREKIT_DB"] = db
    env["LOREKIT_CHROMA_DIR"] = str(tmp_path / "chroma")
    subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "init_db.py")],
        env=env,
        check=True,
        capture_output=True,
    )
    return db


@pytest.fixture
def run(db_path):
    """Return a helper that runs a script as a subprocess."""

    def _run(script, *args):
        env = os.environ.copy()
        env["LOREKIT_DB"] = db_path
        env["LOREKIT_CHROMA_DIR"] = str(os.path.join(os.path.dirname(db_path), "chroma"))
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, script), *args],
            env=env,
            capture_output=True,
            text=True,
        )
        return result

    return _run


@pytest.fixture
def make_session(run):
    """Factory that creates a session and returns its ID."""

    def _make(name="Test Campaign", setting="Fantasy World", system="d20 Fantasy"):
        r = run("session.py", "create", "--name", name, "--setting", setting, "--system", system)
        assert r.returncode == 0
        return r.stdout.strip().split(": ")[1]

    return _make


@pytest.fixture
def make_character(run):
    """Factory that creates a character and returns its ID."""

    def _make(session_id, name="Test Hero", char_type="pc", region=None, level="1"):
        args = ["character.py", "create", "--session", session_id, "--name", name, "--type", char_type, "--level", level]
        if region:
            args.extend(["--region", region])
        r = run(*args)
        assert r.returncode == 0
        return r.stdout.strip().split(": ")[1]

    return _make


@pytest.fixture
def make_region(run):
    """Factory that creates a region and returns its ID."""

    def _make(session_id, name="Test Region", desc="A test region"):
        r = run("region.py", "create", session_id, "--name", name, "--desc", desc)
        assert r.returncode == 0
        return r.stdout.strip().split(": ")[1]

    return _make
