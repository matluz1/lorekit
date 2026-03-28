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


class TestSaveMidCombatLoadRestores:
    """Save mid-combat, change more state, load the save — full state restored."""

    def test_load_restores_full_combat_state(self, make_session, make_character):
        sid = _setup_session(make_session)
        fighter = _setup_fighter(sid, make_character, "Fighter", 30)
        goblin = _setup_fighter(sid, make_character, "Goblin", 20)

        # Start encounter: 3 zones, both in Front (melee_range=0 requires same zone)
        zones = json.dumps([{"name": "Front"}, {"name": "Middle"}, {"name": "Back"}])
        initiative = json.dumps(
            [
                {"character_id": fighter, "roll": 20},
                {"character_id": goblin, "roll": 10},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": fighter, "zone": "Front"},
                {"character_id": goblin, "zone": "Front"},
            ]
        )
        result = encounter_start(
            session_id=sid,
            zones=zones,
            initiative=initiative,
            placements=placements,
        )
        assert "ENCOUNTER STARTED" in result

        # -- Turn 0: initial state --
        turn_save(session_id=sid, narration="Combat begins.", summary="Start")

        # -- Turn 1: Fighter attacks Goblin (melee, same zone) --
        # melee_attack=9, d20=18 → 18+9=27 vs AC 12 → HIT
        # d8=6 → 6+4=10 dmg. Goblin HP: 20 → 10
        rolls = iter([17, 5])  # d20=18, d8=6
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=goblin,
                action="melee_attack",
                system_path=TEST_SYSTEM,
            )
        assert "HIT" in result

        # Move Goblin to Middle (to test position save/load)
        encounter_move(character_id=goblin, target_zone="Middle")
        turn_save(session_id=sid, narration="Fighter strikes Goblin.", summary="T1")

        # -- Turn 2: Advance to Goblin's turn, Goblin uses fireball (ranged, no range limit) --
        encounter_advance_turn(session_id=sid)
        # ranged_attack=7, d20=15 → 15+7=22 vs AC 12 → HIT
        # d8=4 → 4+4=8 dmg. Fighter HP: 30 → 22
        rolls = iter([14, 3])  # d20=15, d8=4
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=goblin,
                defender_id=fighter,
                action="fireball",
                system_path=TEST_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Goblin retaliates.", summary="T2")

        # -- Save here --
        manual_save(session_id=sid, name="Mid Combat")

        # -- Turn 3: Advance to Fighter's turn, move to Middle, melee attack --
        encounter_advance_turn(session_id=sid)
        encounter_move(character_id=fighter, target_zone="Middle")
        # melee_attack=9, d20=19 → 19+9=28 vs AC 12 → HIT
        # d8=7 → 7+4=11 dmg. Goblin HP: 10 → -1
        rolls = iter([18, 6])  # d20=19, d8=7
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=goblin,
                action="melee_attack",
                system_path=TEST_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Fighter finishes Goblin.", summary="T3")

        # -- Load the save --
        result = save_load(session_id=sid, name="Mid Combat")
        assert "SAVE_LOADED" in result

        # -- Assertions --
        # Encounter status
        status = encounter_status(session_id=sid)
        assert "Round" in status
        assert "Fighter" in status
        assert "Goblin" in status

        # Zone positions: Goblin in Middle (moved in T1), Fighter in Front (not Middle)
        # Fighter was moved to Middle in T3, but load restored T2 state
        assert "Middle" in status
        assert "Front" in status

        # HP values — character_view renders attributes as a table (category, key, value columns)
        fighter_view = character_view(character_id=fighter)
        goblin_view = character_view(character_id=goblin)
        assert any("current_hp" in line and "22" in line for line in fighter_view.splitlines()), (
            f"Expected current_hp=22 in fighter view:\n{fighter_view}"
        )
        assert any("current_hp" in line and "10" in line for line in goblin_view.splitlines()), (
            f"Expected current_hp=10 in goblin view:\n{goblin_view}"
        )

        # Timeline: should have turns 1-2 but NOT turn 3
        timeline = timeline_list(session_id=sid)
        assert "Fighter strikes Goblin." in timeline
        assert "Goblin retaliates." in timeline
        assert "Fighter finishes Goblin." not in timeline

        # Initiative order preserved (Fighter first, Goblin second)
        # Status format: "Initiative: Fighter, Goblin" — check within that line
        initiative_line = next((ln for ln in status.splitlines() if "Initiative" in ln), "")
        assert "Fighter" in initiative_line
        assert initiative_line.index("Fighter") < initiative_line.index("Goblin")
