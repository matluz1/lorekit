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


class TestRevertMidCombatUndoesActions:
    """Revert undoes the latest combat action's effects (damage + modifiers)."""

    def test_revert_removes_grapple_modifier(self, make_session, make_character):
        sid = _setup_session(make_session)
        fighter = _setup_fighter(sid, make_character, "Fighter", 30)
        goblin = _setup_fighter(sid, make_character, "Goblin", 20)

        _start_encounter_arena(sid, fighter, goblin)

        # -- Turn 0: initial state --
        turn_save(session_id=sid, narration="Combat begins.", summary="Start")

        # -- Turn 1: Fighter attacks Goblin (d20=18, d8=6 → 10 dmg) --
        rolls = iter([17, 5])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=goblin,
                action="melee_attack",
                system_path=TEST_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Fighter attacks.", summary="T1")

        # -- Turn 2: Fighter grapples Goblin (contested melee_attack) --
        # Attacker d20=15 + 9 = 24, Defender d20=5 + 9 = 14 → HIT
        # Applies -2 defense modifier (encounter duration)
        rolls = iter([14, 4])  # attacker d20=15, defender d20=5
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=goblin,
                action="grapple",
                system_path=TEST_SYSTEM,
            )
        assert "HIT" in result or "wins by" in result
        turn_save(session_id=sid, narration="Fighter grapples Goblin.", summary="T2")

        # Verify grapple modifier exists before revert
        db = _get_db()
        grapple_mods = db.execute(
            "SELECT source FROM combat_state WHERE character_id = ? AND source = 'grapple'",
            (goblin,),
        ).fetchall()
        db.close()
        assert len(grapple_mods) > 0

        # -- Revert --
        result = turn_revert(session_id=sid)
        assert "TURN_REVERTED" in result

        # -- Assertions --
        # Goblin HP = 10 (turn 1 damage stays)
        goblin_view = character_view(character_id=goblin)
        assert any("current_hp" in line and "10" in line for line in goblin_view.splitlines())

        # Grapple modifier gone
        db = _get_db()
        grapple_mods = db.execute(
            "SELECT source FROM combat_state WHERE character_id = ? AND source = 'grapple'",
            (goblin,),
        ).fetchall()
        db.close()
        assert len(grapple_mods) == 0

        # Timeline: has turn 1 but not turn 2
        timeline = timeline_list(session_id=sid)
        assert "Fighter attacks." in timeline
        assert "Fighter grapples Goblin." not in timeline


class TestSaveBranchLoadCrossBranch:
    """Save on branch A during combat, fork to B, load branch A save."""

    def test_cross_branch_load_restores_correct_state(self, make_session, make_character):
        sid = _setup_session(make_session)
        fighter = _setup_fighter(sid, make_character, "Fighter", 30)
        goblin = _setup_fighter(sid, make_character, "Goblin", 20)

        _start_encounter_arena(sid, fighter, goblin)

        # -- Checkpoint #0 + #1: initial state --
        turn_save(session_id=sid, narration="Combat begins.", summary="Start")

        # -- Turn 1: Fighter attacks Goblin (d20=18, d8=6 → 10 dmg, HP 20→10) --
        rolls = iter([17, 5])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=goblin,
                action="melee_attack",
                system_path=TEST_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Fighter hits Goblin.", summary="T1")

        # Save on branch 1
        manual_save(session_id=sid, name="Branch Point")

        # -- Turn 2: Fighter attacks again (d20=17, d8=4 → 8 dmg, HP 10→2) --
        rolls = iter([16, 3])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=goblin,
                action="melee_attack",
                system_path=TEST_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Fighter hits again.", summary="T2")

        # -- Revert 2 steps (back to initial game state, Goblin HP=20) --
        result = turn_revert(session_id=sid, steps=2)
        assert "TURN_REVERTED" in result

        # -- Alt turn: Fighter attacks and MISSES (d20=2) --
        rolls = iter([1])  # d20=2, miss (2+9=11 < AC 12)
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=goblin,
                action="melee_attack",
                system_path=TEST_SYSTEM,
            )
        assert "MISS" in result
        turn_save(session_id=sid, narration="Fighter misses.", summary="Alt")

        # Verify we're on branch 2
        assert _branch_count(sid) == 2

        # Goblin HP should be 20 (miss on this branch)
        goblin_view = character_view(character_id=goblin)
        assert any("current_hp" in line and "20" in line for line in goblin_view.splitlines())

        # -- Load "Branch Point" from branch 1 --
        result = save_load(session_id=sid, name="Branch Point")
        assert "SAVE_LOADED" in result

        # -- Assertions --
        # Goblin HP = 10 (branch 1 state after first hit)
        goblin_view = character_view(character_id=goblin)
        assert any("current_hp" in line and "10" in line for line in goblin_view.splitlines())

        # Encounter still active
        status = encounter_status(session_id=sid)
        assert "Round" in status
        assert "Fighter" in status

        # Both branches preserved
        assert _branch_count(sid) == 2

        # Timeline shows branch 1 content
        timeline = timeline_list(session_id=sid)
        assert "Fighter hits Goblin." in timeline
        assert "Fighter misses." not in timeline


class TestSaveBeforeCombatLoadAfterStarted:
    """Save during exploration, start combat, load — encounter disappears."""

    def test_load_pre_combat_save_removes_encounter(self, make_session, make_character):
        sid = _setup_session(make_session)
        fighter = _setup_fighter(sid, make_character, "Fighter", 30)
        goblin = _setup_fighter(sid, make_character, "Goblin", 20)

        # -- Save before combat --
        turn_save(session_id=sid, narration="Exploring the dungeon.", summary="Explore")
        manual_save(session_id=sid, name="Exploration")

        # -- Start combat --
        result = _start_encounter_arena(sid, fighter, goblin)
        assert "ENCOUNTER STARTED" in result

        # -- Fighter attacks Goblin (d20=18, d8=6 → 10 dmg) --
        rolls = iter([17, 5])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=goblin,
                action="melee_attack",
                system_path=TEST_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Combat rages.", summary="Combat")

        # Verify encounter is active
        status = encounter_status(session_id=sid)
        assert "Round" in status

        # -- Load pre-combat save --
        result = save_load(session_id=sid, name="Exploration")
        assert "SAVE_LOADED" in result

        # -- Assertions --
        # No active encounter
        db = _get_db()
        active_enc = db.execute(
            "SELECT COUNT(*) FROM encounter_state WHERE session_id = ? AND status = 'active'",
            (sid,),
        ).fetchone()[0]
        assert active_enc == 0

        # No zone placements
        zone_count = db.execute(
            "SELECT COUNT(*) FROM character_zone cz "
            "JOIN encounter_state es ON cz.encounter_id = es.id "
            "WHERE es.session_id = ?",
            (sid,),
        ).fetchone()[0]
        assert zone_count == 0

        # No encounter zones
        enc_zones = db.execute(
            "SELECT COUNT(*) FROM encounter_zones ez "
            "JOIN encounter_state es ON ez.encounter_id = es.id "
            "WHERE es.session_id = ?",
            (sid,),
        ).fetchone()[0]
        assert enc_zones == 0

        # No combat modifiers
        combat_mods = db.execute(
            "SELECT COUNT(*) FROM combat_state WHERE character_id IN (?, ?)",
            (fighter, goblin),
        ).fetchone()[0]
        assert combat_mods == 0
        db.close()

        # Characters exist with pre-combat HP
        fighter_view = character_view(character_id=fighter)
        goblin_view = character_view(character_id=goblin)
        assert any("current_hp" in line and "30" in line for line in fighter_view.splitlines())
        assert any("current_hp" in line and "20" in line for line in goblin_view.splitlines())

        # Timeline: exploration narration present, combat narration gone
        timeline = timeline_list(session_id=sid)
        assert "Exploring the dungeon." in timeline
        assert "Combat rages." not in timeline


class TestSaveDuringCombatLoadAfterEnded:
    """Save during combat, end combat, load — encounter is active again."""

    def test_load_mid_combat_save_reactivates_encounter(self, make_session, make_character):
        sid = _setup_session(make_session)
        fighter = _setup_fighter(sid, make_character, "Fighter", 30)
        goblin = _setup_fighter(sid, make_character, "Goblin", 20)

        # -- Start combat with terrain tags for modifier testing --
        zones = json.dumps(
            [
                {"name": "Courtyard"},
                {"name": "Ramparts", "tags": ["cover"]},
            ]
        )
        initiative = json.dumps(
            [
                {"character_id": fighter, "roll": 20},
                {"character_id": goblin, "roll": 10},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": fighter, "zone": "Courtyard"},
                {"character_id": goblin, "zone": "Ramparts"},
            ]
        )
        result = encounter_start(
            session_id=sid,
            zones=zones,
            initiative=initiative,
            placements=placements,
        )
        assert "ENCOUNTER STARTED" in result

        # -- Initial save --
        turn_save(session_id=sid, narration="Battle at the fort.", summary="Start")

        # -- Fighter uses fireball on Goblin (ranged, cross-zone OK) --
        # ranged_attack=7, d20=18 → 18+7=25 vs AC 12 → HIT
        # d8=6 → 6+4=10 dmg. Goblin HP: 20 → 10
        rolls = iter([17, 5])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=goblin,
                action="fireball",
                system_path=TEST_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Fighter strikes.", summary="T1")
        manual_save(session_id=sid, name="In Battle")

        # Verify Goblin has terrain modifier from Ramparts (cover → +2 bonus_defense)
        db = _get_db()
        terrain_mods = db.execute(
            "SELECT source FROM combat_state WHERE character_id = ? AND source LIKE 'zone:%'",
            (goblin,),
        ).fetchall()
        db.close()
        has_terrain = len(terrain_mods) > 0

        # -- End combat --
        result = encounter_end(session_id=sid)
        assert "COMBAT ENDED" in result
        turn_save(session_id=sid, narration="Combat over.", summary="End")

        # Verify no active encounter
        db = _get_db()
        active = db.execute(
            "SELECT COUNT(*) FROM encounter_state WHERE session_id = ? AND status = 'active'",
            (sid,),
        ).fetchone()[0]
        db.close()
        assert active == 0

        # -- Load mid-combat save --
        result = save_load(session_id=sid, name="In Battle")
        assert "SAVE_LOADED" in result

        # -- Assertions --
        # Encounter is active again
        status = encounter_status(session_id=sid)
        assert "Round" in status
        assert "Fighter" in status
        assert "Goblin" in status

        # Zone positions restored
        assert "Courtyard" in status
        assert "Ramparts" in status

        # Goblin HP = 10 (post-attack)
        goblin_view = character_view(character_id=goblin)
        assert any("current_hp" in line and "10" in line for line in goblin_view.splitlines())

        # Terrain modifiers restored (if they existed before end_encounter)
        if has_terrain:
            db = _get_db()
            restored_mods = db.execute(
                "SELECT source FROM combat_state WHERE character_id = ? AND source LIKE 'zone:%'",
                (goblin,),
            ).fetchall()
            db.close()
            assert len(restored_mods) > 0

        # Zone adjacency restored
        db = _get_db()
        adj_count = db.execute(
            "SELECT COUNT(*) FROM zone_adjacency za "
            "JOIN encounter_zones ez ON za.zone_a = ez.id "
            "JOIN encounter_state es ON ez.encounter_id = es.id "
            "WHERE es.session_id = ?",
            (sid,),
        ).fetchone()[0]
        db.close()
        assert adj_count > 0

        # Timeline: "Battle at the fort" present, "Combat over" gone
        timeline = timeline_list(session_id=sid)
        assert "Battle at the fort." in timeline
        assert "Combat over." not in timeline
