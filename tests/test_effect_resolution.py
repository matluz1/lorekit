"""Effect resolution tests — per_rank_effects, classification, outcome tables."""

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

MM3E_SYSTEM = os.path.join(os.path.dirname(__file__), "..", "systems", "mm3e")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _power_ability(name, power_json, category="power"):
    return {
        "name": name,
        "description": json.dumps(power_json),
        "category": category,
        "uses": "",
    }


def _load_effects():
    with open(os.path.join(MM3E_SYSTEM, "effects.json")) as f:
        return json.load(f)


# ===========================================================================
# per_rank_effects in build engine
# ===========================================================================


class TestPerRankEffects:
    def test_growth_rank4_str(self):
        """Growth rank 4: str +1 per rank → +4."""
        from build_engine import BuildResult, process_build

        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Growth", {"effect": "growth", "ranks": 4})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes.get("str", 0) == 4

    def test_growth_rank4_intimidation(self):
        """Growth rank 4: intimidation +1 per 2 ranks → +2."""
        from build_engine import process_build

        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Growth", {"effect": "growth", "ranks": 4})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes.get("intimidation", 0) == 2

    def test_growth_rank4_dodge(self):
        """Growth rank 4: dodge -1 per 2 ranks → -2."""
        from build_engine import process_build

        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Growth", {"effect": "growth", "ranks": 4})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes.get("dodge", 0) == -2

    def test_growth_rank3_speed(self):
        """Growth rank 3: speed +1 per 8 ranks → 0 (3 < 8)."""
        from build_engine import process_build

        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Growth", {"effect": "growth", "ranks": 3})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes.get("speed", 0) == 0

    def test_growth_rank8_speed(self):
        """Growth rank 8: speed +1 per 8 ranks → +1."""
        from build_engine import process_build

        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Growth", {"effect": "growth", "ranks": 8})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes.get("speed", 0) == 1

    def test_shrinking_rank4_stealth(self):
        """Shrinking rank 4: stealth +1 per rank → +4."""
        from build_engine import process_build

        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Shrinking", {"effect": "shrinking", "ranks": 4})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes.get("stealth", 0) == 4

    def test_shrinking_rank4_strength(self):
        """Shrinking rank 4: strength -1 per 4 ranks → -1."""
        from build_engine import process_build

        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Shrinking", {"effect": "shrinking", "ranks": 4})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes.get("strength", 0) == -1

    def test_growth_cost(self):
        """Growth 4: 2/rank → 8 PP (per_rank_effects should not break costing)."""
        from build_engine import process_build

        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Growth", {"effect": "growth", "ranks": 4})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 8


# ===========================================================================
# Resolution classification completeness
# ===========================================================================

VALID_RESOLUTIONS = {"attack_vs_defense", "stat_mod", "opposed_check", "passive", "gm_assisted"}


class TestResolutionClassification:
    def test_all_effects_have_resolution(self):
        """Every effect in effects.json must have a resolution field."""
        effects = _load_effects()
        for key, effect in effects.items():
            if key.startswith("_"):
                continue
            assert "resolution" in effect, f"Effect '{key}' missing resolution field"

    def test_all_resolutions_are_valid(self):
        """Every resolution value must be one of the 5 valid patterns."""
        effects = _load_effects()
        for key, effect in effects.items():
            if key.startswith("_"):
                continue
            res = effect.get("resolution")
            assert res in VALID_RESOLUTIONS, f"Effect '{key}' has invalid resolution: {res}"

    def test_attack_vs_defense_count(self):
        """Exactly 4 effects should be attack_vs_defense."""
        effects = _load_effects()
        avd = [k for k, v in effects.items() if not k.startswith("_") and v.get("resolution") == "attack_vs_defense"]
        assert sorted(avd) == ["affliction", "damage", "nullify", "weaken"]

    def test_stat_mod_count(self):
        """Exactly 4 effects should be stat_mod."""
        effects = _load_effects()
        sm = [k for k, v in effects.items() if not k.startswith("_") and v.get("resolution") == "stat_mod"]
        assert sorted(sm) == ["enhanced_trait", "growth", "protection", "shrinking"]

    def test_opposed_check_count(self):
        """Exactly 3 effects should be opposed_check."""
        effects = _load_effects()
        oc = [k for k, v in effects.items() if not k.startswith("_") and v.get("resolution") == "opposed_check"]
        assert sorted(oc) == ["deflect", "mind_reading", "move_object"]

    def test_passive_count(self):
        """Exactly 2 effects should be passive."""
        effects = _load_effects()
        p = [k for k, v in effects.items() if not k.startswith("_") and v.get("resolution") == "passive"]
        assert sorted(p) == ["immunity", "regeneration"]

    def test_attack_effects_have_metadata(self):
        """attack_vs_defense effects must have attack_stat, defense_stat, outcome_table."""
        effects = _load_effects()
        for key, effect in effects.items():
            if not isinstance(effect, dict):
                continue
            if effect.get("resolution") != "attack_vs_defense":
                continue
            assert "attack_stat" in effect, f"Effect '{key}' missing attack_stat"
            assert "defense_stat" in effect, f"Effect '{key}' missing defense_stat"
            assert "outcome_table" in effect, f"Effect '{key}' missing outcome_table"

    def test_opposed_check_effects_have_metadata(self):
        """opposed_check effects must have defender_stat and attacker_stat."""
        effects = _load_effects()
        for key, effect in effects.items():
            if not isinstance(effect, dict):
                continue
            if effect.get("resolution") != "opposed_check":
                continue
            assert "defender_stat" in effect, f"Effect '{key}' missing defender_stat"
            assert "attacker_stat" in effect, f"Effect '{key}' missing attacker_stat"


# ===========================================================================
# Outcome tables
# ===========================================================================


class TestOutcomeTables:
    def test_outcome_tables_loaded(self):
        """SystemPack should load outcome_tables from system.json."""
        from system_pack import load_system_pack

        pack = load_system_pack(MM3E_SYSTEM)
        assert "damage_degrees" in pack.outcome_tables
        assert "affliction_degrees" in pack.outcome_tables
        assert "weaken_degrees" in pack.outcome_tables
        assert "nullify_degrees" in pack.outcome_tables

    def test_damage_degrees_structure(self):
        """damage_degrees should have success + 4 failure degrees."""
        from system_pack import load_system_pack

        pack = load_system_pack(MM3E_SYSTEM)
        table = pack.outcome_tables["damage_degrees"]
        assert table["success"] == "no_effect"
        assert "increment" in table["1"]
        assert "label" in table["4"]

    def test_affliction_degrees_variable_refs(self):
        """affliction_degrees should use {variable} references for per-effect conditions."""
        from system_pack import load_system_pack

        pack = load_system_pack(MM3E_SYSTEM)
        table = pack.outcome_tables["affliction_degrees"]
        assert "{degree_1_condition}" in table["1"]["label"]
        assert "{degree_2_condition}" in table["2"]["label"]
        assert "{degree_3_condition}" in table["3"]["label"]

    def test_effect_outcome_tables_exist(self):
        """Every outcome_table referenced by effects.json must exist in system.json."""
        from system_pack import load_system_pack

        pack = load_system_pack(MM3E_SYSTEM)
        effects = _load_effects()
        for key, effect in effects.items():
            if not isinstance(effect, dict):
                continue
            table_name = effect.get("outcome_table")
            if table_name:
                assert table_name in pack.outcome_tables, (
                    f"Effect '{key}' references outcome_table '{table_name}' which does not exist in system.json"
                )
