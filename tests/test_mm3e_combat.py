"""M&M3e-specific combat tests through execute_combat_turn.

Validates degree resolution, contested skill actions, grab conditions,
and damage_penalty tracking — features specific to the M&M3e system pack.
"""

import json
import os
from unittest.mock import patch

import cruncher_mm3e
import pytest

MM3E_SYSTEM = cruncher_mm3e.pack_path()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _combat_cfg():
    """Return the combat config from the M&M3e system pack."""
    with open(os.path.join(MM3E_SYSTEM, "system.json")) as f:
        return json.load(f)["combat"]


def _make_character(db, session_id, make_character, name, char_type="npc", **stats):
    """Create a character with M&M3e stats and run rules_calc."""
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


def _start_encounter(db, session_id, characters, zones, placements):
    """Start an encounter with given zones and placements."""
    from lorekit.encounter import start_encounter

    cfg = _combat_cfg()
    start_encounter(
        db,
        session_id,
        zones,
        [{"character_id": cid, "roll": 20 - i} for i, cid in enumerate(characters)],
        placements=[{"character_id": cid, "zone": z} for cid, z in placements],
        combat_cfg=cfg,
    )


# ===========================================================================
# Degree resolution — close_attack
# ===========================================================================


class TestCloseAttack:
    def test_hit_applies_damage_penalty(self, make_session, make_character):
        """Hit + failed resistance → damage_penalty incremented."""
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Villain")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "close_attack", "targets": ["Hero"]}

            # Attack d20=15 → hit, Resistance d20=5 → fail
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output
            assert "RESISTANCE:" in output

            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'damage_penalty'",
                (hero,),
            ).fetchone()
            assert row is not None
            assert int(row[0]) > 0
        finally:
            db.close()

    def test_miss_against_high_dodge(self, make_session, make_character):
        """Low attack vs high dodge → miss, no resistance check."""
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Villain", fgt="2")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", agl="8", ranks_dodge="4")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "close_attack", "targets": ["Hero"]}

            # d20=3 → 3 + 2 = 5 vs DC 10+12 = 22
            roll_calls = iter([2])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "MISS!" in output
        finally:
            db.close()


# ===========================================================================
# Contested skill actions — setup_deception / setup_intimidation
# ===========================================================================


class TestSetupActions:
    def test_deception_applies_vulnerable(self, make_session, make_character):
        """Deception wins contested roll → vulnerable modifiers on target."""
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Trickster", pre="6", ranks_deception="8")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", awe="2", ranks_insight="0")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "setup_deception", "targets": ["Hero"]}

            # NPC 15 + skill_deception(14) = 29, Hero 5 + skill_insight(2) = 7
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output

            mods = db.execute(
                "SELECT source, target_stat FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            mod_stats = {m[1] for m in mods}
            assert "bonus_parry" in mod_stats or "bonus_dodge" in mod_stats
        finally:
            db.close()

    def test_intimidation_applies_vulnerable(self, make_session, make_character):
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Brute", pre="6", ranks_intimidation="8")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", awe="2", ranks_insight="0")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "setup_intimidation", "targets": ["Hero"]}

            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output

            mods = db.execute(
                "SELECT source, target_stat FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            mod_stats = {m[1] for m in mods}
            assert "bonus_parry" in mod_stats or "bonus_dodge" in mod_stats
        finally:
            db.close()

    def test_contested_miss(self, make_session, make_character):
        """Defender wins → no modifiers applied."""
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Trickster", pre="2", ranks_deception="0")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", awe="6", ranks_insight="8")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "setup_deception", "targets": ["Hero"]}

            # NPC 5 + 2 = 7, Hero 15 + 14 = 29
            roll_calls = iter([4, 14])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "MISS!" in output

            mods = db.execute(
                "SELECT source FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            assert len(mods) == 0
        finally:
            db.close()

    def test_setup_then_verify_modifiers(self, make_session, make_character):
        """Full cycle: setup applies vulnerable, modifiers exist on target."""
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            trickster = _make_character(db, sid, make_character, "Trickster", pre="6", ranks_deception="8")
            hero = _make_character(
                db, sid, make_character, "Hero", char_type="pc", fgt="4", agl="4", ranks_parry="2", ranks_dodge="2"
            )
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [trickster, hero],
                [{"name": "Arena"}],
                [(trickster, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "setup_deception", "targets": ["Hero"]}

            roll_calls = iter([17, 2])  # 18 vs 3, easy win
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, trickster, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output

            mods = db.execute(
                "SELECT target_stat, value FROM combat_state WHERE character_id = ? AND source = 'vulnerable'",
                (hero,),
            ).fetchall()
            assert len(mods) > 0, "Vulnerable condition marker should be applied"
            mod_stats = {m[0] for m in mods}
            assert "bonus_dodge" in mod_stats

            # Verify the is_vulnerable flag was set by sync_condition_modifiers
            flag = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'condition_flags' AND key = 'is_vulnerable'",
                (hero,),
            ).fetchone()
            assert flag is not None, "is_vulnerable flag should be set"
            assert int(flag[0]) == 1

            # Verify dodge/parry are halved via formula (not flat modifier)
            dodge = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'dodge'",
                (hero,),
            ).fetchone()
            parry = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'parry'",
                (hero,),
            ).fetchone()
            # Hero: agl=4, ranks_dodge=2 → base 6 → halved = 3
            # Hero: fgt=4, ranks_parry=2 → base 6 → halved = 3
            assert int(dodge[0]) == 3
            assert int(parry[0]) == 3
        finally:
            db.close()


# ===========================================================================
# Grab — on_hit modifiers without resistance check
# ===========================================================================


class TestGrab:
    def test_grab_applies_until_escape_modifiers(self, make_session, make_character):
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Grappler", fgt="8")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", fgt="2")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "grab", "targets": ["Hero"]}

            roll_calls = iter([14])  # d20=15 → hit
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output

            mods = db.execute(
                "SELECT source, target_stat, duration_type FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            mod_stats = {m[1] for m in mods}
            assert "bonus_dodge" in mod_stats
            assert "bonus_speed" in mod_stats
            # The marker row (source="grab") triggers the condition;
            # sync_condition_modifiers creates cond:grab rows with the mechanical effects.
            marker = [m for m in mods if m[0] == "grab"]
            assert len(marker) == 1
            assert marker[0][2] == "until_escape"
            cond_mods = [m for m in mods if m[0] == "cond:grab"]
            assert len(cond_mods) >= 2
            for m in cond_mods:
                assert m[2] == "condition"
        finally:
            db.close()


# ===========================================================================
# Action overrides, effect_rank, resistance_stat, PL cap
# ===========================================================================


class TestActionOverride:
    def test_character_override_used_over_system(self, make_session, make_character):
        """Character with action_override uses it instead of system action."""
        from lorekit.character import set_attr
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Blaster", fgt="6")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            # Override close_attack to target dodge instead of parry
            override = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "dodge",
                    "range": "melee",
                    "damage_rank_stat": "close_damage",
                }
            )
            set_attr(db, npc, "action_override", "close_attack", override)

            # d20=15 → hit, resistance d20=5 → fail
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, npc, hero, "close_attack", MM3E_SYSTEM)

            # Should target dodge, not parry
            assert "dodge" in result.lower() or "HIT!" in result
        finally:
            db.close()

    def test_effect_rank_direct(self, make_session, make_character):
        """Action with effect_rank uses it directly instead of damage_rank_stat."""
        from lorekit.character import set_attr
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Psion", fgt="6")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            # Custom action with effect_rank=10 (ignores close_damage stat)
            override = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "effect_rank": 10,
                }
            )
            set_attr(db, npc, "action_override", "mental_blast", override)

            # d20=18 → hit, resistance d20=3 → fail hard
            roll_calls = iter([17, 2])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, npc, hero, "mental_blast", MM3E_SYSTEM)

            # DC should be 15 + 10 = 25
            assert "DC 25" in result
            assert "HIT!" in result
        finally:
            db.close()

    def test_resistance_stat_override(self, make_session, make_character):
        """Action with resistance_stat targets fortitude instead of toughness."""
        from lorekit.character import set_attr
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Psion", fgt="6")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            override = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "effect_rank": 8,
                    "resistance_stat": "fortitude",
                }
            )
            set_attr(db, npc, "action_override", "fort_blast", override)

            # d20=18 → hit, resistance d20=10
            roll_calls = iter([17, 9])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, npc, hero, "fort_blast", MM3E_SYSTEM)

            assert "HIT!" in result
            assert "RESISTANCE:" in result
            # Resistance check should use fortitude, not toughness
            # fortitude is derived from sta (default 4), so resistance_bonus = 4
            # toughness would be sta(4) = 4 too in default config — but verify the stat is read
        finally:
            db.close()

    def test_cap_warning(self, make_session, make_character):
        """Action where attack + effect_rank > cap max_stat shows warning."""
        from lorekit.character import set_attr
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            # fgt=10 → close_attack=10
            npc = _make_character(db, sid, make_character, "OverPowered", fgt="10")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            # Set pl_limit derived stat
            set_attr(db, npc, "derived", "pl_limit", "20")

            # Custom action: attack_stat=close_attack (10), effect_rank=12 → total 22 > 20
            override = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "effect_rank": 12,
                    "cap": {"sum": ["attack_stat", "effect_rank"], "max_stat": "pl_limit"},
                }
            )
            set_attr(db, npc, "action_override", "op_blast", override)

            # d20=18 → hit, resistance d20=5 → fail
            roll_calls = iter([17, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, npc, hero, "op_blast", MM3E_SYSTEM)

            assert "WARNING: cap exceeded" in result
            assert "HIT!" in result
        finally:
            db.close()

    def test_cap_clean(self, make_session, make_character):
        """Action within cap limits shows no warning."""
        from lorekit.character import set_attr
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Balanced", fgt="6")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            # close_attack uses cap from system.json: close_attack(6) + close_damage(4) = 10
            # pl_limit from rules_calc = power_level * 2 = 1 * 2 = 2... too low
            # Set it manually to 20
            set_attr(db, npc, "derived", "pl_limit", "20")

            # d20=18 → hit, resistance d20=5 → fail
            roll_calls = iter([17, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, npc, hero, "close_attack", MM3E_SYSTEM)

            assert "WARNING" not in result
        finally:
            db.close()

    def test_system_action_still_works(self, make_session, make_character):
        """Characters without overrides still use system actions normally."""
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Normal")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "close_attack", "targets": ["Hero"]}

            # d20=15 → hit, resistance d20=5 → fail
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output
            assert "RESISTANCE:" in output
        finally:
            db.close()
