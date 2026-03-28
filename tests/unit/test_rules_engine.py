"""Tests for the Crunch rules engine."""

import json
import os
import secrets
from unittest.mock import patch

import cruncher_mm3e
import cruncher_pf2e
import pytest

from cruncher.engine import CalcResult, SystemPack, recalculate
from cruncher.system_pack import load_system_pack
from cruncher.types import CharacterData
from lorekit.rules import load_character_data, rules_calc, rules_check, write_derived

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_SYSTEM = os.path.join(ROOT, "systems", "basic")


# ---------------------------------------------------------------------------
# System pack loading
# ---------------------------------------------------------------------------


class TestLoadSystemPack:
    def test_loads_meta(self):
        pack = load_system_pack(TEST_SYSTEM)
        assert pack.name == "Basic d20"
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


# ---------------------------------------------------------------------------
# DB integration
# ---------------------------------------------------------------------------


class TestDBIntegration:
    def test_write_derived(self, make_session, make_character):
        from lorekit.db import require_db

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
        from lorekit.db import require_db

        sid = make_session()
        cid = make_character(sid)

        db = require_db()
        try:
            count = write_derived(db, cid, {"good": 5, "bad": "ERROR: something"})
            assert count == 1
        finally:
            db.close()

    def test_write_derived_upsert(self, make_session, make_character):
        from lorekit.db import require_db

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
        from lorekit.character import set_ability, set_attr
        from lorekit.db import require_db

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
        from lorekit.character import set_attr
        from lorekit.db import require_db

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
            assert derived["defense"] == "12"  # 10 + 2
        finally:
            db.close()

    def test_build_engine_wired_pf2e(self, make_session, make_character):
        """Build engine runs automatically and feeds into derived formulas."""
        from lorekit.character import set_ability, set_attr
        from lorekit.db import require_db

        pf2e = cruncher_pf2e.pack_path()
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
            assert build["prof_fortitude"] == "4"  # expert

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
        from lorekit.character import set_ability, set_attr
        from lorekit.db import require_db

        mm3e = cruncher_mm3e.pack_path()
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
            power_json = json.dumps(
                {
                    "effect": "protection",
                    "ranks": 6,
                    "feeds": {"effect_protection": 6},
                }
            )
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


# ---------------------------------------------------------------------------
# rules_check
# ---------------------------------------------------------------------------


class TestRulesCheck:
    def test_check_success(self, make_session, make_character):
        """Roll high enough → SUCCESS."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        sid = make_session()
        cid = make_character(sid, name="Durão", level=5)

        db = require_db()
        try:
            set_attr(db, cid, "stat", "str", "18")
            set_attr(db, cid, "stat", "dex", "14")
            set_attr(db, cid, "stat", "con", "12")
            set_attr(db, cid, "combat", "base_attack", "5")
            set_attr(db, cid, "combat", "hit_die_avg", "6")
            rules_calc(db, cid, TEST_SYSTEM)
        finally:
            db.close()

        # melee_attack derived = 9, mock d20 roll = 15 → total = 24 vs DC 15 → SUCCESS
        db = require_db()
        try:
            with patch("secrets.randbelow", return_value=14):  # 14+1=15
                output = rules_check(db, cid, "melee_attack", 15, TEST_SYSTEM)
            assert "CHECK: Durão — melee_attack" in output
            assert "d20(15) + 9 = 24 vs DC 15" in output
            assert "SUCCESS (by 9)" in output
        finally:
            db.close()

    def test_check_failure(self, make_session, make_character):
        """Roll too low → FAILURE."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        sid = make_session()
        cid = make_character(sid, name="Durão", level=5)

        db = require_db()
        try:
            set_attr(db, cid, "stat", "str", "18")
            set_attr(db, cid, "stat", "dex", "14")
            set_attr(db, cid, "stat", "con", "12")
            set_attr(db, cid, "combat", "base_attack", "5")
            set_attr(db, cid, "combat", "hit_die_avg", "6")
            rules_calc(db, cid, TEST_SYSTEM)
        finally:
            db.close()

        # melee_attack=9, mock d20 roll=2 → total=11 vs DC 20 → FAILURE
        db = require_db()
        try:
            with patch("secrets.randbelow", return_value=1):  # 1+1=2
                output = rules_check(db, cid, "melee_attack", 20, TEST_SYSTEM)
            assert "FAILURE (by 9)" in output
        finally:
            db.close()

    def test_check_missing_stat(self, make_session, make_character):
        """Missing derived stat raises error."""
        from lorekit.db import LoreKitError, require_db

        sid = make_session()
        cid = make_character(sid, name="Durão", level=5)

        db = require_db()
        try:
            with pytest.raises(LoreKitError, match="not found in derived"):
                rules_check(db, cid, "nonexistent_stat", 10, TEST_SYSTEM)
        finally:
            db.close()


class TestBonusAttrMultiCategory:
    """Bonus attributes in multiple categories must consolidate to one source."""

    def test_bonus_in_two_categories_not_double_counted(self, make_session, make_character):
        """bonus_melee_attack in both 'stat' and 'combat' should not be summed
        as two separate stacking sources — they represent one base value."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        MM3E_SYSTEM = cruncher_mm3e.pack_path()

        db = require_db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Fighter", level=1)

            # Set ability scores
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
                set_attr(db, cid, "stat", key, val)

            # Put bonus_close_damage in TWO categories (simulating duplicate writes)
            set_attr(db, cid, "stat", "bonus_close_damage", "3")
            set_attr(db, cid, "combat", "bonus_close_damage", "3")

            result = rules_calc(db, cid, MM3E_SYSTEM)

            # With the fix, both entries have source="_attr", so grouped stacking
            # (group_by=source, positive=max) takes max(3, 3) = 3, not 3+3=6.
            derived = dict(
                db.execute(
                    "SELECT key, value FROM character_attributes WHERE character_id = ? AND category = 'derived'",
                    (cid,),
                ).fetchall()
            )
            # close_damage = max(unarmed_damage, ...) and unarmed_damage = effective_str + bonus_close_damage
            # effective_str = str(6) → unarmed_damage = 6 + 3 = 9
            assert int(derived["unarmed_damage"]) == 9
            assert int(derived["close_damage"]) == 9
        finally:
            db.close()


class TestBudgetReporting:
    """Budget cost-change diffs and over-budget warnings."""

    MM3E = cruncher_mm3e.pack_path()

    def test_cost_changes_on_first_build(self, make_session, make_character):
        """First rules_calc shows cost changes from 0."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Hero", level=1)

            set_attr(db, cid, "stat", "str", "4")
            set_attr(db, cid, "stat", "sta", "2")

            output = rules_calc(db, cid, self.MM3E)

            assert "BUDGET:" in output
            assert "COST CHANGES:" in output
            assert "ability:" in output
            # str=4 + sta=2 = 6 ranks × 2 pts = 12
            assert "ability: 0 → 12 (+12)" in output
        finally:
            db.close()

    def test_cost_changes_on_update(self, make_session, make_character):
        """Second rules_calc shows incremental cost change."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Hero", level=1)

            set_attr(db, cid, "stat", "str", "4")
            rules_calc(db, cid, self.MM3E)

            # Add defense ranks
            set_attr(db, cid, "stat", "ranks_dodge", "6")
            output = rules_calc(db, cid, self.MM3E)

            assert "COST CHANGES:" in output
            assert "defense: 0 → 6 (+6)" in output
            # ability should NOT appear in cost changes (unchanged)
            assert (
                "ability:" not in output.split("COST CHANGES:")[1].split("WARNING")[0]
                if "WARNING" in output
                else "ability:" not in output.split("COST CHANGES:")[1]
            )
        finally:
            db.close()

    def test_over_budget_warning(self, make_session, make_character):
        """Over-budget build shows WARNING."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Hero", level=1)

            # PL 10 = 150 budget. 80 ranks of abilities × 2 = 160 > 150
            for key, val in [
                ("str", "10"),
                ("sta", "10"),
                ("dex", "10"),
                ("agl", "10"),
                ("fgt", "10"),
                ("int", "10"),
                ("awe", "10"),
                ("pre", "10"),
            ]:
                set_attr(db, cid, "stat", key, val)

            output = rules_calc(db, cid, self.MM3E)

            assert "WARNING: Over budget by 10 points!" in output
        finally:
            db.close()

    def test_no_warning_when_under_budget(self, make_session, make_character):
        """Under-budget build has no WARNING."""
        from lorekit.character import set_attr
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Hero", level=1)

            set_attr(db, cid, "stat", "str", "2")

            output = rules_calc(db, cid, self.MM3E)

            assert "WARNING" not in output
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Skill templates
# ---------------------------------------------------------------------------


class TestSkillTemplates:
    """Skill templates auto-generate derived formulas from patterns."""

    def test_template_instantiates_lore_skill(self):
        pack = SystemPack()
        pack.defaults = {"int": 14}
        pack.derived = {"int_mod": "floor((int - 10) / 2)"}
        pack.derived_patterns = {
            "lore": {
                "formula": "int_mod + if(prof_{slug} > 0, prof_{slug} + level, 0) + bonus_{slug}",
                "default_prof": 0,
                "default_bonus": 0,
            }
        }
        char = CharacterData(character_id=1, session_id=1, name="Test", level=3, char_type="pc")
        char.attributes["build"] = {"prof_lore_scribing": "2"}
        result = recalculate(pack, char)
        # int_mod = floor((14-10)/2) = 2
        # skill_lore_scribing = 2 + if(2>0, 2+3, 0) + 0 = 2 + 5 = 7
        assert result.derived["skill_lore_scribing"] == 7

    def test_template_does_not_fire_without_matching_attr(self):
        pack = SystemPack()
        pack.defaults = {"int": 14}
        pack.derived = {"int_mod": "floor((int - 10) / 2)"}
        pack.derived_patterns = {
            "lore": {
                "formula": "int_mod + if(prof_{slug} > 0, prof_{slug} + level, 0) + bonus_{slug}",
                "default_prof": 0,
                "default_bonus": 0,
            }
        }
        char = CharacterData(character_id=1, session_id=1, name="Test", level=1, char_type="pc")
        result = recalculate(pack, char)
        assert "skill_lore_scribing" not in result.derived

    def test_no_templates_section_is_fine(self):
        pack = SystemPack()
        pack.defaults = {"str": 10}
        pack.derived = {"str_mod": "floor((str - 10) / 2)"}
        char = CharacterData(character_id=1, session_id=1, name="Test", level=1, char_type="pc")
        result = recalculate(pack, char)
        assert result.derived["str_mod"] == 0

    def test_multiple_lore_skills(self):
        pack = SystemPack()
        pack.defaults = {"int": 14}
        pack.derived = {"int_mod": "floor((int - 10) / 2)"}
        pack.derived_patterns = {
            "lore": {
                "formula": "int_mod + if(prof_{slug} > 0, prof_{slug} + level, 0) + bonus_{slug}",
                "default_prof": 0,
                "default_bonus": 0,
            }
        }
        char = CharacterData(character_id=1, session_id=1, name="Test", level=5, char_type="pc")
        char.attributes["build"] = {"prof_lore_scribing": "2", "prof_lore_warfare": "4"}
        result = recalculate(pack, char)
        assert result.derived["skill_lore_scribing"] == 9  # 2 + (2+5) + 0
        assert result.derived["skill_lore_warfare"] == 11  # 2 + (4+5) + 0
