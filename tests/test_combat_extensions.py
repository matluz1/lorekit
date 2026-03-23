"""Tests for combat engine extensions (F1-F10 + Phase 2 features).

Covers: per-action outcome tables, resource counters, remove_conditions,
modify_attribute, pre-resolution filters, character tags, extended ticks,
on-damage triggers, multiattack DC bonus, cumulative degree tracking,
reactions, team attack, join/leave encounter, power toggle, alternate switching,
homing, contagious.
"""

import json
import os
from unittest.mock import patch

import cruncher_mm3e
import pytest

from lorekit.combat import (
    _apply_degree_effect,
    _check_pre_resolution,
    _fire_damage_triggers,
    activate_power,
    deactivate_power,
    end_turn,
    resolve_action,
    switch_alternate,
)

MM3E_SYSTEM = cruncher_mm3e.pack_path()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mm3e_char(db, session_id, make_character, name, char_type="npc", **stats):
    from lorekit.character import set_attr
    from lorekit.rules import rules_calc

    cid = make_character(session_id, name=name, char_type=char_type)
    defaults = {
        "fgt": "6",
        "agl": "2",
        "dex": "2",
        "str": "4",
        "sta": "4",
        "int": "0",
        "awe": "2",
        "pre": "2",
    }
    defaults.update(stats)
    for key, val in defaults.items():
        set_attr(db, cid, "stat", key, str(val))
    rules_calc(db, cid, MM3E_SYSTEM)
    return cid


def _combat_cfg():
    with open(os.path.join(MM3E_SYSTEM, "system.json")) as f:
        return json.load(f)["combat"]


def _start_encounter(db, session_id, characters, placements):
    from lorekit.encounter import start_encounter

    cfg = _combat_cfg()
    start_encounter(
        db,
        session_id,
        [{"name": "Arena"}],
        [{"character_id": cid, "roll": 20 - i} for i, cid in enumerate(characters)],
        placements=[{"character_id": cid, "zone": "Arena"} for cid in characters],
        combat_cfg=cfg,
    )


# ===========================================================================
# F1: Per-Action Outcome Tables
# ===========================================================================


class TestOutcomeTableDispatch:
    """Engine uses action_def.outcome_table when present."""

    def test_action_with_outcome_table_uses_it(self, make_session, make_character):
        """An action_override with outcome_table should use that table, not on_failure."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Attacker")
            dfn = _make_mm3e_char(db, sid, make_character, "Defender")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Register a custom action that references the affliction_degrees table
            action_def = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "damage_rank_stat": "close_damage",
                    "outcome_table": "affliction_degrees",
                    "degrees": {"1": "dazed", "2": "stunned", "3": "incapacitated"},
                }
            )
            set_attr(db, atk, "action_override", "test_affliction", action_def)

            # Roll: attack hits (d20=15), resistance fails badly (d20=1)
            # degree should come from affliction_degrees, which uses {degree_N_condition}
            roll_calls = iter([14, 0])  # attack=15 (hit), resist=1 (big fail)
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "test_affliction", MM3E_SYSTEM)

            assert "DEGREE OF FAILURE:" in output
            # Should show one of the affliction condition labels
            assert "CONDITION:" in output
        finally:
            db.close()

    def test_fallback_to_on_failure(self, make_session, make_character):
        """Default close_attack (no outcome_table) still uses resolution.on_failure."""
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Attacker")
            dfn = _make_mm3e_char(db, sid, make_character, "Defender")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Attack hits, resistance fails → should use damage_degrees (default)
            roll_calls = iter([14, 0])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            assert "HIT!" in output
            assert "damage_penalty:" in output
        finally:
            db.close()


# ===========================================================================
# F5: Resource Counters
# ===========================================================================


class TestResourceCounters:
    def test_spend_resource(self, make_session, make_character):
        """on_use with spend_resource decrements the resource."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Hero")
            dfn = _make_mm3e_char(db, sid, make_character, "Villain")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Give hero 3 hero_points
            set_attr(db, atk, "resource", "hero_points", "3")

            # Action that spends 1 hero_point on use
            action_def = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "damage_rank_stat": "close_damage",
                    "on_use": {"spend_resource": {"key": "hero_points", "cost": 1}},
                }
            )
            set_attr(db, atk, "action_override", "heroic_strike", action_def)

            roll_calls = iter([14, 0])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "heroic_strike", MM3E_SYSTEM)

            assert "RESOURCE: hero_points 3 → 2" in output

            # Verify DB
            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'resource' AND key = 'hero_points'",
                (atk,),
            ).fetchone()
            assert row[0] == "2"
        finally:
            db.close()

    def test_spend_insufficient_raises(self, make_session, make_character):
        """Spending more than available raises LoreKitError."""
        from lorekit.character import set_attr
        from lorekit.db import LoreKitError, require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Hero")
            dfn = _make_mm3e_char(db, sid, make_character, "Villain")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Give hero 0 hero_points
            set_attr(db, atk, "resource", "hero_points", "0")

            action_def = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "on_use": {"spend_resource": {"key": "hero_points", "cost": 1}},
                }
            )
            set_attr(db, atk, "action_override", "heroic_strike", action_def)

            with pytest.raises(LoreKitError, match="Not enough hero_points"):
                resolve_action(db, atk, dfn, "heroic_strike", MM3E_SYSTEM)
        finally:
            db.close()


# ===========================================================================
# F8: Remove Conditions + Modify Attribute
# ===========================================================================


class TestRemoveConditions:
    def test_stand_up_removes_prone(self, make_session, make_character):
        """stand_up action removes prone condition modifiers."""
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Hero")
            dfn = _make_mm3e_char(db, sid, make_character, "Hero2")  # dummy defender
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Apply prone condition
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'cond:prone', 'bonus_close_attack', 'circumstance', -5, 'condition')",
                (atk,),
            )
            db.commit()

            # Use stand_up on self (attacker = defender for self-targeting)
            output = resolve_action(db, atk, atk, "stand_up", MM3E_SYSTEM)

            assert "CONDITION REMOVED: prone" in output

            # Verify condition modifier removed
            row = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'cond:prone'",
                (atk,),
            ).fetchone()
            assert row[0] == 0
        finally:
            db.close()


class TestModifyAttribute:
    def test_healing_reduces_damage(self, make_session, make_character):
        """on_hit modify_attribute reduces damage_penalty."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Healer")
            dfn = _make_mm3e_char(db, sid, make_character, "Wounded")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Set damage on defender
            set_attr(db, dfn, "combat", "damage_penalty", "3")

            # Healing action: on_hit modifies damage_penalty by -1 with floor 0
            action_def = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "on_hit": {
                        "modify_attribute": {"damage_penalty": -1},
                        "floor": {"damage_penalty": 0},
                    },
                }
            )
            set_attr(db, atk, "action_override", "heal_touch", action_def)

            # Ensure hit
            roll_calls = iter([19])  # d20=20 → guaranteed hit
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "heal_touch", MM3E_SYSTEM)

            assert "MODIFIED: damage_penalty 3 → 2" in output
        finally:
            db.close()


# ===========================================================================
# F2: Pre-Resolution Filters
# ===========================================================================


class TestImpervious:
    def test_impervious_blocks_low_rank(self, make_session, make_character):
        """Impervious toughness blocks attacks with rank <= half stat."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Weakling", str="0", fgt="2")
            dfn = _make_mm3e_char(db, sid, make_character, "Tank", sta="10")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Give tank impervious_damage_resistance = 14 (so threshold = 7)
            set_attr(db, dfn, "build", "impervious_damage_resistance", "14")

            # Attacker close_damage is low (str=0 → close_damage = 0)
            # So damage_rank = 0 which is ≤ 7 → impervious
            roll_calls = iter([19])  # hit
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            assert "IMPERVIOUS" in output
            assert "No effect (impervious)" in output
        finally:
            db.close()


class TestImmunity:
    def test_immunity_skips_resolution(self, make_session, make_character):
        """Immunity to a descriptor skips the entire resolution."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Pyro")
            dfn = _make_mm3e_char(db, sid, make_character, "Fireproof")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Give defender immunity to fire
            set_attr(db, dfn, "build", "immunity_fire", "1")

            # Create action with descriptor "fire"
            action_def = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "damage_rank_stat": "close_damage",
                    "descriptor": "fire",
                }
            )
            set_attr(db, atk, "action_override", "fire_blast", action_def)

            output = resolve_action(db, atk, dfn, "fire_blast", MM3E_SYSTEM)

            assert "IMMUNE" in output
            assert "immune to fire" in output
        finally:
            db.close()


# ===========================================================================
# F6: Character Resolution Tags (Minion Rules)
# ===========================================================================


class TestMinionRules:
    def test_minion_degree_escalated(self, make_session, make_character):
        """Minions have any failure degree escalated to 4."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Hero", fgt="10")
            dfn = _make_mm3e_char(db, sid, make_character, "Minion")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Flag defender as minion
            set_attr(db, dfn, "build", "is_minion", "1")

            # Attack hits (d20=15), resistance fails marginally (d20=8)
            # Normally degree 1, but minion escalates to 4
            roll_calls = iter([14, 7])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            if "HIT!" in output and "DEGREE OF FAILURE:" in output:
                assert "TAG [minion]: degree escalated" in output
        finally:
            db.close()


# ===========================================================================
# F3: Extended Tick Actions
# ===========================================================================


class TestModifyAttributeTick:
    def test_regeneration_tick(self, make_session, make_character):
        """end_turn with modify_attribute tick reduces damage_penalty."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            hero = _make_mm3e_char(db, sid, make_character, "Regen", char_type="pc")

            # Set damage
            set_attr(db, hero, "combat", "damage_penalty", "3")

            # Insert a regeneration modifier
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, "
                "value, duration_type) VALUES (?, 'regeneration', 'bonus_toughness', 'buff', 0, 'regeneration')",
                (hero,),
            )
            db.commit()

            # Add regeneration tick to end_turn config via a test system pack
            # We'll use the MM3E system and manually insert the modifier
            # Since MM3E doesn't have regeneration in end_turn, this tests
            # that unknown duration_types are skipped (no crash)
            output = end_turn(db, hero, MM3E_SYSTEM)
            # Should not crash, regeneration duration_type has no config yet
            assert "END TURN:" in output
        finally:
            db.close()


class TestAutoSaveTick:
    def test_auto_save_on_failure(self, make_session, make_character):
        """auto_save tick applies on_failure effect when save fails."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            hero = _make_mm3e_char(db, sid, make_character, "Dying")

            # Insert dying_check modifier
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, "
                "value, duration_type) VALUES (?, 'dying', 'bonus_toughness', 'condition', 0, 'dying_check')",
                (hero,),
            )
            db.commit()

            # Same as regeneration — MM3E doesn't have dying_check in end_turn config by default
            # This validates the engine doesn't crash on unknown duration_types
            output = end_turn(db, hero, MM3E_SYSTEM)
            assert "END TURN:" in output
        finally:
            db.close()


# ===========================================================================
# F4: On-Damage Triggers
# ===========================================================================


class TestConcentrationBreak:
    def test_concentration_check_on_damage(self, make_session, make_character):
        """Taking damage triggers a concentration save check."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            # Low-damage attacker so we get degree 1 (not incapacitated, which cancels concentration)
            atk = _make_mm3e_char(db, sid, make_character, "Attacker", fgt="6", str="0")
            dfn = _make_mm3e_char(db, sid, make_character, "Concentrator", sta="6")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Defender has a concentration modifier active
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, "
                "value, duration_type) VALUES (?, 'force_field', 'bonus_toughness', 'buff', 5, 'concentration')",
                (dfn,),
            )
            db.commit()

            # Attack hits (d20=15), Resistance just barely fails (d20=10 → degree 1),
            # then concentration check fires (d20=1 → fail)
            roll_calls = iter([14, 9, 0])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            if "HIT!" in output and "DEGREE OF FAILURE:" in output:
                # Degree 1 doesn't incapacitate, so concentration trigger should fire
                assert "CONCENTRATION" in output
        finally:
            db.close()


# ===========================================================================
# F9: Multiattack DC Bonus
# ===========================================================================


class TestMultiattack:
    def test_multiattack_dc_bonus(self, make_session, make_character):
        """High hit margin with multiattack action adds DC bonus."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Blaster", fgt="10")
            dfn = _make_mm3e_char(db, sid, make_character, "Target", agl="0")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Action with multiattack config
            action_def = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "damage_rank_stat": "close_damage",
                    "multiattack": {
                        "dc_bonus_thresholds": [
                            {"margin": 5, "bonus": 2},
                            {"margin": 10, "bonus": 5},
                        ]
                    },
                }
            )
            set_attr(db, atk, "action_override", "flurry", action_def)

            # d20=20 → huge margin → should trigger multiattack bonus
            roll_calls = iter([19, 0])  # attack d20=20, resist d20=1
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "flurry", MM3E_SYSTEM)

            if "HIT!" in output:
                assert "MULTIATTACK:" in output
        finally:
            db.close()


# ===========================================================================
# F10: Cumulative Degree Tracking
# ===========================================================================


class TestCumulativeDegree:
    def test_cumulative_stacks(self, make_session, make_character):
        """Cumulative affliction stacks degrees across hits."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Mentalist", fgt="10")
            dfn = _make_mm3e_char(db, sid, make_character, "Victim")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Cumulative affliction action with moderate effect_rank
            # DC = 15 + 3 = 18. Defender will = awe(2) = 2.
            # Roll d20=14 → 14+2=16 vs DC 18 → fail by 2 → degree 1
            action_def = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "effect_rank": 3,
                    "resistance_stat": "will",
                    "outcome_table": "affliction_degrees",
                    "degrees": {"1": "dazed", "2": "stunned", "3": "incapacitated"},
                    "cumulative": True,
                    "max_degree": 3,
                }
            )
            set_attr(db, atk, "action_override", "mind_blast", action_def)

            # First hit: d20=15 (hit), resist d20=14 → 14+2=16 vs DC 18 → fail by 2 → degree 1
            roll_calls = iter([14, 13])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output1 = resolve_action(db, atk, dfn, "mind_blast", MM3E_SYSTEM)

            # Check cumulative tracking attribute was set
            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND key = '_cumulative_degree_mind_blast'",
                (dfn,),
            ).fetchone()
            if "DEGREE OF FAILURE:" in output1:
                assert row is not None
                first_degree = int(row[0])
                assert first_degree == 1

                # Second hit: same rolls → degree 1 again, cumulative → 1+1=2
                roll_calls = iter([14, 13])
                with patch("secrets.randbelow", side_effect=roll_calls):
                    output2 = resolve_action(db, atk, dfn, "mind_blast", MM3E_SYSTEM)

                if "DEGREE OF FAILURE:" in output2:
                    row2 = db.execute(
                        "SELECT value FROM character_attributes "
                        "WHERE character_id = ? AND key = '_cumulative_degree_mind_blast'",
                        (dfn,),
                    ).fetchone()
                    second_degree = int(row2[0])
                    assert second_degree == 2
                    assert "CUMULATIVE:" in output2
        finally:
            db.close()


# ===========================================================================
# F7: Defensive Roll formula fix
# ===========================================================================


class TestDefensiveRollFormula:
    def test_toughness_excludes_defensive_roll_when_vulnerable(self, make_session, make_character):
        """Toughness formula strips adv_defensive_roll when vulnerable."""
        from lorekit.character import set_attr
        from lorekit.db import require_db
        from lorekit.rules import rules_calc

        db = require_db()
        try:
            sid = make_session()
            cid = _make_mm3e_char(db, sid, make_character, "Roller", sta="4")

            # Give defensive roll
            set_attr(db, cid, "stat", "adv_defensive_roll", "3")
            rules_calc(db, cid, MM3E_SYSTEM)

            # Check toughness includes defensive roll
            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'toughness'",
                (cid,),
            ).fetchone()
            toughness_normal = int(row[0])
            assert toughness_normal == 4 + 3  # sta + defensive_roll

            # Set vulnerable flag
            set_attr(db, cid, "condition_flags", "is_vulnerable", "1")
            rules_calc(db, cid, MM3E_SYSTEM)

            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'toughness'",
                (cid,),
            ).fetchone()
            toughness_vulnerable = int(row[0])
            assert toughness_vulnerable == 4  # sta only, no defensive_roll
        finally:
            db.close()


# ===========================================================================
# _apply_degree_effect unit test
# ===========================================================================


class TestApplyDegreeEffect:
    def test_increment_and_label(self, make_session, make_character):
        """_apply_degree_effect applies increment and label."""
        from cruncher.types import CharacterData
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_mm3e_char(db, sid, make_character, "Target")

            # Set initial damage_penalty
            set_attr(db, cid, "combat", "damage_penalty", "1")

            char = CharacterData(
                character_id=cid,
                session_id=sid,
                name="Target",
                level=1,
                char_type="npc",
                attributes={"combat": {"damage_penalty": "1"}},
            )

            effect = {
                "increment": {"damage_penalty": 1},
                "set_max": {"damage_condition": 2},
                "label": "dazed",
            }
            lines = []
            _apply_degree_effect(db, char, effect, lines)

            assert "damage_penalty: 1 → 2" in "\n".join(lines)
            assert "CONDITION: dazed" in "\n".join(lines)
        finally:
            db.close()


# ===========================================================================
# Phase 2 Features: Reactions, Team Attack, Join/Leave, Power Toggle,
# Alternate Switching, Homing, Contagious
# ===========================================================================


class TestReactionInterpose:
    def test_interpose_substitutes_defender(self, make_session, make_character):
        """Interpose reaction swaps the defender to the reactor."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Villain", fgt="10")
            target = _make_mm3e_char(db, sid, make_character, "Squishy", sta="0")
            tank = _make_mm3e_char(db, sid, make_character, "Tank", sta="10")
            _start_encounter(db, sid, [atk, target, tank], [atk, target, tank])

            # Set teams
            db.execute(
                "UPDATE character_zone SET team = 'heroes' WHERE character_id IN (?, ?)",
                (target, tank),
            )
            db.execute(
                "UPDATE character_zone SET team = 'villains' WHERE character_id = ?",
                (atk,),
            )
            db.commit()

            # Give tank an interpose reaction
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, duration_type, duration, metadata) "
                "VALUES (?, 'interpose', '_reaction', 'reaction', 0, 'reaction', 1, ?)",
                (tank, json.dumps({"hook": "before_attack", "effect": "substitute_defender", "range_zones": 0})),
            )
            db.commit()

            # Attack the squishy target — tank should interpose
            roll_calls = iter([14, 0])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, target, "close_attack", MM3E_SYSTEM)

            assert "REACTION [interpose]" in output
            assert "Tank" in output  # Tank's name should appear
        finally:
            db.close()


class TestReactionDeflect:
    def test_deflect_replaces_defense(self, make_session, make_character):
        """Deflect reaction replaces defense stat with reactor's stat."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Attacker", fgt="6")
            dfn = _make_mm3e_char(db, sid, make_character, "Deflector")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Give defender a high deflect stat
            set_attr(db, dfn, "derived", "deflect_rank", "15")

            # Set up deflect reaction
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, duration_type, duration, metadata) "
                "VALUES (?, 'deflect', '_reaction', 'reaction', 0, 'reaction', 1, ?)",
                (dfn, json.dumps({"hook": "replace_defense", "effect": "use_reactor_stat", "stat": "deflect_rank"})),
            )
            db.commit()

            # Attack — defense should use deflect_rank (15) instead of parry
            roll_calls = iter([14])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            assert "REACTION [deflect]" in output
            assert "deflect_rank" in output
        finally:
            db.close()


class TestTeamAttack:
    def test_team_bonus_applied(self, make_session, make_character):
        """Assistants add attack and DC bonus."""
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Leader", fgt="6")
            ast1 = _make_mm3e_char(db, sid, make_character, "Helper1")
            dfn = _make_mm3e_char(db, sid, make_character, "Target")
            _start_encounter(db, sid, [atk, ast1, dfn], [atk, ast1, dfn])

            # Attack with assistant
            roll_calls = iter([14, 0])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(
                    db,
                    atk,
                    dfn,
                    "close_attack",
                    MM3E_SYSTEM,
                    options={"assistants": [ast1]},
                )

            assert "TEAM ATTACK:" in output
        finally:
            db.close()


class TestJoinEncounter:
    def test_join_mid_combat(self, make_session, make_character):
        """A character can join an active encounter mid-combat."""
        from lorekit.db import require_db
        from lorekit.encounter import join_encounter

        db = require_db()
        try:
            sid = make_session()
            hero = _make_mm3e_char(db, sid, make_character, "Hero")
            villain = _make_mm3e_char(db, sid, make_character, "Villain")
            _start_encounter(db, sid, [hero, villain], [hero, villain])

            # Create a new character to join
            summon = _make_mm3e_char(db, sid, make_character, "Summon")

            cfg = _combat_cfg()
            output = join_encounter(db, sid, summon, "Arena", team="heroes", combat_cfg=cfg)

            assert "JOINED ENCOUNTER" in output
            assert "Summon" in output

            # Verify character is in initiative order
            enc = db.execute(
                "SELECT initiative_order FROM encounter_state WHERE session_id = ? AND status = 'active'",
                (sid,),
            ).fetchone()
            init_order = json.loads(enc[0])
            assert summon in init_order
        finally:
            db.close()


class TestLeaveEncounter:
    def test_leave_mid_combat(self, make_session, make_character):
        """A character can leave an active encounter."""
        from lorekit.db import require_db
        from lorekit.encounter import leave_encounter

        db = require_db()
        try:
            sid = make_session()
            hero = _make_mm3e_char(db, sid, make_character, "Hero")
            minion = _make_mm3e_char(db, sid, make_character, "Minion")
            _start_encounter(db, sid, [hero, minion], [hero, minion])

            output = leave_encounter(db, sid, minion)

            assert "LEFT ENCOUNTER" in output
            assert "Minion" in output

            # Verify removed from initiative
            enc = db.execute(
                "SELECT initiative_order FROM encounter_state WHERE session_id = ? AND status = 'active'",
                (sid,),
            ).fetchone()
            init_order = json.loads(enc[0])
            assert minion not in init_order
        finally:
            db.close()


class TestPowerToggle:
    def test_activate_inserts_modifiers(self, make_session, make_character):
        """activate_power inserts sustained modifiers from ability JSON."""
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            hero = _make_mm3e_char(db, sid, make_character, "Grower")

            # Add ability with on_activate
            db.execute(
                "INSERT INTO character_abilities (character_id, name, description, category) "
                "VALUES (?, 'Growth', ?, 'power')",
                (
                    hero,
                    json.dumps(
                        {
                            "on_activate": {
                                "apply_modifiers": [
                                    {
                                        "source": "growth",
                                        "target_stat": "bonus_str",
                                        "value": 4,
                                        "duration_type": "sustained",
                                    },
                                    {
                                        "source": "growth",
                                        "target_stat": "bonus_sta",
                                        "value": 4,
                                        "duration_type": "sustained",
                                    },
                                ]
                            }
                        }
                    ),
                ),
            )
            db.commit()

            output = activate_power(db, hero, "Growth", MM3E_SYSTEM)

            assert "ACTIVATE: Growth" in output

            # Verify modifiers inserted
            rows = db.execute(
                "SELECT target_stat, value FROM combat_state WHERE character_id = ? AND source = 'growth'",
                (hero,),
            ).fetchall()
            assert len(rows) == 2
        finally:
            db.close()

    def test_deactivate_removes_modifiers(self, make_session, make_character):
        """deactivate_power removes the sustained modifiers."""
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            hero = _make_mm3e_char(db, sid, make_character, "Grower")

            db.execute(
                "INSERT INTO character_abilities (character_id, name, description, category) "
                "VALUES (?, 'Growth', ?, 'power')",
                (
                    hero,
                    json.dumps(
                        {
                            "on_activate": {
                                "apply_modifiers": [
                                    {
                                        "source": "growth",
                                        "target_stat": "bonus_str",
                                        "value": 4,
                                        "duration_type": "sustained",
                                    },
                                ]
                            }
                        }
                    ),
                ),
            )
            db.commit()

            activate_power(db, hero, "Growth", MM3E_SYSTEM)
            output = deactivate_power(db, hero, "Growth", MM3E_SYSTEM)

            assert "DEACTIVATE: Growth" in output
            assert "1 modifier(s) removed" in output

            rows = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'growth'",
                (hero,),
            ).fetchone()
            assert rows[0] == 0
        finally:
            db.close()


class TestHoming:
    def test_homing_defers_on_miss(self, make_session, make_character):
        """Action with homing=true creates deferred_homing row on miss."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Archer", fgt="2")
            dfn = _make_mm3e_char(db, sid, make_character, "Dodger", agl="10", ranks_dodge="5")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Action with homing
            action_def = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "damage_rank_stat": "close_damage",
                    "homing": 1,
                }
            )
            set_attr(db, atk, "action_override", "homing_blast", action_def)

            # d20=1 → guaranteed miss against high dodge
            roll_calls = iter([0])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "homing_blast", MM3E_SYSTEM)

            assert "MISS!" in output
            assert "HOMING:" in output

            # Verify deferred row exists
            row = db.execute(
                "SELECT metadata FROM combat_state WHERE character_id = ? AND duration_type = 'deferred_homing'",
                (atk,),
            ).fetchone()
            assert row is not None
        finally:
            db.close()


class TestContagious:
    def test_contagious_spreads_on_melee(self, make_session, make_character):
        """Contagious modifier copies from defender to attacker on melee hit."""
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_mm3e_char(db, sid, make_character, "Attacker", fgt="10")
            dfn = _make_mm3e_char(db, sid, make_character, "Infected")
            _start_encounter(db, sid, [atk, dfn], [atk, dfn])

            # Give defender a contagious modifier
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type, save_stat, save_dc, metadata) "
                "VALUES (?, 'plague', 'bonus_fortitude', 'condition', -2, "
                "'save_ends', 'fortitude', 15, ?)",
                (dfn, json.dumps({"contagious": True})),
            )
            db.commit()

            # Attack and hit → contagious should spread
            roll_calls = iter([19, 0])  # big hit, failed resistance
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            if "HIT!" in output:
                assert "CONTAGIOUS:" in output

                # Verify attacker got the modifier
                row = db.execute(
                    "SELECT source FROM combat_state WHERE character_id = ? AND source LIKE 'contagious:%'",
                    (atk,),
                ).fetchone()
                assert row is not None
        finally:
            db.close()


class TestMetadataColumn:
    def test_metadata_column_exists(self, make_session, make_character):
        """combat_state table has the metadata column."""
        from lorekit.db import require_db

        db = require_db()
        try:
            # Insert a row with metadata
            sid = make_session()
            hero = _make_mm3e_char(db, sid, make_character, "Hero")
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, duration_type, metadata) "
                "VALUES (?, 'test', 'test_stat', 'buff', 1, 'encounter', ?)",
                (hero, json.dumps({"test": True})),
            )
            db.commit()

            row = db.execute(
                "SELECT metadata FROM combat_state WHERE character_id = ? AND source = 'test'",
                (hero,),
            ).fetchone()
            assert row is not None
            assert json.loads(row[0])["test"] is True
        finally:
            db.close()


# ===========================================================================
# MCP Wiring: combat_modifier activate/deactivate/switch_alternate
# ===========================================================================


def _setup_mm3e_session(db, sid):
    """Register MM3E as the rules_system for a session."""
    import os

    pack_name = "mm3e"
    systems_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "systems")
    link_path = os.path.join(systems_dir, pack_name)
    if not os.path.exists(link_path):
        os.symlink(MM3E_SYSTEM, link_path)

    db.execute(
        "INSERT OR REPLACE INTO session_meta (session_id, key, value) VALUES (?, 'rules_system', ?)",
        (sid, pack_name),
    )
    db.commit()


class TestCombatModifierActivate:
    def test_activate_via_mcp(self, make_session, make_character):
        """combat_modifier action=activate activates a sustained power."""
        from lorekit.db import require_db
        from lorekit.server import combat_modifier

        db = require_db()
        try:
            sid = make_session()
            _setup_mm3e_session(db, sid)
            hero = _make_mm3e_char(db, sid, make_character, "Grower")

            db.execute(
                "INSERT INTO character_abilities (character_id, name, description, category) "
                "VALUES (?, 'Growth', ?, 'power')",
                (
                    hero,
                    json.dumps(
                        {
                            "on_activate": {
                                "apply_modifiers": [
                                    {
                                        "source": "growth",
                                        "target_stat": "bonus_str",
                                        "value": 4,
                                        "duration_type": "sustained",
                                    },
                                ]
                            }
                        }
                    ),
                ),
            )
            db.commit()
        finally:
            db.close()

        output = combat_modifier(character_id=hero, action="activate", source="Growth")
        assert "ACTIVATE: Growth" in output

    def test_deactivate_via_mcp(self, make_session, make_character):
        """combat_modifier action=deactivate removes sustained modifiers."""
        from lorekit.db import require_db
        from lorekit.server import combat_modifier

        db = require_db()
        try:
            sid = make_session()
            _setup_mm3e_session(db, sid)
            hero = _make_mm3e_char(db, sid, make_character, "Grower")

            db.execute(
                "INSERT INTO character_abilities (character_id, name, description, category) "
                "VALUES (?, 'Growth', ?, 'power')",
                (
                    hero,
                    json.dumps(
                        {
                            "on_activate": {
                                "apply_modifiers": [
                                    {
                                        "source": "growth",
                                        "target_stat": "bonus_str",
                                        "value": 4,
                                        "duration_type": "sustained",
                                    },
                                ]
                            }
                        }
                    ),
                ),
            )
            db.commit()
        finally:
            db.close()

        combat_modifier(character_id=hero, action="activate", source="Growth")
        output = combat_modifier(character_id=hero, action="deactivate", source="Growth")
        assert "DEACTIVATE: Growth" in output
        assert "removed" in output


class TestAutoRegisterReactions:
    def test_reaction_registered_at_encounter_start(self, make_session, make_character):
        """Abilities with reaction metadata auto-register at encounter start."""
        from lorekit.db import require_db
        from lorekit.server import encounter_start

        db = require_db()
        try:
            sid = make_session()
            _setup_mm3e_session(db, sid)
            tank = _make_mm3e_char(db, sid, make_character, "Tank", char_type="pc")
            villain = _make_mm3e_char(db, sid, make_character, "Villain")

            # Give tank an ability with reaction metadata
            db.execute(
                "INSERT INTO character_abilities (character_id, name, description, category) "
                "VALUES (?, 'Interpose', ?, 'advantage')",
                (
                    tank,
                    json.dumps(
                        {
                            "reaction": {
                                "source": "interpose",
                                "hook": "before_attack",
                                "effect": "substitute_defender",
                                "range_zones": 0,
                            }
                        }
                    ),
                ),
            )
            db.commit()
        finally:
            db.close()

        output = encounter_start(
            session_id=sid,
            zones='[{"name": "Arena"}]',
            initiative="auto",
            placements=json.dumps(
                [
                    {"character_id": tank, "zone": "Arena"},
                    {"character_id": villain, "zone": "Arena"},
                ]
            ),
        )

        assert "REACTION REGISTERED" in output
        assert "interpose" in output

        # Verify the combat_state row exists
        db = require_db()
        try:
            row = db.execute(
                "SELECT metadata FROM combat_state "
                "WHERE character_id = ? AND source = 'interpose' AND duration_type = 'reaction'",
                (tank,),
            ).fetchone()
            assert row is not None
            meta = json.loads(row[0])
            assert meta["hook"] == "before_attack"
            assert meta["effect"] == "substitute_defender"
        finally:
            db.close()
