"""Integration tests: MM3e combat + checkpoint branching.

Verify that save/load/revert correctly preserves and restores full
encounter state under the degree-based MM3e system — damage_penalty,
damage_condition, grab modifiers, contested skill actions, zone
positions, and initiative order.
"""

import json
import os
from unittest.mock import patch

import pytest

pytest.importorskip("sqlite_vec")

from lorekit.rules import resolve_system_path
from lorekit.tools.character import character_sheet_update, character_view
from lorekit.tools.encounter import (
    encounter_advance_turn,
    encounter_move,
    encounter_start,
    encounter_status,
)
from lorekit.tools.narrative import (
    manual_save,
    save_load,
    timeline_list,
    turn_revert,
    turn_save,
)
from lorekit.tools.rules import rules_resolve

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MM3E_SYSTEM = os.path.join(ROOT, "systems", "mm3e", "src", "cruncher_mm3e", "data")


@pytest.fixture(autouse=True)
def _patch_system_path(monkeypatch):
    """Make resolve_system_path find our mm3e pack."""
    _real = resolve_system_path

    def _patched(name):
        if name == "mm3e":
            return MM3E_SYSTEM
        return _real(name)

    monkeypatch.setattr("lorekit.rules.resolve_system_path", _patched)


# ---------------------------------------------------------------------------
# Character helpers
# ---------------------------------------------------------------------------


def _setup_hero(session_id, make_character):
    """PL 10 melee fighter.

    close_attack 10, close_damage 10, parry 10, toughness 10,
    dodge 8, fortitude 10, will 10, grab_dc 15+10=DC 25.
    skill_intimidation 10.
    """
    cid = make_character(session_id, name="Sentinel", level=10)
    attrs = json.dumps(
        [
            {"category": "stat", "key": "str", "value": "5"},
            {"category": "stat", "key": "sta", "value": "5"},
            {"category": "stat", "key": "dex", "value": "0"},
            {"category": "stat", "key": "agl", "value": "2"},
            {"category": "stat", "key": "fgt", "value": "8"},
            {"category": "stat", "key": "int", "value": "0"},
            {"category": "stat", "key": "awe", "value": "2"},
            {"category": "stat", "key": "pre", "value": "4"},
            # Defense ranks
            {"category": "stat", "key": "ranks_dodge", "value": "6"},
            {"category": "stat", "key": "ranks_parry", "value": "2"},
            {"category": "stat", "key": "ranks_toughness", "value": "5"},
            {"category": "stat", "key": "ranks_fortitude", "value": "5"},
            {"category": "stat", "key": "ranks_will", "value": "8"},
            # Attack advantages
            {"category": "stat", "key": "adv_close_attack", "value": "2"},
            # Weapon
            {"category": "stat", "key": "weapon_close_damage", "value": "5"},
            {"category": "stat", "key": "weapon_strength_based", "value": "1"},
            # Skills
            {"category": "stat", "key": "ranks_intimidation", "value": "6"},
            {"category": "stat", "key": "ranks_athletics", "value": "5"},
        ]
    )
    character_sheet_update(character_id=cid, attrs=attrs)
    return cid


def _setup_villain(session_id, make_character):
    """PL 10 ranged/control type.

    ranged_attack 10, ranged_damage 10, dodge 10, toughness 8,
    parry 6, fortitude 10, will 10.
    skill_insight 10, skill_deception 10.
    """
    cid = make_character(session_id, name="Puppeteer", level=10)
    attrs = json.dumps(
        [
            {"category": "stat", "key": "str", "value": "2"},
            {"category": "stat", "key": "sta", "value": "2"},
            {"category": "stat", "key": "dex", "value": "6"},
            {"category": "stat", "key": "agl", "value": "4"},
            {"category": "stat", "key": "fgt", "value": "2"},
            {"category": "stat", "key": "int", "value": "2"},
            {"category": "stat", "key": "awe", "value": "4"},
            {"category": "stat", "key": "pre", "value": "2"},
            # Defense ranks
            {"category": "stat", "key": "ranks_dodge", "value": "6"},
            {"category": "stat", "key": "ranks_parry", "value": "4"},
            {"category": "stat", "key": "ranks_toughness", "value": "6"},
            {"category": "stat", "key": "ranks_fortitude", "value": "8"},
            {"category": "stat", "key": "ranks_will", "value": "6"},
            # Ranged attack
            {"category": "stat", "key": "adv_ranged_attack", "value": "4"},
            {"category": "stat", "key": "weapon_ranged_damage", "value": "10"},
            # Skills
            {"category": "stat", "key": "ranks_insight", "value": "6"},
            {"category": "stat", "key": "ranks_deception", "value": "8"},
        ]
    )
    character_sheet_update(character_id=cid, attrs=attrs)
    return cid


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_db():
    from lorekit.db import get_db

    return get_db(os.environ["LOREKIT_DB"])


def _combat_state_rows(character_id, source=None):
    """Return combat_state rows for a character, optionally filtered by source."""
    db = _get_db()
    if source:
        rows = db.execute(
            "SELECT source, target_stat, value FROM combat_state WHERE character_id = ? AND source = ?",
            (character_id, source),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT source, target_stat, value FROM combat_state WHERE character_id = ?",
            (character_id,),
        ).fetchall()
    db.close()
    return rows


def _get_attr(character_id, key, category=None):
    """Read an attribute value from the character sheet."""
    db = _get_db()
    if category:
        row = db.execute(
            "SELECT value FROM character_attributes WHERE character_id = ? AND category = ? AND key = ?",
            (character_id, category, key),
        ).fetchone()
    else:
        row = db.execute(
            "SELECT value FROM character_attributes WHERE character_id = ? AND key = ? ORDER BY id DESC LIMIT 1",
            (character_id, key),
        ).fetchone()
    db.close()
    return row[0] if row else None


class TestMM3eDirtyCombatCheckpoint:
    """Save mid-combat with many MM3e modifiers, load and verify full restoration."""

    def test_load_restores_damage_grab_and_conditions(self, make_session, make_character):
        """Build dirty state: damage penalties, grab modifiers, zone moves.

        Sequence:
            T0  start encounter (Street, Rooftop, Alley), both in Street
            T1  Sentinel close_attack → Puppeteer (HIT, degree-2 → dazed)
            T2  Sentinel grabs Puppeteer (HIT, resist FAIL → grab mods)
            --- SAVE "Mid Grapple" ---
            T3  advance turn, Puppeteer moves (should fail due to grab,
                fallback: another attack to change state)
            T4  more state changes
            --- LOAD "Mid Grapple" ---
            verify everything restored
        """
        sid = make_session(system="mm3e")
        hero = _setup_hero(sid, make_character)
        villain = _setup_villain(sid, make_character)

        # 3 zones
        zones = json.dumps(
            [
                {"name": "Street"},
                {"name": "Rooftop"},
                {"name": "Alley"},
            ]
        )
        initiative = json.dumps(
            [
                {"character_id": hero, "roll": 20},
                {"character_id": villain, "roll": 5},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": hero, "zone": "Street"},
                {"character_id": villain, "zone": "Street"},
            ]
        )
        result = encounter_start(
            session_id=sid,
            zones=zones,
            initiative=initiative,
            placements=placements,
        )
        assert "ENCOUNTER STARTED" in result

        turn_save(session_id=sid, narration="Heroes face off in the street.", summary="Start")

        # ------------------------------------------------------------------
        # Turn 1: Sentinel close_attack → Puppeteer
        # ------------------------------------------------------------------
        # Hero: close_attack=10, close_damage=10
        # Villain: parry=6, DC = 6+10 = 16
        #   Attack: randbelow(20)=9 → die=10, total=10+10=20 vs DC 16 → HIT
        # Villain resistance: damage_resistance = toughness(8) - damage_penalty(0) = 8
        #   Resist DC = 15 + close_damage(10) = 25
        #   randbelow(20)=7 → die=8, total=8+8=16 vs DC 25 → FAIL by 9
        #   degree = 1 + floor(9/5) = 2 → damage_penalty +1, damage_condition = max(0,2) = 2 (dazed)
        rolls = iter([9, 7])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=hero,
                defender_id=villain,
                action="close_attack",
                system_path=MM3E_SYSTEM,
            )
        assert "HIT" in result
        assert "DEGREE OF FAILURE: 2" in result

        turn_save(session_id=sid, narration="Sentinel lands a heavy blow.", summary="T1")

        # Verify damage state after T1
        assert _get_attr(villain, "damage_penalty") == "1"
        assert _get_attr(villain, "damage_condition") == "2"

        # ------------------------------------------------------------------
        # Turn 2: Sentinel grabs Puppeteer
        # ------------------------------------------------------------------
        # Grab: close_attack(10) vs parry DC (6+10=16)
        #   Attack: randbelow(20)=11 → die=12, total=12+10=22 vs DC 16 → HIT
        # On-hit resist: villain rolls d20 + max(effective_str=2, dodge=10) = d20+10 vs DC (grab_dc+10)
        #   Hero grab_dc = str(5)+10 = 15, DC = 15+10 = 25
        #   randbelow(20)=4 → die=5, total=5+10=15 vs DC 25 → FAIL (not resisted)
        # Applies: source=grab, target_stat=bonus_dodge, value=0, until_escape
        # Then condition sync sees grab → adds cond:grab modifiers (-2 dodge, -999 speed)
        rolls = iter([11, 4])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=hero,
                defender_id=villain,
                action="grab",
                system_path=MM3E_SYSTEM,
            )
        assert "HIT" in result
        assert "RESIST" in result

        # Move hero to Rooftop (to test position save/load)
        encounter_move(character_id=hero, target_zone="Rooftop")

        turn_save(session_id=sid, narration="Sentinel grapples the Puppeteer.", summary="T2")

        # Verify grab modifiers exist
        grab_rows = _combat_state_rows(villain, source="grab")
        assert len(grab_rows) > 0, "Expected grab modifier on villain"

        # Verify condition-derived grab modifiers exist
        cond_grab_rows = _combat_state_rows(villain, source="cond:grab")
        assert len(cond_grab_rows) > 0, "Expected cond:grab modifiers on villain"

        # ------------------------------------------------------------------
        # SAVE "Mid Grapple"
        # ------------------------------------------------------------------
        manual_save(session_id=sid, name="Mid Grapple")

        # Snapshot state for later assertion
        pre_save_status = encounter_status(session_id=sid)

        # ------------------------------------------------------------------
        # Turn 3: Advance to villain's turn, villain attacks hero
        # ------------------------------------------------------------------
        encounter_advance_turn(session_id=sid)

        # Villain ranged_attack → Sentinel
        # ranged_attack=10 vs dodge DC (8+10=18)
        #   Attack: randbelow(20)=14 → die=15, total=15+10=25 vs DC 18 → HIT
        # Hero resistance: damage_resistance = toughness(10) - damage_penalty(0) = 10
        #   Resist DC = 15 + ranged_damage(10) = 25
        #   randbelow(20)=5 → die=6, total=6+10=16 vs DC 25 → FAIL by 9
        #   degree = 1 + floor(9/5) = 2 → damage_penalty +1, damage_condition = 2 (dazed)
        rolls = iter([14, 5])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=villain,
                defender_id=hero,
                action="ranged_attack",
                system_path=MM3E_SYSTEM,
            )
        assert "HIT" in result

        turn_save(session_id=sid, narration="Puppeteer retaliates from grapple.", summary="T3")

        # Move villain to Alley (post-save state change)
        encounter_move(character_id=villain, target_zone="Alley")

        turn_save(session_id=sid, narration="Puppeteer escapes to the alley.", summary="T4")

        # Verify hero now has damage_penalty from T3
        assert _get_attr(hero, "damage_penalty") == "1"

        # ------------------------------------------------------------------
        # LOAD "Mid Grapple"
        # ------------------------------------------------------------------
        result = save_load(session_id=sid, name="Mid Grapple")
        assert "SAVE_LOADED" in result

        # ------------------------------------------------------------------
        # Assertions: everything restored to "Mid Grapple" state
        # ------------------------------------------------------------------

        # 1. Encounter status
        status = encounter_status(session_id=sid)
        assert "Round" in status
        assert "Sentinel" in status
        assert "Puppeteer" in status

        # 2. Zone positions: hero in Rooftop, villain in Street (not Alley)
        assert "Rooftop" in status
        assert "Street" in status

        # 3. Initiative order preserved (Sentinel first, Puppeteer second)
        init_line = next((ln for ln in status.splitlines() if "Initiative" in ln), "")
        assert "Sentinel" in init_line
        assert init_line.index("Sentinel") < init_line.index("Puppeteer")

        # 4. Villain damage_penalty=1, damage_condition=2 (from T1, not further)
        assert _get_attr(villain, "damage_penalty") == "1"
        assert _get_attr(villain, "damage_condition") == "2"

        # 5. Hero damage_penalty should be 0 (T3 damage undone by load)
        hero_dp = _get_attr(hero, "damage_penalty")
        assert hero_dp is None or hero_dp == "0", f"Expected hero damage_penalty=0 after load, got {hero_dp}"

        # 6. Grab modifiers on villain restored
        grab_rows_after = _combat_state_rows(villain, source="grab")
        assert len(grab_rows_after) > 0, "Grab modifier should be restored on villain"

        cond_grab_after = _combat_state_rows(villain, source="cond:grab")
        assert len(cond_grab_after) > 0, "cond:grab modifiers should be restored"

        # 7. Timeline: T1 and T2 present, T3/T4 gone
        timeline = timeline_list(session_id=sid)
        assert "Sentinel lands a heavy blow." in timeline
        assert "Sentinel grapples the Puppeteer." in timeline
        assert "Puppeteer retaliates from grapple." not in timeline
        assert "Puppeteer escapes to the alley." not in timeline

    def test_revert_undoes_grab(self, make_session, make_character):
        """Revert after a grab removes the grab modifiers but keeps prior damage."""
        sid = make_session(system="mm3e")
        hero = _setup_hero(sid, make_character)
        villain = _setup_villain(sid, make_character)

        zones = json.dumps([{"name": "Arena"}])
        initiative = json.dumps(
            [
                {"character_id": hero, "roll": 20},
                {"character_id": villain, "roll": 5},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": hero, "zone": "Arena"},
                {"character_id": villain, "zone": "Arena"},
            ]
        )
        result = encounter_start(
            session_id=sid,
            zones=zones,
            initiative=initiative,
            placements=placements,
        )
        assert "ENCOUNTER STARTED" in result

        turn_save(session_id=sid, narration="Arena combat.", summary="Start")

        # T1: close_attack → damage
        # same rolls as above: randbelow 9 (attack), 7 (resist) → degree 2
        rolls = iter([9, 7])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=hero,
                defender_id=villain,
                action="close_attack",
                system_path=MM3E_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Sentinel punches.", summary="T1")

        # T2: grab → modifiers applied
        rolls = iter([11, 4])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=hero,
                defender_id=villain,
                action="grab",
                system_path=MM3E_SYSTEM,
            )
        assert "HIT" in result
        turn_save(session_id=sid, narration="Sentinel grapples.", summary="T2")

        # Verify grab exists
        assert len(_combat_state_rows(villain, source="grab")) > 0

        # Revert (undo T2)
        result = turn_revert(session_id=sid)
        assert "TURN_REVERTED" in result

        # Grab modifiers gone
        assert len(_combat_state_rows(villain, source="grab")) == 0
        assert len(_combat_state_rows(villain, source="cond:grab")) == 0

        # Damage from T1 preserved
        assert _get_attr(villain, "damage_penalty") == "1"
        assert _get_attr(villain, "damage_condition") == "2"

        # Timeline: T1 present, T2 gone
        timeline = timeline_list(session_id=sid)
        assert "Sentinel punches." in timeline
        assert "Sentinel grapples." not in timeline

    def test_contested_setup_modifiers_survive_checkpoint(self, make_session, make_character):
        """setup_intimidation applies next_attack_received modifier; save/load preserves it."""
        sid = make_session(system="mm3e")
        hero = _setup_hero(sid, make_character)
        villain = _setup_villain(sid, make_character)

        zones = json.dumps([{"name": "Arena"}])
        initiative = json.dumps(
            [
                {"character_id": hero, "roll": 20},
                {"character_id": villain, "roll": 5},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": hero, "zone": "Arena"},
                {"character_id": villain, "zone": "Arena"},
            ]
        )
        encounter_start(
            session_id=sid,
            zones=zones,
            initiative=initiative,
            placements=placements,
        )

        turn_save(session_id=sid, narration="Stare down.", summary="Start")

        # setup_intimidation: contested skill_intimidation vs skill_insight
        # Hero: skill_intimidation = pre(4) + ranks_intimidation(6) = 10
        # Villain: skill_insight = awe(4) + ranks_insight(6) = 10
        # Hero roll: randbelow(20)=14 → die=15, total=15+10=25
        # Villain roll: randbelow(20)=4 → die=5, total=5+10=15
        # HIT (25 >= 15)
        # Applies: source=vulnerable, bonus_dodge=0, condition, next_attack_received
        rolls = iter([14, 4])
        with patch("secrets.randbelow", side_effect=rolls):
            result = rules_resolve(
                attacker_id=hero,
                defender_id=villain,
                action="setup_intimidation",
                system_path=MM3E_SYSTEM,
            )
        assert "HIT" in result

        turn_save(session_id=sid, narration="Sentinel intimidates.", summary="T1")

        # Verify vulnerable modifier exists on villain
        vuln_rows = _combat_state_rows(villain, source="vulnerable")
        assert len(vuln_rows) > 0, "Expected vulnerable modifier from setup_intimidation"

        # Save
        manual_save(session_id=sid, name="Post Intimidate")

        # Consume the modifier: attack to trigger next_attack_received removal
        # close_attack: randbelow=9 (attack), randbelow=7 (resist)
        rolls = iter([9, 7])
        with patch("secrets.randbelow", side_effect=rolls):
            rules_resolve(
                attacker_id=hero,
                defender_id=villain,
                action="close_attack",
                system_path=MM3E_SYSTEM,
            )
        turn_save(session_id=sid, narration="Sentinel strikes.", summary="T2")

        # Vulnerable modifier should be consumed now
        vuln_after_attack = _combat_state_rows(villain, source="vulnerable")
        assert len(vuln_after_attack) == 0, "Vulnerable should be consumed after attack"

        # Load
        result = save_load(session_id=sid, name="Post Intimidate")
        assert "SAVE_LOADED" in result

        # Vulnerable modifier should be restored
        vuln_restored = _combat_state_rows(villain, source="vulnerable")
        assert len(vuln_restored) > 0, "Vulnerable modifier should be restored after load"

        # Timeline: T1 present, T2 gone
        timeline = timeline_list(session_id=sid)
        assert "Sentinel intimidates." in timeline
        assert "Sentinel strikes." not in timeline
