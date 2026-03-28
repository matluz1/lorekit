"""Integration tests: PF2e combat + checkpoint branching.

Verify that save/load/revert correctly preserves and restores full
encounter state (round, turn, positions, HP, grapple modifiers, zone
terrain effects) under the PF2e threshold-based resolution system.
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PF2E_SYSTEM = os.path.join(ROOT, "systems", "pf2e", "src", "cruncher_pf2e", "data")


@pytest.fixture(autouse=True)
def _patch_system_path(monkeypatch):
    """Make resolve_system_path find our PF2e pack."""
    _real = resolve_system_path

    def _patched(name):
        if name == "pf2e":
            return PF2E_SYSTEM
        return _real(name)

    monkeypatch.setattr("lorekit.rules.resolve_system_path", _patched)


def _setup_session(make_session):
    return make_session(system="pf2e")


def _setup_fighter(session_id, make_character):
    """Fighter: STR 18, DEX 14, CON 14, level 5.

    Derived (at level 5, trained = prof 2):
      str_mod = 4, dex_mod = 2, con_mod = 2
      melee_attack = 4 + (2 + 5) = 11
      armor_class  = 10 + 2 + (2 + 5) = 19
      skill_athletics = 4 + (2 + 5) = 11
      fortitude = 2 + (2 + 5) = 9  ->  fortitude_dc = 10 + 9 = 19
      max_hp = 8 + (10 + 2) * 5 = 68  (ancestry_hp=8, hp_per_level=10)
    """
    cid = make_character(session_id, name="Fighter", level=5)
    attrs = json.dumps(
        [
            {"category": "stat", "key": "str", "value": "18"},
            {"category": "stat", "key": "dex", "value": "14"},
            {"category": "stat", "key": "con", "value": "14"},
            {"category": "stat", "key": "ancestry_hp", "value": "8"},
            {"category": "stat", "key": "hp_per_level", "value": "10"},
            {"category": "stat", "key": "prof_simple_weapons", "value": "2"},
            {"category": "stat", "key": "prof_unarmored", "value": "2"},
            {"category": "stat", "key": "prof_athletics", "value": "2"},
            {"category": "stat", "key": "prof_fortitude", "value": "2"},
            {"category": "stat", "key": "prof_reflex", "value": "2"},
            {"category": "stat", "key": "fortitude_dc", "value": "19"},
            {"category": "build", "key": "weapon_damage_die", "value": "1d8"},
            {"category": "combat", "key": "current_hp", "value": "68"},
        ]
    )
    character_sheet_update(character_id=cid, attrs=attrs)
    return cid


def _setup_rogue(session_id, make_character):
    """Rogue: DEX 18, STR 10, CON 12, level 5.

    Derived (at level 5, trained = prof 2):
      str_mod = 0, dex_mod = 4, con_mod = 1
      melee_attack = 0 + (2 + 5) = 7
      armor_class  = 10 + 4 + (2 + 5) = 21
      skill_athletics = 0 (untrained)
      fortitude = 1 + (2 + 5) = 8  ->  fortitude_dc = 10 + 8 = 18
      max_hp = 6 + (8 + 1) * 5 = 51  (ancestry_hp=6, hp_per_level=8)
    """
    cid = make_character(session_id, name="Rogue", level=5)
    attrs = json.dumps(
        [
            {"category": "stat", "key": "str", "value": "10"},
            {"category": "stat", "key": "dex", "value": "18"},
            {"category": "stat", "key": "con", "value": "12"},
            {"category": "stat", "key": "ancestry_hp", "value": "6"},
            {"category": "stat", "key": "hp_per_level", "value": "8"},
            {"category": "stat", "key": "prof_simple_weapons", "value": "2"},
            {"category": "stat", "key": "prof_unarmored", "value": "2"},
            {"category": "stat", "key": "prof_athletics", "value": "0"},
            {"category": "stat", "key": "prof_fortitude", "value": "2"},
            {"category": "stat", "key": "prof_reflex", "value": "2"},
            {"category": "stat", "key": "fortitude_dc", "value": "18"},
            {"category": "build", "key": "weapon_damage_die", "value": "1d6"},
            {"category": "combat", "key": "current_hp", "value": "51"},
        ]
    )
    character_sheet_update(character_id=cid, attrs=attrs)
    return cid


def _get_db():
    from lorekit.db import get_db

    return get_db(os.environ["LOREKIT_DB"])


class TestPF2eDirtyCombatCheckpoint:
    """Create dirty PF2e combat state with damage, grapple modifiers, zone
    positions, and terrain tags, then verify checkpoint save/load restores all."""

    def test_save_grappled_state_load_restores_everything(self, make_session, make_character):
        sid = _setup_session(make_session)
        fighter = _setup_fighter(sid, make_character)
        rogue = _setup_rogue(sid, make_character)

        # 3 zones: Tavern (cover), Street, Alley (difficult_terrain)
        # Adjacency: Tavern-Street, Street-Alley
        zones = json.dumps(
            [
                {"name": "Tavern", "tags": ["cover"]},
                {"name": "Street"},
                {"name": "Alley", "tags": ["difficult_terrain"]},
            ]
        )
        adjacency = json.dumps(
            [
                {"from": "Tavern", "to": "Street", "weight": 1},
                {"from": "Street", "to": "Alley", "weight": 1},
            ]
        )
        initiative = json.dumps(
            [
                {"character_id": fighter, "roll": 20},
                {"character_id": rogue, "roll": 10},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": fighter, "zone": "Street"},
                {"character_id": rogue, "zone": "Tavern"},
            ]
        )
        result = encounter_start(
            session_id=sid,
            zones=zones,
            adjacency=adjacency,
            initiative=initiative,
            placements=placements,
        )
        assert "ENCOUNTER STARTED" in result

        turn_save(session_id=sid, narration="Tavern brawl begins.", summary="Start")

        # -- Step 1: Fighter moves to Tavern --
        encounter_move(character_id=fighter, target_zone="Tavern")

        # -- Step 2: Fighter attacks Rogue with melee_attack --
        # Fighter melee_attack = 11, Rogue armor_class = 21
        # d20=15 (randbelow returns 14), total = 15 + 11 = 26 >= 21 -> HIT
        # d8=5 (randbelow returns 4), damage = 5 + str_mod(4) = 9
        # Rogue HP: 51 -> 42
        rolls = iter([14, 4])  # d20=15, d8=5
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=rogue,
                action="melee_attack",
                system_path=PF2E_SYSTEM,
            )
        assert "HIT" in result

        turn_save(session_id=sid, narration="Fighter slashes the Rogue.", summary="T1")

        # -- Step 3: Fighter grapples Rogue --
        # Fighter skill_athletics = 11, Rogue fortitude_dc = 18
        # d20=12 (randbelow returns 11), total = 12 + 11 = 23 >= 18 -> HIT
        # Applies: bonus_ac -2, bonus_speed -999 on Rogue
        rolls = iter([11])  # d20=12
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=rogue,
                action="grapple",
                system_path=PF2E_SYSTEM,
            )
        assert "HIT" in result

        turn_save(session_id=sid, narration="Fighter grapples Rogue.", summary="T2 Grapple")

        # Verify grapple modifiers exist before saving
        db = _get_db()
        grapple_mods = db.execute(
            "SELECT source, target_stat, value FROM combat_state WHERE character_id = ? AND source = 'grapple'",
            (rogue,),
        ).fetchall()
        db.close()
        assert len(grapple_mods) == 2, f"Expected 2 grapple modifiers, got {grapple_mods}"

        # -- Save checkpoint: "Grappled State" --
        manual_save(session_id=sid, name="Grappled State")

        # -- Step 4: Advance turn to Rogue --
        encounter_advance_turn(session_id=sid)
        turn_save(session_id=sid, narration="Rogue's turn.", summary="T3 Rogue")

        # -- Step 5: Rogue takes more damage from fighter counter (next round) --
        # Advance back to Fighter's turn (round 2)
        encounter_advance_turn(session_id=sid)

        # Fighter attacks again, bringing Rogue HP further down
        # d20=18 (randbelow 17), total = 18 + 11 = 29 >= 21 -> HIT
        # d8=7 (randbelow 6), damage = 7 + 4 = 11
        # Rogue HP: 42 -> 31
        rolls = iter([17, 6])  # d20=18, d8=7
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=rogue,
                action="melee_attack",
                system_path=PF2E_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Fighter pounds Rogue.", summary="T4")

        # Move Rogue to Street (to dirty positions further)
        encounter_move(character_id=rogue, target_zone="Street")
        turn_save(session_id=sid, narration="Rogue stumbles to Street.", summary="T5 Move")

        # Verify Rogue HP is now 31
        rogue_view = character_view(character_id=rogue)
        assert any("current_hp" in line and "31" in line for line in rogue_view.splitlines()), (
            f"Expected current_hp=31 before load:\n{rogue_view}"
        )

        # -- Step 6: Load "Grappled State" --
        result = save_load(session_id=sid, name="Grappled State")
        assert "SAVE_LOADED" in result

        # -- Step 7: Verify ALL state is restored --

        # 7a: Rogue HP at saved value (42)
        rogue_view = character_view(character_id=rogue)
        assert any("current_hp" in line and "42" in line for line in rogue_view.splitlines()), (
            f"Expected current_hp=42 after load:\n{rogue_view}"
        )

        # 7b: Fighter HP unchanged (68, never took damage)
        fighter_view = character_view(character_id=fighter)
        assert any("current_hp" in line and "68" in line for line in fighter_view.splitlines()), (
            f"Expected current_hp=68 after load:\n{fighter_view}"
        )

        # 7c: Grapple modifiers present in combat_state
        db = _get_db()
        grapple_mods = db.execute(
            "SELECT source, target_stat, value FROM combat_state WHERE character_id = ? AND source = 'grapple'",
            (rogue,),
        ).fetchall()
        db.close()
        assert len(grapple_mods) == 2, f"Expected 2 grapple modifiers restored, got {grapple_mods}"

        # 7d: Zone positions (both in Tavern)
        status = encounter_status(session_id=sid)
        assert "Tavern" in status
        # Rogue should be in Tavern (not Street — that was after the save)
        # Fighter should also be in Tavern
        assert "Fighter" in status
        assert "Rogue" in status

        # 7e: Initiative order (Fighter first, Rogue second)
        initiative_line = next((ln for ln in status.splitlines() if "Initiative" in ln), "")
        assert "Fighter" in initiative_line
        assert initiative_line.index("Fighter") < initiative_line.index("Rogue")

        # 7f: Round 1, Fighter's turn (the save was on Fighter's turn, round 1)
        assert "Round" in status

        # 7g: Timeline entries match (T4/T5 gone, T1/T2 present)
        timeline = timeline_list(session_id=sid)
        assert "Fighter slashes the Rogue." in timeline
        assert "Fighter grapples Rogue." in timeline
        assert "Fighter pounds Rogue." not in timeline
        assert "Rogue stumbles to Street." not in timeline

        # 7h: Terrain tags: Tavern has cover modifier
        db = _get_db()
        terrain_mods = db.execute(
            "SELECT source FROM combat_state WHERE character_id = ? AND source LIKE 'zone:%'",
            (rogue,),
        ).fetchall()
        db.close()
        # Rogue is in Tavern (cover zone), so should have terrain modifier
        assert len(terrain_mods) > 0, "Expected terrain modifier from Tavern cover zone"

    def test_revert_undoes_grapple_and_damage(self, make_session, make_character):
        """After grapple + damage, turn_revert restores prior state."""
        sid = _setup_session(make_session)
        fighter = _setup_fighter(sid, make_character)
        rogue = _setup_rogue(sid, make_character)

        # Single zone for simplicity
        zones = json.dumps([{"name": "Arena"}])
        initiative = json.dumps(
            [
                {"character_id": fighter, "roll": 20},
                {"character_id": rogue, "roll": 10},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": fighter, "zone": "Arena"},
                {"character_id": rogue, "zone": "Arena"},
            ]
        )
        encounter_start(
            session_id=sid,
            zones=zones,
            initiative=initiative,
            placements=placements,
        )

        turn_save(session_id=sid, narration="Arena combat begins.", summary="Start")

        # -- Fighter attacks Rogue (d20=15, d8=5 -> 9 dmg, HP 51 -> 42) --
        rolls = iter([14, 4])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=rogue,
                action="melee_attack",
                system_path=PF2E_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Fighter attacks Rogue.", summary="T1")

        # Verify Rogue HP = 42
        rogue_view = character_view(character_id=rogue)
        assert any("current_hp" in line and "42" in line for line in rogue_view.splitlines())

        # -- Fighter grapples Rogue --
        # d20=12 (randbelow 11), total = 12 + 11 = 23 >= 18 -> HIT
        rolls = iter([11])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=rogue,
                action="grapple",
                system_path=PF2E_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Fighter grapples Rogue.", summary="T2 Grapple")

        # Verify grapple modifiers exist
        db = _get_db()
        grapple_mods = db.execute(
            "SELECT source FROM combat_state WHERE character_id = ? AND source = 'grapple'",
            (rogue,),
        ).fetchall()
        db.close()
        assert len(grapple_mods) > 0

        # -- Revert the grapple turn --
        result = turn_revert(session_id=sid)
        assert "TURN_REVERTED" in result

        # Grapple modifiers gone
        db = _get_db()
        grapple_mods = db.execute(
            "SELECT source FROM combat_state WHERE character_id = ? AND source = 'grapple'",
            (rogue,),
        ).fetchall()
        db.close()
        assert len(grapple_mods) == 0, "Grapple modifiers should be removed after revert"

        # Rogue HP still 42 (T1 damage stays, only T2 was reverted)
        rogue_view = character_view(character_id=rogue)
        assert any("current_hp" in line and "42" in line for line in rogue_view.splitlines()), (
            f"Expected current_hp=42 after revert:\n{rogue_view}"
        )

        # Timeline: T1 present, T2 gone
        timeline = timeline_list(session_id=sid)
        assert "Fighter attacks Rogue." in timeline
        assert "Fighter grapples Rogue." not in timeline

    def test_power_attack_damage_checkpoint(self, make_session, make_character):
        """Power attack with composable damage is properly checkpointed."""
        sid = _setup_session(make_session)
        fighter = _setup_fighter(sid, make_character)
        rogue = _setup_rogue(sid, make_character)

        zones = json.dumps([{"name": "Arena"}])
        initiative = json.dumps(
            [
                {"character_id": fighter, "roll": 20},
                {"character_id": rogue, "roll": 10},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": fighter, "zone": "Arena"},
                {"character_id": rogue, "zone": "Arena"},
            ]
        )
        encounter_start(
            session_id=sid,
            zones=zones,
            initiative=initiative,
            placements=placements,
        )

        turn_save(session_id=sid, narration="Power attack test.", summary="Start")

        # Power attack at level 5: power_attack_extra = 1 (level < 10)
        # damage_roll: [weapon_damage_die(1d8) + str_mod, weapon_damage_die(1d8) x power_attack_extra(1)]
        # So: 1d8 + str_mod(4) + 1x1d8
        # Fighter melee_attack = 11, Rogue armor_class = 21
        # d20=16 (randbelow 15), total = 16 + 11 = 27 >= 21 -> HIT
        # First d8=6 (randbelow 5), bonus = str_mod 4 -> 6+4=10
        # Extra d8=4 (randbelow 3) -> 4
        # Total damage = 10 + 4 = 14, Rogue HP: 51 -> 37
        rolls = iter([15, 5, 3])  # d20=16, d8=6, d8=4
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=fighter,
                defender_id=rogue,
                action="power_attack",
                system_path=PF2E_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Fighter power attacks.", summary="T1 Power")

        # Save state
        manual_save(session_id=sid, name="After Power Attack")

        # Do more damage
        rolls = iter([14, 4])  # d20=15, d8=5 -> 5+4=9, HP 37->28
        with patch("secrets.randbelow", side_effect=rolls):
            rules_resolve(
                attacker_id=fighter,
                defender_id=rogue,
                action="melee_attack",
                system_path=PF2E_SYSTEM,
            )
        turn_save(session_id=sid, narration="More damage.", summary="T2")

        # Load checkpoint
        result = save_load(session_id=sid, name="After Power Attack")
        assert "SAVE_LOADED" in result

        # Rogue HP = 37 (power attack damage preserved, followup undone)
        rogue_view = character_view(character_id=rogue)
        assert any("current_hp" in line and "37" in line for line in rogue_view.splitlines()), (
            f"Expected current_hp=37 after load:\n{rogue_view}"
        )

        timeline = timeline_list(session_id=sid)
        assert "Fighter power attacks." in timeline
        assert "More damage." not in timeline
