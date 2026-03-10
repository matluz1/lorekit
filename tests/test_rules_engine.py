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

    def test_loads_defaults(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert pack.defaults["bonus_melee_attack"] == 0
        assert pack.defaults["str"] == 10

    def test_loads_tables(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert "base_attack_full" in pack.tables
        assert pack.tables["base_attack_full"][0] == 1
        assert pack.tables["base_attack_full"][9] == 10

    def test_loads_derived(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert "melee_attack" in pack.derived
        assert "defense" in pack.derived
        assert "str_mod" in pack.derived

    def test_loads_constraints(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert "hp_positive" in pack.constraints

    def test_missing_system_json(self, tmp_path):
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
                "stat": {"str": "18", "dex": "14", "con": "12"},
            },
        )
        for k, v in overrides.items():
            setattr(char, k, v)
        return char

    def test_basic_derived(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"base_attack": "5", "hit_die_avg": "6"}

        result = recalculate(pack, char)
        # str_mod = floor((18 - 10) / 2) = 4
        assert result.derived["str_mod"] == 4
        # melee_attack = base_attack(5) + str_mod(4) + bonus_melee_attack(0) = 9
        assert result.derived["melee_attack"] == 9
        # dex_mod = floor((14 - 10) / 2) = 2
        # ranged_attack = 5 + 2 + 0 = 7
        assert result.derived["ranged_attack"] == 7
        # defense = 10 + dex_mod(2) + 0 = 12
        assert result.derived["defense"] == 12
        # con_mod = floor((12 - 10) / 2) = 1
        # max_hp = 6 * 5 + 1 * 5 = 35
        assert result.derived["max_hp"] == 35

    def test_bonus_variables(self):
        """Bonus variables (pre-aggregated by build engine) affect derived stats."""
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"base_attack": "5", "hit_die_avg": "6"}
        char.attributes["build"] = {"bonus_melee_attack": "1"}

        result = recalculate(pack, char)
        # melee = 5 + 4 + 1 = 10
        assert result.derived["melee_attack"] == 10

    def test_constraint_passes(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"base_attack": "5", "hit_die_avg": "6"}

        result = recalculate(pack, char)
        assert result.violations == []

    def test_changes_tracked(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"base_attack": "5", "hit_die_avg": "6"}

        result = recalculate(pack, char)
        # All stats are new (no previous derived values)
        assert "melee_attack" in result.changes
        assert result.changes["melee_attack"][0] is None  # old value

    def test_changes_diff(self):
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"base_attack": "5", "hit_die_avg": "6"}
        # Pretend old derived values exist
        char.attributes["derived"] = {"melee_attack": "8", "defense": "12"}

        result = recalculate(pack, char)
        # melee_attack changed from 8 to 9
        assert result.changes["melee_attack"] == ("8", 9)
        # defense stayed at 12 — should NOT be in changes
        assert "defense" not in result.changes

    def test_defaults_applied(self):
        """Defaults from system pack are used for missing variables."""
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"base_attack": "5", "hit_die_avg": "6"}

        result = recalculate(pack, char)
        # bonus_melee_attack defaults to 0 from system pack
        assert result.derived["melee_attack"] == 9  # 5 + 4 + 0

    def test_character_attrs_override_defaults(self):
        """Character attributes take precedence over system pack defaults."""
        pack = load_system_pack(TEST_SYSTEM)
        char = self._make_char()
        char.attributes["combat"] = {"base_attack": "5", "hit_die_avg": "6"}
        # Override the default for bonus_melee_attack
        char.attributes["build"] = {"bonus_melee_attack": "3"}

        result = recalculate(pack, char)
        assert result.derived["melee_attack"] == 12  # 5 + 4 + 3

    def test_empty_system_pack(self, tmp_path):
        # Minimal system.json with no derived stats
        system_file = tmp_path / "system.json"
        system_file.write_text('{"meta": {"name": "Empty"}}')
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
            set_attr(db, cid, "stat", "str", "18")
            set_attr(db, cid, "stat", "dex", "14")
            set_attr(db, cid, "stat", "con", "12")
            set_attr(db, cid, "info", "class", "warrior")
            set_ability(db, cid, "Weapon Focus", "Swords", "combat")

            char = load_character_data(db, cid)
            assert char.name == "Durão"
            assert char.level == 5
            assert char.attributes["stat"]["str"] == "18"
            assert char.attributes["info"]["class"] == "warrior"
            assert len(char.abilities) == 1
            assert char.abilities[0]["name"] == "Weapon Focus"
        finally:
            db.close()

    def test_rules_calc_full(self, make_session, make_character):
        from _db import require_db
        from character import set_attr

        sid = make_session()
        cid = make_character(sid, name="Durão", level=5)

        db = require_db()
        try:
            set_attr(db, cid, "stat", "str", "18")
            set_attr(db, cid, "stat", "dex", "14")
            set_attr(db, cid, "stat", "con", "12")
            set_attr(db, cid, "combat", "base_attack", "5")
            set_attr(db, cid, "combat", "hit_die_avg", "6")
            # Pre-aggregated bonus from build engine (e.g. Weapon Focus)
            set_attr(db, cid, "build", "bonus_melee_attack", "1")

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
            assert derived["melee_attack"] == "10"  # 5 + 4 + 1
            assert derived["defense"] == "12"        # 10 + 2
        finally:
            db.close()

    def test_rules_calc_no_system(self, make_session, make_character, tmp_path):
        from _db import require_db

        sid = make_session()
        cid = make_character(sid)

        system_file = tmp_path / "system.json"
        system_file.write_text('{"meta": {"name": "Empty"}}')

        db = require_db()
        try:
            output = rules_calc(db, cid, str(tmp_path))
            assert "no derived stats" in output
        finally:
            db.close()

    def test_build_engine_wired_pf2e(self, make_session, make_character):
        """Build engine runs automatically and feeds into derived formulas."""
        from _db import require_db
        from character import set_attr, set_ability

        pf2e = os.path.join(os.path.dirname(__file__), "..", "systems", "pf2e")
        sid = make_session()
        cid = make_character(sid, name="Valeros", level=1)

        db = require_db()
        try:
            set_attr(db, cid, "stat", "str", "18")
            set_attr(db, cid, "stat", "dex", "14")
            set_attr(db, cid, "stat", "con", "14")
            set_attr(db, cid, "stat", "wis", "10")
            set_attr(db, cid, "info", "ancestry", "human")
            set_attr(db, cid, "info", "class", "fighter")
            set_ability(db, cid, "Toughness", "", "general")

            output = rules_calc(db, cid, pf2e)

            # Build engine should have written these attributes
            build_rows = db.execute(
                "SELECT key, value FROM character_attributes "
                "WHERE character_id = ? AND category = 'build' ORDER BY key",
                (cid,),
            ).fetchall()
            build = dict(build_rows)

            # Ancestry writes
            assert build["ancestry_hp"] == "8"
            assert build["speed_base"] == "25"
            # Class writes
            assert build["hp_per_level"] == "10"
            # Feat effects
            assert build["bonus_hp"] == "1"
            # Progressions (fighter level 1)
            assert build["prof_perception"] == "4"  # expert
            assert build["prof_fortitude"] == "4"    # expert

            # Derived formulas should use build attributes
            derived_rows = db.execute(
                "SELECT key, value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' ORDER BY key",
                (cid,),
            ).fetchall()
            derived = dict(derived_rows)

            # max_hp = ancestry_hp + (hp_per_level + con_mod) * level + bonus_hp
            # = 8 + (10 + 2) * 1 + 1 = 21
            assert derived["max_hp"] == "21"
            assert derived["str_mod"] == "4"
        finally:
            db.close()

    def test_build_engine_wired_mm3e(self, make_session, make_character):
        """Build engine runs for M&M3e: budget, abilities, powers."""
        from _db import require_db
        from character import set_attr, set_ability

        mm3e = os.path.join(os.path.dirname(__file__), "..", "systems", "mm3e")
        sid = make_session()
        cid = make_character(sid, name="Paragon", level=1)

        db = require_db()
        try:
            set_attr(db, cid, "stat", "str", "6")
            set_attr(db, cid, "stat", "sta", "6")
            set_attr(db, cid, "stat", "fgt", "6")
            set_attr(db, cid, "stat", "agl", "2")
            set_attr(db, cid, "stat", "dex", "0")
            set_attr(db, cid, "stat", "int", "0")
            set_attr(db, cid, "stat", "awe", "2")
            set_attr(db, cid, "stat", "pre", "2")
            set_attr(db, cid, "stat", "power_level", "10")
            set_attr(db, cid, "stat", "ranks_dodge", "4")
            set_attr(db, cid, "stat", "ranks_fortitude", "4")
            set_attr(db, cid, "stat", "ranks_will", "4")
            set_ability(db, cid, "Close Attack", "", "advantage")
            # Protection power with feeds
            power_json = json.dumps({
                "effect": "protection",
                "ranks": 6,
                "feeds": {"effect_protection": 6},
            })
            set_ability(db, cid, "Tough Skin", power_json, "power")

            output = rules_calc(db, cid, mm3e)

            build_rows = db.execute(
                "SELECT key, value FROM character_attributes "
                "WHERE character_id = ? AND category = 'build' ORDER BY key",
                (cid,),
            ).fetchall()
            build = dict(build_rows)

            # Budget
            assert build["budget_total"] == "150"
            # Advantage effect
            assert build["adv_close_attack"] == "1"
            # Power feed
            assert build["effect_protection"] == "6"
            # Cost tracking
            assert "cost_ability" in build
            assert "cost_powers" in build

            # Derived formulas should use build attributes
            derived_rows = db.execute(
                "SELECT key, value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' ORDER BY key",
                (cid,),
            ).fetchall()
            derived = dict(derived_rows)

            # toughness = effective_sta + ranks_toughness + bonus_toughness + effect_protection + adv_defensive_roll
            # = 6 + 0 + 0 + 6 + 0 = 12
            assert derived["toughness"] == "12"
            # close_attack = effective_fgt + adv_close_attack + bonus_close_attack
            # = 6 + 1 + 0 = 7
            assert derived["close_attack"] == "7"
        finally:
            db.close()
