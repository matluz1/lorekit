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
        "str": "18",
        "dex": "14",
        "con": "12",
        "base_attack": "5",
        "hit_die_avg": "6",
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
                ("fgt", "6"),
                ("agl", "2"),
                ("dex", "0"),
                ("str", "6"),
                ("sta", "4"),
                ("int", "0"),
                ("awe", "2"),
                ("pre", "0"),
            ]:
                set_attr(db, atk_id, "stat", key, val)
            # Run calc to get derived
            from rules_engine import rules_calc

            rules_calc(db, atk_id, MM3E_SYSTEM)

            # Set up defender stats
            for key, val in [
                ("fgt", "4"),
                ("agl", "4"),
                ("dex", "0"),
                ("str", "2"),
                ("sta", "4"),
                ("int", "0"),
                ("awe", "2"),
                ("pre", "0"),
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
                ("fgt", "6"),
                ("agl", "2"),
                ("dex", "0"),
                ("str", "6"),
                ("sta", "4"),
                ("int", "0"),
                ("awe", "2"),
                ("pre", "0"),
            ]:
                set_attr(db, atk_id, "stat", key, val)
            from rules_engine import rules_calc

            rules_calc(db, atk_id, MM3E_SYSTEM)

            for key, val in [
                ("fgt", "4"),
                ("agl", "4"),
                ("dex", "0"),
                ("str", "2"),
                ("sta", "8"),
                ("int", "0"),
                ("awe", "2"),
                ("pre", "0"),
                ("ranks_parry", "2"),
                ("ranks_toughness", "4"),
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
        from _db import LoreKitError, require_db
        from character import set_attr

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "A")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "B")

            with pytest.raises(LoreKitError, match="Unknown action"):
                resolve_action(db, atk_id, def_id, "dragon_breath", TEST_SYSTEM)
        finally:
            db.close()


class TestRangeValidation:
    def test_melee_out_of_range_rejected(self, make_session, make_character):
        """Melee attack across zones is rejected when encounter is active."""
        from _db import LoreKitError, require_db
        from character import set_attr
        from encounter import start_encounter

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Defender")
            set_attr(db, def_id, "combat", "current_hp", "35")

            # Start encounter with characters in different zones
            start_encounter(
                db,
                atk_id and db.execute("SELECT session_id FROM characters WHERE id = ?", (atk_id,)).fetchone()[0],
                [{"name": "Near"}, {"name": "Far"}],
                [{"character_id": atk_id, "roll": 20}, {"character_id": def_id, "roll": 10}],
                placements=[
                    {"character_id": atk_id, "zone": "Near"},
                    {"character_id": def_id, "zone": "Far"},
                ],
                combat_cfg={"zone_scale": 30, "movement_unit": "ft", "melee_range": 0, "zone_tags": {}},
            )

            with pytest.raises(LoreKitError, match="out of range"):
                resolve_action(db, atk_id, def_id, "melee_attack", TEST_SYSTEM)
        finally:
            db.close()

    def test_melee_same_zone_allowed(self, make_session, make_character):
        """Melee attack in same zone proceeds normally."""
        from unittest.mock import patch

        from _db import require_db
        from character import set_attr
        from encounter import start_encounter

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Defender")
            set_attr(db, def_id, "combat", "current_hp", "35")

            sess_id = db.execute("SELECT session_id FROM characters WHERE id = ?", (atk_id,)).fetchone()[0]

            start_encounter(
                db,
                sess_id,
                [{"name": "Arena"}],
                [{"character_id": atk_id, "roll": 20}, {"character_id": def_id, "roll": 10}],
                placements=[
                    {"character_id": atk_id, "zone": "Arena"},
                    {"character_id": def_id, "zone": "Arena"},
                ],
                combat_cfg={"zone_scale": 30, "movement_unit": "ft", "melee_range": 0, "zone_tags": {}},
            )

            roll_calls = iter([17, 5])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "melee_attack", TEST_SYSTEM)

            assert "HIT!" in output
        finally:
            db.close()


class TestMissingStats:
    def test_missing_attack_stat_raises(self, make_session, make_character):
        """Character without the required attack stat → error."""
        from _db import LoreKitError, require_db

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


class TestContestedAction:
    def test_grapple_success_applies_modifiers(self, make_session, make_character):
        """Contested grapple: attacker wins → modifiers applied via combat_state."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Grappler")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Target")

            # Attacker rolls 18, defender rolls 5 → attacker wins
            roll_calls = iter([17, 4])  # 17+1=18, 4+1=5
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "grapple", TEST_SYSTEM)

            assert "HIT!" in output
            assert "MODIFIER: grapple" in output

            # Verify combat_state row was created
            row = db.execute(
                "SELECT source, target_stat, value FROM combat_state WHERE character_id = ? AND source = 'grapple'",
                (def_id,),
            ).fetchone()
            assert row is not None
            assert row[1] == "bonus_defense"
            assert row[2] == -2
        finally:
            db.close()

    def test_grapple_failure(self, make_session, make_character):
        """Contested grapple: defender wins → no modifiers applied."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Grappler")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Target")

            # Attacker rolls 3, defender rolls 18 → defender wins
            roll_calls = iter([2, 17])  # 2+1=3, 17+1=18
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "grapple", TEST_SYSTEM)

            assert "MISS!" in output
            assert "Target resists" in output
            assert "MODIFIER" not in output
        finally:
            db.close()

    def test_no_damage_action(self, make_session, make_character):
        """Action with on_hit modifiers but no damage_roll skips damage."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Grappler")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Target")
            set_attr(db, def_id, "combat", "current_hp", "35")

            roll_calls = iter([17, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "grapple", TEST_SYSTEM)

            assert "HIT!" in output
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


class TestForcedMovement:
    def test_shove_pushes_target(self, make_session, make_character):
        """Shove action pushes target to adjacent zone on success."""
        from _db import require_db
        from character import set_attr
        from encounter import start_encounter

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Pusher")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Target")

            sess_id = db.execute("SELECT session_id FROM characters WHERE id = ?", (atk_id,)).fetchone()[0]

            start_encounter(
                db,
                sess_id,
                [{"name": "Near"}, {"name": "Mid"}, {"name": "Far"}],
                [{"character_id": atk_id, "roll": 20}, {"character_id": def_id, "roll": 10}],
                placements=[
                    {"character_id": atk_id, "zone": "Near"},
                    {"character_id": def_id, "zone": "Near"},
                ],
                combat_cfg={"zone_scale": 30, "movement_unit": "ft", "melee_range": 0, "zone_tags": {}},
            )

            # Attacker rolls 18, defender rolls 3 → attacker wins, push 30ft = 1 zone
            roll_calls = iter([17, 2])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "shove", TEST_SYSTEM)

            assert "HIT!" in output
            assert "FORCED MOVEMENT" in output
            assert "Near → Mid" in output

            # Verify target moved to Mid zone
            row = db.execute(
                "SELECT ez.name FROM character_zone cz "
                "JOIN encounter_zones ez ON ez.id = cz.zone_id "
                "WHERE cz.character_id = ?",
                (def_id,),
            ).fetchone()
            assert row[0] == "Mid"
        finally:
            db.close()

    def test_shove_out_of_range_rejected(self, make_session, make_character):
        """Shove across zones is rejected — melee requires same zone."""
        from _db import LoreKitError, require_db
        from character import set_attr
        from encounter import start_encounter

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Pusher")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Target")

            sess_id = db.execute("SELECT session_id FROM characters WHERE id = ?", (atk_id,)).fetchone()[0]

            start_encounter(
                db,
                sess_id,
                [{"name": "Near"}, {"name": "Far"}],
                [{"character_id": atk_id, "roll": 20}, {"character_id": def_id, "roll": 10}],
                placements=[
                    {"character_id": atk_id, "zone": "Near"},
                    {"character_id": def_id, "zone": "Far"},
                ],
                combat_cfg={"zone_scale": 30, "movement_unit": "ft", "melee_range": 0, "zone_tags": {}},
            )

            with pytest.raises(LoreKitError, match="out of range"):
                resolve_action(db, atk_id, def_id, "shove", TEST_SYSTEM)
        finally:
            db.close()


class TestAreaEffect:
    """Area effect resolution — hits multiple targets in zones within radius."""

    def _setup_encounter(self, db, make_session, make_character, set_attr):
        """Set up 3 fighters in a 3-zone linear encounter: Near ↔ Mid ↔ Far."""
        from encounter import start_encounter

        sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Caster")
        _, t1_id = _setup_fighter(db, make_session, make_character, set_attr, "Target1")
        _, t2_id = _setup_fighter(db, make_session, make_character, set_attr, "Target2")
        set_attr(db, t1_id, "combat", "current_hp", "35")
        set_attr(db, t2_id, "combat", "current_hp", "35")

        sess_id = db.execute("SELECT session_id FROM characters WHERE id = ?", (atk_id,)).fetchone()[0]

        start_encounter(
            db,
            sess_id,
            [{"name": "Near"}, {"name": "Mid"}, {"name": "Far"}],
            [
                {"character_id": atk_id, "roll": 20},
                {"character_id": t1_id, "roll": 15},
                {"character_id": t2_id, "roll": 10},
            ],
            placements=[
                {"character_id": atk_id, "zone": "Near"},
                {"character_id": t1_id, "zone": "Mid"},
                {"character_id": t2_id, "zone": "Far"},
            ],
            combat_cfg={"zone_scale": 30, "movement_unit": "ft", "melee_range": 0, "zone_tags": {}},
        )
        return sess_id, atk_id, t1_id, t2_id

    def test_area_radius0_hits_center_zone_only(self, make_session, make_character):
        """radius=0 only hits characters in the center zone."""
        from _db import require_db
        from character import set_attr
        from combat_engine import resolve_area_action

        db = require_db()
        try:
            sid, atk_id, t1_id, t2_id = self._setup_encounter(
                db,
                make_session,
                make_character,
                set_attr,
            )

            # Mock: attack roll + damage roll for one target
            roll_calls = iter([17, 5])  # hit, damage
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_area_action(
                    db,
                    atk_id,
                    "fireball",
                    TEST_SYSTEM,
                    center_zone="Mid",
                    radius=0,
                )

            assert "Target1" in output
            assert "Target2" not in output
            assert "HIT!" in output
        finally:
            db.close()

    def test_area_radius1_hits_adjacent_zones(self, make_session, make_character):
        """radius=1 hits center + adjacent zones."""
        from _db import require_db
        from character import set_attr
        from combat_engine import resolve_area_action

        db = require_db()
        try:
            sid, atk_id, t1_id, t2_id = self._setup_encounter(
                db,
                make_session,
                make_character,
                set_attr,
            )

            # Mock: 2 targets × (attack roll + damage roll)
            roll_calls = iter([17, 5, 17, 5])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_area_action(
                    db,
                    atk_id,
                    "fireball",
                    TEST_SYSTEM,
                    center_zone="Mid",
                    radius=1,
                )

            # Both targets hit (attacker excluded by default)
            assert "Target1" in output
            assert "Target2" in output
            # Caster appears as attacker but never as defender
            assert "→ Caster" not in output
        finally:
            db.close()

    def test_area_attacker_excluded_by_default(self, make_session, make_character):
        """Attacker is excluded from area targets by default."""
        from _db import require_db
        from character import set_attr
        from combat_engine import resolve_area_action

        db = require_db()
        try:
            sid, atk_id, t1_id, t2_id = self._setup_encounter(
                db,
                make_session,
                make_character,
                set_attr,
            )

            # Center on attacker's zone (Near), radius=0
            roll_calls = iter([])  # no targets expected
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_area_action(
                    db,
                    atk_id,
                    "fireball",
                    TEST_SYSTEM,
                    center_zone="self",
                    radius=0,
                )

            assert "no targets" in output
        finally:
            db.close()

    def test_area_center_self_uses_attacker_zone(self, make_session, make_character):
        """center='self' uses the attacker's zone."""
        from _db import require_db
        from character import set_attr
        from combat_engine import resolve_area_action

        db = require_db()
        try:
            sid, atk_id, t1_id, t2_id = self._setup_encounter(
                db,
                make_session,
                make_character,
                set_attr,
            )

            # Center on self (Near), radius=1 reaches Mid (Target1)
            roll_calls = iter([17, 5])  # one target
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_area_action(
                    db,
                    atk_id,
                    "fireball",
                    TEST_SYSTEM,
                    center_zone="self",
                    radius=1,
                )

            assert "Target1" in output
            assert "Target2" not in output  # Far is 2 hops from Near
        finally:
            db.close()

    def test_area_no_encounter_raises(self, make_session, make_character):
        """Area effect without an active encounter raises an error."""
        from _db import LoreKitError, require_db
        from character import set_attr
        from combat_engine import resolve_area_action

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Caster")

            with pytest.raises(LoreKitError, match="No active encounter"):
                resolve_area_action(
                    db,
                    atk_id,
                    "fireball",
                    TEST_SYSTEM,
                    center_zone="Mid",
                    radius=1,
                )
        finally:
            db.close()

    def test_area_empty_no_targets(self, make_session, make_character):
        """Area with no targets returns a clean message."""
        from _db import require_db
        from character import set_attr
        from combat_engine import resolve_area_action
        from encounter import start_encounter

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Caster")

            sess_id = db.execute("SELECT session_id FROM characters WHERE id = ?", (atk_id,)).fetchone()[0]

            start_encounter(
                db,
                sess_id,
                [{"name": "Near"}, {"name": "Far"}],
                [{"character_id": atk_id, "roll": 20}],
                placements=[{"character_id": atk_id, "zone": "Near"}],
                combat_cfg={"zone_scale": 30, "movement_unit": "ft", "melee_range": 0, "zone_tags": {}},
            )

            output = resolve_area_action(
                db,
                atk_id,
                "fireball",
                TEST_SYSTEM,
                center_zone="Far",
                radius=0,
            )
            assert "no targets" in output
        finally:
            db.close()


class TestDegreeOnHit:
    def test_mm3e_grab_applies_modifiers(self, make_session, make_character):
        """M&M3e grab: degree action with on_hit modifiers (no resistance check)."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid = make_session()
            atk_id = make_character(sid, name="Hero", level=1)
            def_id = make_character(sid, name="Villain", level=1)

            for key, val in [
                ("fgt", "6"),
                ("agl", "2"),
                ("dex", "0"),
                ("str", "6"),
                ("sta", "4"),
                ("int", "0"),
                ("awe", "2"),
                ("pre", "0"),
            ]:
                set_attr(db, atk_id, "stat", key, val)
            from rules_engine import rules_calc

            rules_calc(db, atk_id, MM3E_SYSTEM)

            for key, val in [
                ("fgt", "4"),
                ("agl", "4"),
                ("dex", "0"),
                ("str", "2"),
                ("sta", "4"),
                ("int", "0"),
                ("awe", "2"),
                ("pre", "0"),
                ("ranks_parry", "2"),
            ]:
                set_attr(db, def_id, "stat", key, val)
            rules_calc(db, def_id, MM3E_SYSTEM)

            # Attack roll=15 + close_attack(6) = 21 vs DC 10+parry(6) = 16 → HIT
            # No damage_rank_stat → on_hit effects applied directly (no resistance check)
            roll_calls = iter([14])  # 14+1=15
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "grab", MM3E_SYSTEM)

            assert "HIT!" in output
            assert "MODIFIER: grab" in output
            assert "RESISTANCE:" not in output

            # Verify combat_state modifiers applied
            rows = db.execute(
                "SELECT source, target_stat, value FROM combat_state WHERE character_id = ? AND source = 'grab'",
                (def_id,),
            ).fetchall()
            assert len(rows) == 2
            stats = {r[1] for r in rows}
            assert "bonus_dodge" in stats
            assert "bonus_speed" in stats
        finally:
            db.close()
