"""Tests for the combat resolution engine."""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from combat_engine import resolve_action

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")
MM3E_SYSTEM = os.path.join(os.path.dirname(__file__), "..", "systems", "mm3e")


def _setup_fighter(db, make_session, make_character, set_attr, name, **overrides):
    """Create a character with basic combat stats for the test system."""
    sid = make_session()
    cid = make_character(sid, name=name, level=5)
    defaults = {
        "str": "18", "dex": "14", "con": "12",
        "base_attack": "5", "hit_die_avg": "6",
    }
    defaults.update(overrides)

    for key, val in defaults.items():
        set_attr(db, cid, "stat", key, val)

    set_attr(db, cid, "combat", "base_attack", defaults.get("base_attack", "5"))
    set_attr(db, cid, "combat", "hit_die_avg", defaults.get("hit_die_avg", "6"))

    # Run rules_calc to compute derived stats
    from rules_engine import rules_calc
    rules_calc(db, cid, TEST_SYSTEM)

    # Set weapon (build attribute)
    set_attr(db, cid, "build", "weapon_damage_die", "1d8")

    return sid, cid


class TestThresholdHit:
    def test_hit_deals_damage(self, make_session, make_character):
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Defender")

            # Set current_hp on defender
            set_attr(db, def_id, "combat", "current_hp", "35")

            # Mock: attack d20=18 (hit), damage d8=6
            roll_calls = iter([17, 5])  # randbelow: 17+1=18, 5+1=6
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "melee_attack", TEST_SYSTEM)

            assert "HIT!" in output
            assert "DAMAGE:" in output
            # attack: d20(18) + 9 = 27 vs armor_class (10 + 2 + 0 + 0 = 12)
            assert "27 vs armor_class 12" in output
            # damage: d8(6) + str_mod(4) = 10
            assert "1d8(6) + 4 = 10" in output
            # HP: 35 → 25
            assert "current_hp: 35 → 25" in output

            # Verify DB was updated
            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'combat' AND key = 'current_hp'",
                (def_id,),
            ).fetchone()
            assert row[0] == "25"
        finally:
            db.close()


class TestThresholdMiss:
    def test_miss_no_damage(self, make_session, make_character):
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Defender")
            set_attr(db, def_id, "combat", "current_hp", "35")

            # Mock: attack d20=1 (miss)
            with patch("secrets.randbelow", return_value=0):  # 0+1=1
                output = resolve_action(db, atk_id, def_id, "melee_attack", TEST_SYSTEM)

            assert "MISS!" in output
            assert "DAMAGE:" not in output

            # HP unchanged
            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'combat' AND key = 'current_hp'",
                (def_id,),
            ).fetchone()
            assert row[0] == "35"
        finally:
            db.close()


class TestThresholdHpFallback:
    def test_no_current_hp_uses_max_hp(self, make_session, make_character):
        """If current_hp doesn't exist, initialize from max_hp."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Defender")
            # Don't set current_hp — should fall back to max_hp (35)

            roll_calls = iter([17, 5])  # hit, damage 6
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "melee_attack", TEST_SYSTEM)

            assert "HIT!" in output
            # max_hp = 6*5 + 1*5 = 35, damage = 6+4 = 10 → 25
            assert "current_hp: 35 → 25" in output
        finally:
            db.close()


class TestDegreeHitResistanceFail:
    def test_degree_hit_with_resistance_failure(self, make_session, make_character):
        """M&M3e: hit + failed resistance → degree of failure with conditions."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid = make_session()
            atk_id = make_character(sid, name="Hero", level=1)
            def_id = make_character(sid, name="Villain", level=1)

            # Set up attacker stats
            for key, val in [
                ("fgt", "6"), ("agl", "2"), ("dex", "0"),
                ("str", "6"), ("sta", "4"), ("int", "0"), ("awe", "2"), ("pre", "0"),
            ]:
                set_attr(db, atk_id, "stat", key, val)
            # Run calc to get derived
            from rules_engine import rules_calc
            rules_calc(db, atk_id, MM3E_SYSTEM)

            # Set up defender stats
            for key, val in [
                ("fgt", "4"), ("agl", "4"), ("dex", "0"),
                ("str", "2"), ("sta", "4"), ("int", "0"), ("awe", "2"), ("pre", "0"),
                ("ranks_parry", "2"),
            ]:
                set_attr(db, def_id, "stat", key, val)
            rules_calc(db, def_id, MM3E_SYSTEM)

            # Mock rolls:
            # Attack d20=15 (hit): 15 + close_attack(6+0+0=6) = 21 vs DC 10+parry(4+2=6)=16 → HIT
            # Resistance d20=3: 3 + toughness(4+0+0+0+0=4) = 7 vs DC 15+unarmed_damage(6+0=6)=21
            # Degree = floor((21-7)/5) = floor(14/5) = 2 → dazed + damage_penalty
            roll_calls = iter([14, 2])  # 14+1=15, 2+1=3
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)

            assert "HIT!" in output
            assert "RESISTANCE:" in output
            assert "DEGREE OF FAILURE: 2" in output
            assert "CONDITION: dazed" in output
            assert "damage_penalty:" in output
        finally:
            db.close()


class TestDegreeNoEffect:
    def test_degree_hit_resistance_success(self, make_session, make_character):
        """M&M3e: hit but resistance succeeds → no effect."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid = make_session()
            atk_id = make_character(sid, name="Hero", level=1)
            def_id = make_character(sid, name="Villain", level=1)

            for key, val in [
                ("fgt", "6"), ("agl", "2"), ("dex", "0"),
                ("str", "6"), ("sta", "4"), ("int", "0"), ("awe", "2"), ("pre", "0"),
            ]:
                set_attr(db, atk_id, "stat", key, val)
            from rules_engine import rules_calc
            rules_calc(db, atk_id, MM3E_SYSTEM)

            for key, val in [
                ("fgt", "4"), ("agl", "4"), ("dex", "0"),
                ("str", "2"), ("sta", "8"), ("int", "0"), ("awe", "2"), ("pre", "0"),
                ("ranks_parry", "2"), ("ranks_toughness", "4"),
            ]:
                set_attr(db, def_id, "stat", key, val)
            rules_calc(db, def_id, MM3E_SYSTEM)

            # Attack d20=15 → hit
            # Resistance d20=20: 20 + toughness(8+4+0+0+0=12) = 32 vs DC 15+6=21 → SUCCESS
            roll_calls = iter([14, 19])  # 15, 20
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)

            assert "HIT!" in output
            assert "No effect" in output
        finally:
            db.close()


class TestUnknownAction:
    def test_unknown_action_raises(self, make_session, make_character):
        from _db import require_db, LoreKitError
        from character import set_attr

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "A")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "B")

            with pytest.raises(LoreKitError, match="Unknown action"):
                resolve_action(db, atk_id, def_id, "dragon_breath", TEST_SYSTEM)
        finally:
            db.close()


class TestMissingStats:
    def test_missing_attack_stat_raises(self, make_session, make_character):
        """Character without the required attack stat → error."""
        from _db import require_db, LoreKitError

        db = require_db()
        try:
            sid = make_session()
            # Create minimal character with no stats
            atk_id = make_character(sid, name="Empty", level=1)
            def_id = make_character(sid, name="Target", level=1)

            with pytest.raises(LoreKitError, match="not found"):
                resolve_action(db, atk_id, def_id, "melee_attack", TEST_SYSTEM)
        finally:
            db.close()
