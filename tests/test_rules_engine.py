"""Tests for the Crunch rules engine."""

import json
import os
import pytest

from rules_engine import (
    CalcResult,
    CharacterData,
    SystemPack,
    load_character_data,
    load_system_pack,
    recalculate,
    rules_calc,
    write_derived,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


# ---------------------------------------------------------------------------
# System pack loading
# ---------------------------------------------------------------------------

class TestLoadSystemPack:
    def test_loads_meta(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert pack.name == "Test System"
        assert pack.dice == "d20"

    def test_loads_abilities(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert pack.ability_list == ["Strength", "Dexterity", "Constitution"]
        assert pack.ability_mod_formula == "floor((score - 10) / 2)"

    def test_short_names(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert pack.ability_short_names["str"] == "Strength"
        assert pack.ability_short_names["dex"] == "Dexterity"
        assert pack.ability_short_names["con"] == "Constitution"

    def test_loads_tables(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert "bab_full" in pack.tables
        assert pack.tables["bab_full"][0] == 1
        assert pack.tables["bab_full"][9] == 10

    def test_loads_derived(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert "melee_attack" in pack.derived
        assert "defense" in pack.derived

    def test_loads_constraints(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert "hp_positive" in pack.constraints

    def test_loads_iterative(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert pack.iterative_threshold == 6
        assert pack.iterative_penalty == -5

    def test_loads_classes(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert "warrior" in pack.classes
        cls = pack.classes["warrior"]
        assert cls.name == "Warrior"
        assert cls.hit_die == "d10"
        assert cls.bab == "bab_full"
        assert 1 in cls.levels
        assert "combat_stance" in cls.levels[1].features

    def test_loads_feats(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert "power_attack" in pack.feats
        assert pack.feats["power_attack"].combat_option is True
        assert pack.feats["weapon_focus"].param == "weapon_type"

    def test_missing_system_toml(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_system_pack(str(tmp_path))


# ---------------------------------------------------------------------------
# Recalculation (pure, no DB)
# ---------------------------------------------------------------------------

class TestRecalculate:
    def _make_char(self, **overrides) -> CharacterData:
        char = CharacterData(
            character_id=1,
            session_id=1,
            name="Test Hero",
            level=5,
            attributes={
                "ability": {"str": "18", "dex": "14", "con": "12"},
            },
        )
        for k, v in overrides.items():
            setattr(char, k, v)
        return char

    def test_basic_derived(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        # No class set, so bab won't be resolved from class tables.
        # Set bab manually via attributes.
        char.attributes["combat"] = {"bab": "5"}
        char.attributes["hit"] = {"hit_die_avg": "6"}

        result = recalculate(pack, char)
        # melee_attack = bab(5) + mod(str)(4) + sum(bonuses.melee_attack)(0) = 9
        assert result.derived["melee_attack"] == 9
        # ranged_attack = bab(5) + mod(dex)(2) + 0 = 7
        assert result.derived["ranged_attack"] == 7
        # defense = 10 + mod(dex)(2) + 0 = 12
        assert result.derived["defense"] == 12
        # max_hp = 6 * 5 + 1 * 5 = 35
        assert result.derived["max_hp"] == 35

    def test_class_integration(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["info"] = {"class": "warrior"}

        result = recalculate(pack, char)
        # Warrior level 5: bab_full[4] = 5
        # melee = 5 + mod(str=18)(4) + 0 = 9
        assert result.derived["melee_attack"] == 9
        # hit_die_avg for d10 = ceil(10/2)+1 = 6
        # max_hp = 6*5 + mod(con=12)(1)*5 = 30+5 = 35
        assert result.derived["max_hp"] == 35

    def test_feat_bonuses(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"bab": "5"}
        char.attributes["hit"] = {"hit_die_avg": "6"}
        # Add Weapon Focus (always-on, non-combat_option)
        char.abilities = [
            {"name": "Weapon Focus", "description": "Swords", "category": "combat", "uses": "at_will"},
        ]

        result = recalculate(pack, char)
        # melee = 5 + 4 + 1 (weapon focus) = 10
        assert result.derived["melee_attack"] == 10

    def test_combat_option_not_always_on(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"bab": "5"}
        char.attributes["hit"] = {"hit_die_avg": "6"}
        # Power Attack is a combat_option — its effects should NOT be in always-on bonuses
        char.abilities = [
            {"name": "Power Attack", "description": "", "category": "combat", "uses": "at_will"},
        ]

        result = recalculate(pack, char)
        # melee = 5 + 4 + 0 (power attack not applied) = 9
        assert result.derived["melee_attack"] == 9

    def test_constraint_passes(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"bab": "5"}
        char.attributes["hit"] = {"hit_die_avg": "6"}

        result = recalculate(pack, char)
        assert result.violations == []

    def test_changes_tracked(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"bab": "5"}
        char.attributes["hit"] = {"hit_die_avg": "6"}

        result = recalculate(pack, char)
        # All stats are new (no previous derived values)
        assert "melee_attack" in result.changes
        assert result.changes["melee_attack"][0] is None  # old value

    def test_changes_diff(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"bab": "5"}
        char.attributes["hit"] = {"hit_die_avg": "6"}
        # Pretend old derived values exist
        char.attributes["derived"] = {"melee_attack": "8", "defense": "12"}

        result = recalculate(pack, char)
        # melee_attack changed from 8 to 9
        assert result.changes["melee_attack"] == ("8", 9)
        # defense stayed at 12 — should NOT be in changes
        assert "defense" not in result.changes

    def test_empty_system_pack(self, tmp_path):
        # Minimal system.toml with no derived stats
        system_file = tmp_path / "system.toml"
        system_file.write_text('[meta]\nname = "Empty"\n')
        pack = load_system_pack(str(tmp_path))
        char = self._make_char()

        result = recalculate(pack, char)
        assert result.derived == {}
        assert result.violations == []


# ---------------------------------------------------------------------------
# DB integration
# ---------------------------------------------------------------------------

class TestDBIntegration:
    def test_write_derived(self, make_session, make_character):
        from _db import require_db
        sid = make_session()
        cid = make_character(sid, name="Warrior", level=5)

        db = require_db()
        try:
            count = write_derived(db, cid, {"melee_attack": 9, "defense": 12})
            assert count == 2

            # Verify values were written
            rows = db.execute(
                "SELECT key, value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' ORDER BY key",
                (cid,),
            ).fetchall()
            assert dict(rows) == {"defense": "12", "melee_attack": "9"}
        finally:
            db.close()

    def test_write_derived_skips_errors(self, make_session, make_character):
        from _db import require_db
        sid = make_session()
        cid = make_character(sid)

        db = require_db()
        try:
            count = write_derived(db, cid, {"good": 5, "bad": "ERROR: something"})
            assert count == 1
        finally:
            db.close()

    def test_write_derived_upsert(self, make_session, make_character):
        from _db import require_db
        sid = make_session()
        cid = make_character(sid)

        db = require_db()
        try:
            write_derived(db, cid, {"melee_attack": 9})
            write_derived(db, cid, {"melee_attack": 11})

            val = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'melee_attack'",
                (cid,),
            ).fetchone()[0]
            assert val == "11"
        finally:
            db.close()

    def test_load_character_data(self, make_session, make_character):
        from _db import require_db
        from character import set_attr, set_ability

        sid = make_session()
        cid = make_character(sid, name="Durão", level=5)

        db = require_db()
        try:
            set_attr(db, cid, "ability", "str", "18")
            set_attr(db, cid, "ability", "dex", "14")
            set_attr(db, cid, "ability", "con", "12")
            set_attr(db, cid, "info", "class", "warrior")
            set_ability(db, cid, "Weapon Focus", "Swords", "combat")

            char = load_character_data(db, cid)
            assert char.name == "Durão"
            assert char.level == 5
            assert char.attributes["ability"]["str"] == "18"
            assert char.attributes["info"]["class"] == "warrior"
            assert len(char.abilities) == 1
            assert char.abilities[0]["name"] == "Weapon Focus"
        finally:
            db.close()

    def test_rules_calc_full(self, make_session, make_character):
        from _db import require_db
        from character import set_attr, set_ability

        sid = make_session()
        cid = make_character(sid, name="Durão", level=5)

        db = require_db()
        try:
            set_attr(db, cid, "ability", "str", "18")
            set_attr(db, cid, "ability", "dex", "14")
            set_attr(db, cid, "ability", "con", "12")
            set_attr(db, cid, "info", "class", "warrior")
            set_ability(db, cid, "Weapon Focus", "Swords", "combat")

            output = rules_calc(db, cid, TEST_SYSTEM)
            assert "RULES_CALC: Durão" in output
            assert "stats computed" in output

            # Verify derived values are now in DB
            rows = db.execute(
                "SELECT key, value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' ORDER BY key",
                (cid,),
            ).fetchall()
            derived = dict(rows)
            assert derived["melee_attack"] == "10"  # 5 + 4 + 1 (weapon focus)
            assert derived["defense"] == "12"        # 10 + 2
        finally:
            db.close()

    def test_rules_calc_no_system(self, make_session, make_character, tmp_path):
        from _db import require_db

        sid = make_session()
        cid = make_character(sid)

        system_file = tmp_path / "system.toml"
        system_file.write_text('[meta]\nname = "Empty"\n')

        db = require_db()
        try:
            output = rules_calc(db, cid, str(tmp_path))
            assert "no derived stats" in output
        finally:
            db.close()
