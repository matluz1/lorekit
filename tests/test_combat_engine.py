"""Tests for the combat resolution engine."""

import json
import os
from unittest.mock import patch

import cruncher_mm3e
import pytest

from lorekit.combat import resolve_action, resolve_area_action

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")
MM3E_SYSTEM = cruncher_mm3e.pack_path()


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
    from lorekit.rules import rules_calc

    rules_calc(db, cid, TEST_SYSTEM)

    # Set weapon (build attribute)
    set_attr(db, cid, "build", "weapon_damage_die", "1d8")

    return sid, cid


class TestThresholdHit:
    def test_hit_deals_damage(self, make_session, make_character):
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
            from lorekit.rules import rules_calc

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
            assert "DEGREE OF FAILURE: 3" in output
            assert "CONDITION: staggered" in output
            assert "damage_penalty:" in output
        finally:
            db.close()


class TestDegreeNoEffect:
    def test_degree_hit_resistance_success(self, make_session, make_character):
        """M&M3e: hit but resistance succeeds → no effect."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
            from lorekit.rules import rules_calc

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
        from lorekit.character import set_attr
        from lorekit.db import LoreKitError, require_db

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
        from lorekit.character import set_attr
        from lorekit.db import LoreKitError, require_db
        from lorekit.encounter import start_encounter

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

        from lorekit.character import set_attr
        from lorekit.db import require_db
        from lorekit.encounter import start_encounter

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
        from lorekit.db import LoreKitError, require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db
        from lorekit.encounter import start_encounter

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
        from lorekit.character import set_attr
        from lorekit.db import LoreKitError, require_db
        from lorekit.encounter import start_encounter

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
        from lorekit.encounter import start_encounter

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import LoreKitError, require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db
        from lorekit.encounter import start_encounter

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
            from lorekit.rules import rules_calc

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

            # The on_hit inserts a marker row (source="grab") which triggers
            # the grab condition; sync_condition_modifiers creates cond:grab rows
            # with the mechanical effects from condition_rules.
            marker = db.execute(
                "SELECT source, target_stat FROM combat_state WHERE character_id = ? AND source = 'grab'",
                (def_id,),
            ).fetchall()
            assert len(marker) == 1

            cond_rows = db.execute(
                "SELECT source, target_stat, value FROM combat_state WHERE character_id = ? AND source = 'cond:grab'",
                (def_id,),
            ).fetchall()
            cond_stats = {r[1] for r in cond_rows}
            assert "bonus_dodge" in cond_stats
            assert "bonus_speed" in cond_stats
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Critical hit tests
# ---------------------------------------------------------------------------


class TestThresholdCriticalHit:
    def test_natural_20_doubles_damage(self, make_session, make_character):
        """Threshold: natural 20 hit → CRITICAL HIT with damage multiplier."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Defender")
            set_attr(db, def_id, "combat", "current_hp", "40")

            # Natural 20 attack (hit), damage d8=4
            roll_calls = iter([19, 3])  # 19+1=20 (nat20), 3+1=4
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "melee_attack", TEST_SYSTEM)

            assert "CRITICAL HIT!" in output
            assert "Damage x2" in output
            # damage: (d8(4) + str_mod(4)) * 2 = 16 → HP 40 → 24
            assert "current_hp: 40 → 24" in output
        finally:
            db.close()

    def test_natural_20_miss_upgraded_to_hit(self, make_session, make_character):
        """Threshold: natural 20 that would miss → upgraded to regular hit."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_fighter(
                db,
                make_session,
                make_character,
                set_attr,
                "Defender",
                dex="30",  # very high AC so normal roll would miss
            )
            set_attr(db, def_id, "combat", "current_hp", "40")

            # Natural 20 attack, damage d8=4
            # attack: d20(20) + 9 = 29 vs AC = 10 + 10 + 0 + 0 = 20
            # This would normally hit, so let's use low str to ensure miss without nat20
            # Actually with dex=30, AC = 10 + 10 = 20. attack=29 hits anyway.
            # Let's set armor bonus high instead.
            set_attr(db, def_id, "stat", "item_bonus_ac", "30")
            from lorekit.rules import rules_calc

            rules_calc(db, def_id, TEST_SYSTEM)
            # Now AC = 10 + 10 + 30 = 50. attack d20(20)+9=29 < 50 → miss normally.
            # But nat 20 degree_shift upgrades miss → hit (not crit since it wasn't a hit)

            roll_calls = iter([19, 3])  # nat20, damage d8=4
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "melee_attack", TEST_SYSTEM)

            assert "HIT!" in output
            assert "CRITICAL" not in output  # miss→hit, not crit
        finally:
            db.close()

    def test_no_crit_without_natural_20(self, make_session, make_character):
        """Threshold: regular hit (not nat 20) → no critical."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Defender")
            set_attr(db, def_id, "combat", "current_hp", "40")

            # d20=18 (not nat 20), damage d8=6
            roll_calls = iter([17, 5])  # 17+1=18, 5+1=6
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "melee_attack", TEST_SYSTEM)

            assert "HIT!" in output
            assert "CRITICAL" not in output
            # damage: d8(6) + 4 = 10 (no multiplier)
            assert "current_hp: 40 → 30" in output
        finally:
            db.close()


class TestDegreeCriticalHit:
    def test_mm3e_natural_20_adds_effect_rank(self, make_session, make_character):
        """M&M3e degree: natural 20 → +5 effect rank on resistance DC."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
            from lorekit.rules import rules_calc

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

            # Attack d20=20 (nat20, hit): 20 + 6 = 26 vs DC 10+6=16 → HIT
            # Crit: effect rank bonus +5 → damage_rank = 6+5 = 11
            # Resistance d20=10: 10 + 4 = 14 vs DC 15+11=26
            # Degree = floor((26-14)/5) = floor(12/5) = 2
            roll_calls = iter([19, 9])  # 20, 10
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)

            assert "HIT!" in output
            assert "CRITICAL! Effect rank +5" in output
            assert "vs DC 26" in output  # 15 + 6 + 5 = 26
            assert "DEGREE OF FAILURE:" in output
        finally:
            db.close()

    def test_mm3e_no_crit_without_natural_20(self, make_session, make_character):
        """M&M3e degree: regular hit → no effect rank bonus."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
            from lorekit.rules import rules_calc

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

            # Attack d20=15 (not nat20): 15 + 6 = 21 vs DC 16 → HIT
            # No crit → damage_rank = 6 (no bonus)
            # Resistance d20=3: 3 + 4 = 7 vs DC 15+6=21
            roll_calls = iter([14, 2])  # 15, 3
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)

            assert "HIT!" in output
            assert "CRITICAL" not in output
            assert "vs DC 21" in output  # 15 + 6, no crit bonus
        finally:
            db.close()


class TestRelocateOnHit:
    def test_relocate_moves_target_on_hit(self, make_session, make_character):
        """on_hit relocate moves the target to a named zone."""
        from cruncher.system_pack import SystemPack, load_system_pack
        from cruncher.types import CharacterData
        from lorekit.character import set_attr
        from lorekit.combat import _apply_on_hit
        from lorekit.db import require_db
        from lorekit.encounter import (
            _get_character_zone,
            _zone_id_to_name,
            start_encounter,
        )
        from lorekit.rules import load_character_data

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Caster")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Target")

            sess_id = db.execute("SELECT session_id FROM characters WHERE id = ?", (atk_id,)).fetchone()[0]

            start_encounter(
                db,
                sess_id,
                [{"name": "Near"}, {"name": "Far"}],
                [{"character_id": atk_id, "roll": 20}, {"character_id": def_id, "roll": 10}],
                placements=[
                    {"character_id": atk_id, "zone": "Near"},
                    {"character_id": def_id, "zone": "Near"},
                ],
                combat_cfg={"zone_scale": 30, "movement_unit": "ft", "melee_range": 0, "zone_tags": {}},
            )

            pack = load_system_pack(TEST_SYSTEM)
            attacker = load_character_data(db, atk_id)
            defender = load_character_data(db, def_id)

            on_hit = {"relocate": {"who": "primary", "zone_field": "relocate_zone"}}
            options = {"relocate_zone": "Far"}
            lines = []

            _apply_on_hit(db, pack, attacker, defender, on_hit, lines, options=options)

            output = "\n".join(lines)
            assert "MOVED" in output
            assert "Far" in output

            # Verify target is now in Far zone
            enc_id = db.execute(
                "SELECT id FROM encounter_state WHERE session_id = ? AND status = 'active'",
                (sess_id,),
            ).fetchone()[0]
            zone_id = _get_character_zone(db, enc_id, def_id)
            zone_name = _zone_id_to_name(db, zone_id)
            assert zone_name == "Far"
        finally:
            db.close()


class TestUtilityAction:
    def test_on_use_relocate_no_roll(self, make_session, make_character):
        """Utility action (no attack_stat) applies on_use effects without rolling."""
        from lorekit.character import set_attr
        from lorekit.db import require_db
        from lorekit.encounter import (
            _get_character_zone,
            _zone_id_to_name,
            start_encounter,
        )

        db = require_db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, set_attr, "Caster")
            _, def_id = _setup_fighter(db, make_session, make_character, set_attr, "Ally")

            sess_id = db.execute("SELECT session_id FROM characters WHERE id = ?", (atk_id,)).fetchone()[0]

            start_encounter(
                db,
                sess_id,
                [{"name": "Near"}, {"name": "Far"}],
                [{"character_id": atk_id, "roll": 20}, {"character_id": def_id, "roll": 10}],
                placements=[
                    {"character_id": atk_id, "zone": "Near"},
                    {"character_id": def_id, "zone": "Near"},
                ],
                combat_cfg={"zone_scale": 30, "movement_unit": "ft", "melee_range": 0, "zone_tags": {}},
            )

            # Teleport is a utility action — no attack_stat, on_use relocate
            output = resolve_action(
                db,
                atk_id,
                def_id,
                "teleport",
                TEST_SYSTEM,
                options={"relocate_zone": "Far"},
            )

            assert "MOVED" in output
            assert "Far" in output
            # No roll should appear
            assert "ATTACK" not in output
            assert "HIT" not in output
            assert "MISS" not in output

            # Verify target moved
            enc_id = db.execute(
                "SELECT id FROM encounter_state WHERE session_id = ? AND status = 'active'",
                (sess_id,),
            ).fetchone()[0]
            zone_id = _get_character_zone(db, enc_id, def_id)
            zone_name = _zone_id_to_name(db, zone_id)
            assert zone_name == "Far"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Condition-based action limits (shared PC + NPC enforcement)
# ---------------------------------------------------------------------------


def _setup_mm3e_fighter(db, make_session, make_character, set_attr, name):
    """Create an M&M3e character with basic stats."""
    sid = make_session()
    cid = make_character(sid, name=name, level=1)
    for key, val in [
        ("fgt", "6"),
        ("agl", "2"),
        ("dex", "0"),
        ("str", "6"),
        ("sta", "4"),
        ("int", "0"),
        ("awe", "2"),
        ("pre", "0"),
        ("power_level", "10"),
    ]:
        set_attr(db, cid, "stat", key, val)
    from lorekit.rules import rules_calc

    rules_calc(db, cid, MM3E_SYSTEM)
    return sid, cid


class TestConditionActionLimit:
    """Condition-based action limits apply to both PCs and NPCs."""

    def test_incapacitated_blocks_action(self, make_session, make_character):
        """A character with damage_condition >= 4 (incapacitated) cannot act."""
        from lorekit.character import set_attr
        from lorekit.db import LoreKitError, require_db

        db = require_db()
        try:
            sid, atk_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Defender")
            # Set attacker to incapacitated
            set_attr(db, atk_id, "stat", "damage_condition", "4")

            with pytest.raises(LoreKitError, match="BLOCKED.*incapacitated"):
                resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)
        finally:
            db.close()

    def test_stunned_blocks_action(self, make_session, make_character):
        """A character with a 'stunned' combat_state source cannot act."""
        from lorekit.character import set_attr
        from lorekit.db import LoreKitError, require_db

        db = require_db()
        try:
            sid, atk_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Defender")
            # Apply stunned via combat_state
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, value, modifier_type, duration_type, duration) "
                "VALUES (?, 'stunned', 'bonus_dodge', -2, 'condition', 'rounds', 1)",
                (atk_id,),
            )
            db.commit()

            with pytest.raises(LoreKitError, match="BLOCKED.*stunned"):
                resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)
        finally:
            db.close()

    def test_dazed_allows_first_action_blocks_second(self, make_session, make_character):
        """Dazed (max_total: 1): first action goes through, second is blocked."""
        from lorekit.character import set_attr
        from lorekit.db import LoreKitError, require_db

        db = require_db()
        try:
            sid, atk_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Defender")
            # Set attacker to dazed (damage_condition = 2)
            set_attr(db, atk_id, "stat", "damage_condition", "2")

            # First action should succeed
            roll_calls = iter([14, 19])  # attack d20=15, resist d20=20
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)
            assert "ACTION" in result

            # Second action should be blocked
            with pytest.raises(LoreKitError, match="BLOCKED.*dazed.*1/1"):
                resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)
        finally:
            db.close()

    def test_action_counter_resets_on_advance_turn(self, make_session, make_character):
        """The per-turn action counter resets when advance_turn is called."""
        from lorekit.character import set_attr
        from lorekit.db import require_db
        from lorekit.encounter import advance_turn

        db = require_db()
        try:
            sid, atk_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Defender")

            # Set up encounter
            from lorekit.encounter import start_encounter

            zones = [{"name": "Arena"}]
            initiative = [{"character_id": atk_id, "roll": 20}, {"character_id": def_id, "roll": 10}]
            placements = [{"character_id": atk_id, "zone": "Arena"}, {"character_id": def_id, "zone": "Arena"}]
            start_encounter(db, sid, zones, initiative, placements=placements)

            # Set dazed
            set_attr(db, atk_id, "stat", "damage_condition", "2")

            # Use the one allowed action
            roll_calls = iter([14, 19])
            with patch("secrets.randbelow", side_effect=roll_calls):
                resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)

            # Advance past attacker's turn (to defender), then back to attacker
            combat_cfg = {"zone_scale": 1}
            advance_turn(db, sid, combat_cfg)  # now defender's turn
            advance_turn(db, sid, combat_cfg)  # back to attacker's turn

            # Counter should be reset — action should work again
            roll_calls = iter([14, 19])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)
            assert "ACTION" in result
        finally:
            db.close()

    def test_healthy_character_not_blocked(self, make_session, make_character):
        """A character with no active conditions can act freely."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid, atk_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Attacker")
            _, def_id = _setup_mm3e_fighter(db, make_session, make_character, set_attr, "Defender")

            # Two actions should both work (no condition limiting)
            roll_calls = iter([14, 19, 14, 19])
            with patch("secrets.randbelow", side_effect=roll_calls):
                r1 = resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)
                r2 = resolve_action(db, atk_id, def_id, "close_attack", MM3E_SYSTEM)
            assert "ACTION" in r1
            assert "ACTION" in r2
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Named combat options
# ---------------------------------------------------------------------------


class TestCombatOptions:
    def test_expand_named_options(self):
        """Named combat options expand into trade dicts."""
        from cruncher.system_pack import load_system_pack
        from lorekit.combat import _expand_combat_options

        pack = load_system_pack(MM3E_SYSTEM)

        opts = _expand_combat_options(
            pack,
            {
                "combat_options": [
                    {"name": "power_attack", "value": 5},
                    {"name": "all_out_attack", "value": 3},
                ]
            },
        )

        trades = opts["trade"]
        assert len(trades) == 2

        # Power Attack: from close_attack, to close_damage, value 5
        pa = trades[0]
        assert pa["from"] == "close_attack"
        assert pa["to"] == "close_damage"
        assert pa["value"] == 5

        # All-out Attack: no from, to close_attack, value 3, with apply_modifiers
        aoa = trades[1]
        assert "from" not in aoa
        assert aoa["to"] == "close_attack"
        assert aoa["value"] == 3
        assert len(aoa["apply_modifiers"]) == 2
        # negate: true means modifier value = -3
        assert aoa["apply_modifiers"][0]["value"] == -3
        assert aoa["apply_modifiers"][1]["value"] == -3

    def test_clamp_to_max(self):
        """Value exceeding max is clamped."""
        from cruncher.system_pack import load_system_pack
        from lorekit.combat import _expand_combat_options

        pack = load_system_pack(MM3E_SYSTEM)

        opts = _expand_combat_options(pack, {"combat_options": [{"name": "power_attack", "value": 99}]})

        assert opts["trade"][0]["value"] == 5  # max is 5

    def test_optional_from_in_trade(self, make_session, make_character):
        """Trades without 'from' work correctly (only add to 'to' stat)."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
                set_attr(db, def_id, "stat", key, val)

            from lorekit.rules import rules_calc

            rules_calc(db, atk_id, MM3E_SYSTEM)
            rules_calc(db, def_id, MM3E_SYSTEM)

            from lorekit.encounter import start_encounter

            start_encounter(
                db,
                sid,
                [{"name": "Arena"}],
                [{"character_id": atk_id, "roll": 20}, {"character_id": def_id, "roll": 10}],
                placements=[
                    {"character_id": atk_id, "zone": "Arena"},
                    {"character_id": def_id, "zone": "Arena"},
                ],
                combat_cfg={"zone_scale": 1, "movement_unit": "rank", "melee_range": 0, "zone_tags": {}},
            )

            # Trade with no 'from' — just adds +5 to close_attack
            roll_calls = iter([14, 19])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(
                    db,
                    atk_id,
                    def_id,
                    "close_attack",
                    MM3E_SYSTEM,
                    options={"trade": [{"to": "close_attack", "value": 5}]},
                )
            # Should not crash and should show the attack
            assert "ACTION:" in output
        finally:
            db.close()

    def test_named_options_apply_modifiers(self, make_session, make_character):
        """All-out Attack via named option applies persistent defense penalties."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
                set_attr(db, def_id, "stat", key, val)

            from lorekit.rules import rules_calc

            rules_calc(db, atk_id, MM3E_SYSTEM)
            rules_calc(db, def_id, MM3E_SYSTEM)

            from lorekit.encounter import start_encounter

            start_encounter(
                db,
                sid,
                [{"name": "Arena"}],
                [{"character_id": atk_id, "roll": 20}, {"character_id": def_id, "roll": 10}],
                placements=[
                    {"character_id": atk_id, "zone": "Arena"},
                    {"character_id": def_id, "zone": "Arena"},
                ],
                combat_cfg={"zone_scale": 1, "movement_unit": "rank", "melee_range": 0, "zone_tags": {}},
            )

            roll_calls = iter([14, 19])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(
                    db,
                    atk_id,
                    def_id,
                    "close_attack",
                    MM3E_SYSTEM,
                    options={"combat_options": [{"name": "all_out_attack", "value": 5}]},
                )

            assert "TRADE MODIFIER: all_out_attack" in output

            # Verify modifiers on attacker
            mods = db.execute(
                "SELECT source, target_stat, value, duration_type FROM combat_state "
                "WHERE character_id = ? AND source = 'all_out_attack'",
                (atk_id,),
            ).fetchall()
            assert len(mods) == 2
            for m in mods:
                assert m[2] == -5  # negated value
                assert m[3] == "until_next_turn"
        finally:
            db.close()
