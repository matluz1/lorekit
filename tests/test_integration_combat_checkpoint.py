"""Integration tests: combat + checkpoint branching.

Verify that save/load/revert correctly preserves and restores
full encounter state (round, turn, positions, HP, modifiers)
across checkpoint branches.
"""

import json
import os
from unittest.mock import patch

import pytest

pytest.importorskip("sqlite_vec")

from lorekit.rules import resolve_system_path  # noqa: E402
from lorekit.tools.character import character_sheet_update, character_view  # noqa: E402
from lorekit.tools.encounter import (  # noqa: E402
    encounter_advance_turn,
    encounter_end,
    encounter_move,
    encounter_start,
    encounter_status,
)
from lorekit.tools.narrative import (  # noqa: E402
    manual_save,
    save_load,
    timeline_list,
    turn_revert,
    turn_save,
)
from lorekit.tools.rules import rules_resolve  # noqa: E402
from lorekit.tools.session import session_meta_set  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


@pytest.fixture(autouse=True)
def _patch_system_path(monkeypatch):
    """Make resolve_system_path find our test fixture for 'test_system'."""
    _real = resolve_system_path

    def _patched(name):
        if name == "test_system":
            return TEST_SYSTEM
        return _real(name)

    monkeypatch.setattr("lorekit.rules.resolve_system_path", _patched)


def _setup_session(make_session):
    """Create a session with rules_system pointing to test_system."""
    sid = make_session()
    session_meta_set(session_id=sid, key="rules_system", value="test_system")
    return sid


def _setup_fighter(session_id, make_character, name, hp):
    """Create a combat-ready character via tool-level calls."""
    cid = make_character(session_id, name=name, level=5)
    attrs = json.dumps(
        [
            {"category": "stat", "key": "str", "value": "18"},
            {"category": "stat", "key": "dex", "value": "14"},
            {"category": "stat", "key": "con", "value": "12"},
            {"category": "stat", "key": "base_attack", "value": "5"},
            {"category": "stat", "key": "hit_die_avg", "value": "6"},
            {"category": "build", "key": "weapon_damage_die", "value": "1d8"},
            {"category": "combat", "key": "current_hp", "value": str(hp)},
        ]
    )
    character_sheet_update(character_id=cid, attrs=attrs)
    return cid


def _start_encounter_arena(session_id, c1, c2):
    """Start encounter: single Arena zone, c1 first (init 20), c2 second (init 10)."""
    zones = json.dumps([{"name": "Arena"}])
    initiative = json.dumps(
        [
            {"character_id": c1, "roll": 20},
            {"character_id": c2, "roll": 10},
        ]
    )
    placements = json.dumps(
        [
            {"character_id": c1, "zone": "Arena"},
            {"character_id": c2, "zone": "Arena"},
        ]
    )
    return encounter_start(
        session_id=session_id,
        zones=zones,
        initiative=initiative,
        placements=placements,
    )


def _get_db():
    from lorekit.db import get_db

    return get_db(os.environ["LOREKIT_DB"])


def _branch_count(session_id):
    db = _get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM checkpoint_branches WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    db.close()
    return count
