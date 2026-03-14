"""Shared pytest fixtures for LoreKit tests."""

import os
import re
import sys

import pytest

# Allow imports from project root and core/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "core"))


def pytest_configure(config):
    """Warn about system packs that ship without a test_config.json."""
    systems_dir = os.path.join(ROOT, "systems")
    if not os.path.isdir(systems_dir):
        return
    for name in sorted(os.listdir(systems_dir)):
        pack_dir = os.path.join(systems_dir, name)
        system_json = os.path.join(pack_dir, "system.json")
        test_cfg = os.path.join(pack_dir, "test_config.json")
        if os.path.isfile(system_json) and not os.path.isfile(test_cfg):
            config.issue_config_time_warning(
                pytest.PytestConfigWarning(
                    f"System pack '{name}' has no test_config.json — "
                    f"it won't be covered by the parametrized test harness"
                ),
                stacklevel=1,
            )


def _extract_id(result):
    """Extract integer ID from result strings like 'FOO_CREATED: 123'."""
    m = re.search(r":\s*(\d+)", result)
    assert m, f"Could not extract ID from: {result}"
    return int(m.group(1))


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Point LoreKit at a temp database for every test."""
    db = str(tmp_path / "game.db")
    monkeypatch.setenv("LOREKIT_DB_DIR", str(tmp_path))
    monkeypatch.setenv("LOREKIT_DB", db)
    from _db import init_schema

    init_schema(db)


@pytest.fixture
def make_session():
    """Factory that creates a session and returns its integer ID."""

    def _make(name="Test Campaign", setting="Fantasy World", system="d20 Fantasy"):
        from mcp_server import session_create

        result = session_create(name=name, setting=setting, system=system)
        return _extract_id(result)

    return _make


@pytest.fixture
def make_character():
    """Factory that creates a character and returns its integer ID."""

    def _make(session_id, name="Test Hero", char_type="pc", region=None, level=1):
        from mcp_server import character_create

        kwargs = dict(session=session_id, name=name, level=level, type=char_type)
        if region:
            kwargs["region"] = region
        result = character_create(**kwargs)
        return _extract_id(result)

    return _make


@pytest.fixture
def make_region():
    """Factory that creates a region and returns its integer ID."""

    def _make(session_id, name="Test Region", desc="A test region"):
        from mcp_server import region_create

        result = region_create(session_id=session_id, name=name, desc=desc)
        return _extract_id(result)

    return _make
