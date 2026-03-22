"""Tests for the data-driven build engine."""

import json
import os

import cruncher_mm3e
import cruncher_pf2e
import pytest

from cruncher.build import BuildResult, process_build

PF2E_SYSTEM = cruncher_pf2e.pack_path()
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


class TestWrites:
    """Test the 'writes' operation — copy fields from source to attributes."""

    def test_ancestry_writes(self):
        char_attrs = {"info": {"ancestry": "human"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=1)
        assert result.attributes["ancestry_hp"] == 8
        assert result.attributes["speed_base"] == 25

    def test_ancestry_elf(self):
        char_attrs = {"info": {"ancestry": "elf"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=1)
        assert result.attributes["ancestry_hp"] == 6
        assert result.attributes["speed_base"] == 30

    def test_ancestry_dwarf(self):
        char_attrs = {"info": {"ancestry": "dwarf"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=1)
        assert result.attributes["ancestry_hp"] == 10
        assert result.attributes["speed_base"] == 20

    def test_class_writes(self):
        char_attrs = {"info": {"class": "fighter"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=1)
        assert result.attributes["hp_per_level"] == 10

    def test_class_wizard(self):
        char_attrs = {"info": {"class": "wizard"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=1)
        assert result.attributes["hp_per_level"] == 6

    def test_no_ancestry_selected(self):
        result = process_build(PF2E_SYSTEM, {}, [], level=1)
        assert "ancestry_hp" not in result.attributes

    def test_unknown_ancestry(self):
        char_attrs = {"info": {"ancestry": "martian"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=1)
        assert "ancestry_hp" not in result.attributes


class TestProgressions:
    """Test the 'progressions' operation — table lookups by level."""

    def test_fighter_level_1_profs(self):
        char_attrs = {"info": {"class": "fighter"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=1)
        # Fighter at level 1: expert perception (4)
        assert result.attributes["prof_perception"] == 4
        # Expert fortitude (4)
        assert result.attributes["prof_fortitude"] == 4
        # Trained will (2)
        assert result.attributes["prof_will"] == 2

    def test_fighter_level_5_weapon_mastery(self):
        char_attrs = {"info": {"class": "fighter"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=5)
        # Master weapons at level 5 (6)
        assert result.attributes["prof_martial_weapons"] == 6
        assert result.attributes["prof_simple_weapons"] == 6

    def test_fighter_level_9_juggernaut(self):
        char_attrs = {"info": {"class": "fighter"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=9)
        # Master fortitude at level 9 (6)
        assert result.attributes["prof_fortitude"] == 6

    def test_rogue_level_7_evasion(self):
        char_attrs = {"info": {"class": "rogue"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=7)
        # Master reflex at level 7 (6)
        assert result.attributes["prof_reflex"] == 6

    def test_wizard_level_7_expert_spell(self):
        char_attrs = {"info": {"class": "wizard"}}
        result = process_build(PF2E_SYSTEM, char_attrs, [], level=7)
        # Expert spell at level 7 (4)
        assert result.attributes["prof_spell_dc"] == 4
        assert result.attributes["prof_spell_attack"] == 4

    def test_no_class_selected(self):
        result = process_build(PF2E_SYSTEM, {}, [], level=5)
        assert "prof_perception" not in result.attributes


class TestEffects:
    """Test the 'effects' operation — feat bonus aggregation."""

    def test_toughness_bonus(self):
        char_attrs = {"info": {}}
        abilities = [
            {"name": "Toughness", "description": "", "category": "general", "uses": ""},
        ]
        result = process_build(PF2E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["bonus_hp"] == 1

    def test_fleet_bonus(self):
        char_attrs = {"info": {}}
        abilities = [
            {"name": "Fleet", "description": "", "category": "general", "uses": ""},
        ]
        result = process_build(PF2E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["bonus_speed"] == 5

    def test_incredible_initiative(self):
        char_attrs = {"info": {}}
        abilities = [
            {"name": "Incredible Initiative", "description": "", "category": "general", "uses": ""},
        ]
        result = process_build(PF2E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["bonus_initiative"] == 2

    def test_combat_option_excluded(self):
        """Combat option feats should NOT contribute always-on bonuses."""
        char_attrs = {"info": {}}
        abilities = [
            {"name": "Power Attack", "description": "", "category": "fighter", "uses": ""},
        ]
        result = process_build(PF2E_SYSTEM, char_attrs, abilities, level=1)
        # Power Attack is a combat option — should not add bonuses
        assert "bonus_melee_attack" not in result.attributes

    def test_multiple_feats_stack(self):
        char_attrs = {"info": {}}
        abilities = [
            {"name": "Toughness", "description": "", "category": "general", "uses": ""},
            {"name": "Fleet", "description": "", "category": "general", "uses": ""},
        ]
        result = process_build(PF2E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["bonus_hp"] == 1
        assert result.attributes["bonus_speed"] == 5

    def test_unknown_feat_ignored(self):
        char_attrs = {"info": {}}
        abilities = [
            {"name": "Nonexistent Feat", "description": "", "category": "general", "uses": ""},
        ]
        result = process_build(PF2E_SYSTEM, char_attrs, abilities, level=1)
        # No crash, no attributes set
        assert len(result.attributes) == 0


class TestFullBuild:
    """Integration test: build engine produces correct attributes for full characters."""

    def test_fighter_level_1_full(self):
        char_attrs = {
            "info": {"ancestry": "human", "class": "fighter"},
        }
        abilities = [
            {"name": "Toughness", "description": "", "category": "general", "uses": ""},
        ]
        result = process_build(PF2E_SYSTEM, char_attrs, abilities, level=1)

        # Ancestry writes
        assert result.attributes["ancestry_hp"] == 8
        assert result.attributes["speed_base"] == 25

        # Class writes
        assert result.attributes["hp_per_level"] == 10

        # Class progressions
        assert result.attributes["prof_perception"] == 4
        assert result.attributes["prof_fortitude"] == 4
        assert result.attributes["prof_will"] == 2

        # Feat effects
        assert result.attributes["bonus_hp"] == 1

    def test_no_build_section(self, tmp_path):
        """System without build section returns empty result."""
        system_file = tmp_path / "system.json"
        system_file.write_text('{"meta": {"name": "Minimal"}}')
        result = process_build(str(tmp_path), {}, [], level=1)
        assert result.attributes == {}

    def test_missing_system_returns_empty(self, tmp_path):
        result = process_build(str(tmp_path / "nonexistent"), {}, [], level=1)
        assert result.attributes == {}


# ---------------------------------------------------------------------------
# M&M 3e build tests
# ---------------------------------------------------------------------------

MM3E_SYSTEM = cruncher_mm3e.pack_path()


def _power_ability(name, power_json, category="power"):
    """Helper: create an ability dict with power JSON in the description."""
    return {
        "name": name,
        "description": json.dumps(power_json),
        "category": category,
        "uses": "",
    }


class TestMM3eBudget:
    """Test budget setup from power_level."""

    def test_default_pl10_budget(self):
        char_attrs = {"stat": {"power_level": "10"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert result.budget_total == 150

    def test_pl8_budget(self):
        char_attrs = {"stat": {"power_level": "8"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert result.budget_total == 120

    def test_pl12_budget(self):
        char_attrs = {"stat": {"power_level": "12"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert result.budget_total == 180


class TestMM3eAbilities:
    """Test ability cost tracking."""

    def test_ability_costs(self):
        char_attrs = {"stat": {"str": "2", "sta": "3", "power_level": "10"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        # str=2 * 2pp + sta=3 * 2pp = 10pp
        assert result.costs["ability"] == 10

    def test_negative_abilities(self):
        char_attrs = {"stat": {"str": "-1", "int": "5", "power_level": "10"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        # str=-1 * 2 + int=5 * 2 = -2 + 10 = 8pp
        assert result.costs["ability"] == 8

    def test_no_abilities_set(self):
        char_attrs = {"stat": {"power_level": "10"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert "ability" not in result.costs


class TestMM3eDefenses:
    """Test defense purchase cost tracking."""

    def test_defense_costs(self):
        char_attrs = {
            "stat": {
                "ranks_dodge": "5",
                "ranks_parry": "3",
                "ranks_fortitude": "4",
                "ranks_will": "6",
                "power_level": "10",
            }
        }
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        # 5 + 3 + 4 + 6 = 18 PP
        assert result.costs["defense"] == 18

    def test_no_defense_purchases(self):
        char_attrs = {"stat": {"power_level": "10"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert "defense" not in result.costs


class TestMM3eSkills:
    """Test skill cost tracking (0.5 PP per rank)."""

    def test_skill_costs(self):
        char_attrs = {
            "stat": {
                "ranks_acrobatics": "8",
                "ranks_perception": "4",
                "power_level": "10",
            }
        }
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        # 12 ranks * 0.5 = 6 PP
        assert result.costs["skill"] == 6

    def test_odd_ranks_round_up(self):
        char_attrs = {
            "stat": {
                "ranks_athletics": "5",
                "power_level": "10",
            }
        }
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        # 5 ranks * 0.5 = 2.5 → ceil = 3 PP
        assert result.costs["skill"] == 3


class TestMM3eAdvantages:
    """Test advantage effects and cost tracking."""

    def test_close_attack_effect(self):
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            {"name": "Close Attack", "description": "", "category": "advantage", "uses": ""},
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["adv_close_attack"] == 1
        assert result.costs["advantage"] == 1

    def test_defensive_roll_effect(self):
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            {"name": "Defensive Roll", "description": "", "category": "advantage", "uses": ""},
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["adv_defensive_roll"] == 1

    def test_equipment_effect(self):
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            {"name": "Equipment", "description": "", "category": "advantage", "uses": ""},
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["adv_equipment"] == 1

    def test_combat_option_excluded(self):
        """Combat options like Accurate Attack don't produce always-on effects."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            {"name": "Accurate Attack", "description": "", "category": "advantage", "uses": ""},
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert "bonus_attack" not in result.attributes


class TestMM3ePipeline:
    """Test power cost computation via the pipeline stages."""

    def test_basic_damage(self):
        """Damage 10: base 1/rank, no mods → 10 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Blast", {"effect": "damage", "ranks": 10})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 10

    def test_ranged_damage(self):
        """Damage 10 + Increased Range (+1/rank) → 2/rank × 10 = 20 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability(
                "Blast",
                {
                    "effect": "damage",
                    "ranks": 10,
                    "extras": ["increased_range"],
                },
            )
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 20

    def test_limited_damage(self):
        """Damage 10 + Limited (-1/rank) → (1-1)=0 effective, fractional: ceil(10/2)=5 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability(
                "Blast",
                {
                    "effect": "damage",
                    "ranks": 10,
                    "flaws": ["limited"],
                },
            )
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 5

    def test_flight_basic(self):
        """Flight 8: base 2/rank → 16 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Flight", {"effect": "flight", "ranks": 8})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 16

    def test_protection_basic(self):
        """Protection 10: base 1/rank → 10 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Armor", {"effect": "protection", "ranks": 10})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 10

    def test_removable_device(self):
        """Protection 10 (Removable -1/5) → 10 - (10/5)*1 = 8 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability(
                "Shield",
                {
                    "effect": "protection",
                    "ranks": 10,
                    "removable": 1,
                },
            )
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 8

    def test_easily_removable(self):
        """Protection 10 (Easily Removable -2/5) → 10 - (10/5)*2 = 6 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability(
                "Shield",
                {
                    "effect": "protection",
                    "ranks": 10,
                    "removable": 2,
                },
            )
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 6

    def test_flat_extras(self):
        """Damage 10 + Subtle (flat +1) → 10 + 1 = 11 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability(
                "Blast",
                {
                    "effect": "damage",
                    "ranks": 10,
                    "flat_extras": ["subtle"],
                },
            )
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 11

    def test_multiple_extras_and_flaws(self):
        """Damage 10 + Increased Range (+1) + Multiattack (+1) + Limited (-1) → 2/rank × 10 = 20 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability(
                "Blast",
                {
                    "effect": "damage",
                    "ranks": 10,
                    "extras": ["increased_range", "multiattack"],
                    "flaws": ["limited"],
                },
            )
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 20

    def test_multiple_powers_sum(self):
        """Two powers: Damage 10 (10 PP) + Flight 5 (10 PP) = 20 PP total."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blast", {"effect": "damage", "ranks": 10}),
            _power_ability("Flight", {"effect": "flight", "ranks": 5}),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 20


class TestMM3eFeeds:
    """Test power feeds — stat contributions from powers."""

    def test_protection_feeds_toughness(self):
        """Protection with feeds writes to effect_protection."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability(
                "Armor",
                {
                    "effect": "protection",
                    "ranks": 10,
                    "feeds": {"effect_protection": 10},
                },
            )
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["effect_protection"] == 10

    def test_enhanced_ability_feeds(self):
        """Enhanced Strength feeds effective_str via effect_enhanced_str."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability(
                "Enhanced Strength",
                {
                    "effect": "enhanced_trait",
                    "ranks": 5,
                    "feeds": {"effect_enhanced_str": 5},
                },
            )
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["effect_enhanced_str"] == 5

    def test_multiple_feeds_stack(self):
        """Two powers feeding the same stat should stack."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability(
                "Armor",
                {
                    "effect": "protection",
                    "ranks": 5,
                    "feeds": {"effect_protection": 5},
                },
            ),
            _power_ability(
                "Force Field",
                {
                    "effect": "protection",
                    "ranks": 3,
                    "feeds": {"effect_protection": 3},
                },
            ),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["effect_protection"] == 8


class TestMM3eArrays:
    """Test power arrays — alternate effects cost flat PP."""

    def test_alternate_effect_cost(self):
        """An alternate effect costs 1 PP (not the full power cost)."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blast", {"effect": "damage", "ranks": 10, "extras": ["increased_range"]}),
            _power_ability("Strike", {"effect": "damage", "ranks": 10, "array_of": "Blast"}),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        # Primary: 20 PP, Alternate: 1 PP
        assert result.costs["powers"] == 20
        assert result.costs["arrays"] == 1

    def test_dynamic_alternate_cost(self):
        """A dynamic alternate effect costs 2 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blast", {"effect": "damage", "ranks": 10, "extras": ["increased_range"]}),
            _power_ability("Strike", {"effect": "damage", "ranks": 10, "array_of": "Blast", "dynamic": True}),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["arrays"] == 2

    def test_multiple_alternates(self):
        """Multiple alternates each cost their flat PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blast", {"effect": "damage", "ranks": 10, "extras": ["increased_range"]}),
            _power_ability("Strike", {"effect": "damage", "ranks": 10, "array_of": "Blast"}),
            _power_ability(
                "Snare", {"effect": "affliction", "ranks": 10, "extras": ["increased_range"], "array_of": "Blast"}
            ),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["arrays"] == 2  # 1 + 1

    def test_alternate_not_counted_as_power_cost(self):
        """Alternate effects shouldn't add to power costs, only array costs."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blast", {"effect": "damage", "ranks": 10}),
            _power_ability("Strike", {"effect": "damage", "ranks": 10, "array_of": "Blast"}),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        # Only the primary's cost in powers
        assert result.costs["powers"] == 10


class TestMM3eSubBudget:
    """Test sub-budget — equipment points from Equipment advantage."""

    def test_equipment_sub_budget(self):
        """Equipment 3 → 15 equipment points."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            {"name": "Equipment", "description": "", "category": "advantage", "uses": ""},
            {"name": "Equipment", "description": "", "category": "advantage", "uses": ""},
            {"name": "Equipment", "description": "", "category": "advantage", "uses": ""},
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.attributes["adv_equipment"] == 3
        assert result.attributes["equipment_points_total"] == 15


class TestMM3eBudgetTotal:
    """Test that budget_spent sums all cost categories."""

    def test_total_spent(self):
        """All categories sum into budget_spent."""
        char_attrs = {
            "stat": {
                "str": "2",
                "sta": "2",  # 8 PP abilities
                "ranks_dodge": "5",  # 5 PP defense
                "ranks_acrobatics": "4",  # 2 PP skills
                "power_level": "10",
            }
        }
        abilities = [
            {"name": "Close Attack", "description": "", "category": "advantage", "uses": ""},
            _power_ability("Blast", {"effect": "damage", "ranks": 10}),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        # abilities=8 + defenses=5 + skills=2 + advantage=1 + powers=10 = 26
        assert result.budget_total == 150
        assert result.budget_spent == 26


# ---------------------------------------------------------------------------
# Equipment build tests
# ---------------------------------------------------------------------------


class TestEquipment:
    """Test the 'equipped' select mode — equipment items to attributes."""

    def test_equipment_armor_writes(self):
        """Equipped armor writes AC bonus and dex cap."""
        char_items = [{"name": "Chain mail", "description": "", "quantity": 1}]
        result = process_build(TEST_SYSTEM, {}, [], level=1, char_items=char_items)
        assert result.attributes["item_bonus_ac"] == 4
        assert result.attributes["armor_dex_cap"] == 1
        assert result.attributes["armor_check_penalty"] == -2
        assert result.attributes["armor_speed_penalty"] == -5

    def test_equipment_weapon_writes(self):
        """Equipped weapon writes damage die and type."""
        char_items = [{"name": "Longsword", "description": "", "quantity": 1}]
        result = process_build(TEST_SYSTEM, {}, [], level=1, char_items=char_items)
        assert result.attributes["weapon_damage_die"] == "1d8"
        assert result.attributes["weapon_damage_type"] == "S"
        assert result.attributes["weapon_group"] == "Sword"
        assert result.attributes["weapon_traits"] == ["versatile_P"]

    def test_equipment_shield_writes(self):
        """Equipped shield writes shield bonus."""
        char_items = [{"name": "Steel shield", "description": "", "quantity": 1}]
        result = process_build(TEST_SYSTEM, {}, [], level=1, char_items=char_items)
        assert result.attributes["shield_bonus"] == 2

    def test_equipment_not_found(self):
        """Unknown item is silently ignored."""
        char_items = [{"name": "Vorpal Blade", "description": "", "quantity": 1}]
        result = process_build(TEST_SYSTEM, {}, [], level=1, char_items=char_items)
        assert "weapon_damage_die" not in result.attributes

    def test_equipment_no_items(self):
        """No items → no equipment attributes."""
        result = process_build(TEST_SYSTEM, {}, [], level=1, char_items=[])
        assert "item_bonus_ac" not in result.attributes

    def test_mm3e_melee_weapon_writes(self):
        """M&M 3e: equipping a sword writes close damage stats."""
        char_items = [{"name": "sword", "description": "", "quantity": 1}]
        result = process_build(MM3E_SYSTEM, {}, [], level=1, char_items=char_items)
        assert result.attributes["weapon_close_damage"] == 3
        assert result.attributes["weapon_damage_type"] == "slashing"
        assert result.attributes["weapon_strength_based"] is True
        assert result.attributes["weapon_critical"] == 19

    def test_mm3e_ranged_weapon_writes(self):
        """M&M 3e: equipping a heavy pistol writes ranged damage stats."""
        char_items = [{"name": "Heavy Pistol", "description": "", "quantity": 1}]
        result = process_build(MM3E_SYSTEM, {}, [], level=1, char_items=char_items)
        assert result.attributes["weapon_ranged_damage"] == 4
        assert result.attributes["weapon_damage_type"] == "ballistic"
        assert result.attributes["weapon_critical"] == 20

    def test_mm3e_armor_writes(self):
        """M&M 3e: equipping leather armor writes effect_protection."""
        char_items = [{"name": "Leather Armor", "description": "", "quantity": 1}]
        result = process_build(MM3E_SYSTEM, {}, [], level=1, char_items=char_items)
        assert result.attributes["effect_protection"] == 1

    def test_mm3e_shield_writes(self):
        """M&M 3e: equipping a medium shield writes dodge/parry bonuses."""
        char_items = [{"name": "Medium Shield", "description": "", "quantity": 1}]
        result = process_build(MM3E_SYSTEM, {}, [], level=1, char_items=char_items)
        assert result.attributes["bonus_dodge"] == 2
        assert result.attributes["bonus_parry"] == 2

    def test_mm3e_unknown_equipment_ignored(self):
        """M&M 3e: unknown equipment is silently ignored."""
        char_items = [{"name": "unobtanium_blade", "description": "", "quantity": 1}]
        result = process_build(MM3E_SYSTEM, {}, [], level=1, char_items=char_items)
        assert "weapon_close_damage" not in result.attributes


class TestMM3eExplicitCost:
    """Test explicit cost fallback for unstructured powers."""

    def test_explicit_cost_tracked(self):
        """Power with {"cost": 20} is tracked without needing effect/pipeline."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Gadget", {"cost": 20})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 20
        assert result.ability_costs["powers"]["Gadget"] == 20

    def test_effect_takes_precedence(self):
        """When both effect and cost are present, pipeline cost is used."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [_power_ability("Blast", {"effect": "damage", "ranks": 10, "cost": 999})]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        # Pipeline computes 10, not the explicit 999
        assert result.costs["powers"] == 10

    def test_mixed_pipeline_and_explicit(self):
        """Pipeline power + explicit cost power sum correctly."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blast", {"effect": "damage", "ranks": 10}),
            _power_ability("Gadget", {"cost": 5}),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs["powers"] == 15
        assert result.ability_costs["powers"]["Blast"] == 10
        assert result.ability_costs["powers"]["Gadget"] == 5

    def test_plain_text_still_ignored(self):
        """Plain text description (not JSON) is still ignored."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            {"name": "Narration Power", "description": "A cool power that does stuff", "category": "power", "uses": ""},
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert "powers" not in result.costs


class TestMM3eAbilityCosts:
    """Test per-ability cost tracking in ability_costs dict."""

    def test_per_ability_costs_populated(self):
        """ability_costs tracks individual power costs."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blast", {"effect": "damage", "ranks": 10, "extras": ["increased_range"]}),
            _power_ability("Force Field", {"effect": "protection", "ranks": 8}),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.ability_costs["powers"]["Blast"] == 20
        assert result.ability_costs["powers"]["Force Field"] == 8
        assert result.costs["powers"] == 28

    def test_array_costs_tracked_separately(self):
        """Array alternates tracked under 'arrays' category."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blast", {"effect": "damage", "ranks": 10, "extras": ["increased_range"]}),
            _power_ability("Strike", {"effect": "damage", "ranks": 10, "array_of": "Blast"}),
            _power_ability("Snare", {"effect": "affliction", "ranks": 10, "array_of": "Blast", "dynamic": True}),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.ability_costs["powers"]["Blast"] == 20
        assert result.ability_costs["arrays"]["Strike"] == 1
        assert result.ability_costs["arrays"]["Snare"] == 2

    def test_no_abilities_no_ability_costs(self):
        """No powers → empty ability_costs."""
        char_attrs = {"stat": {"power_level": "10"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert result.ability_costs == {}


class TestMM3eStatPrefix:
    """Test stat_prefix — cost tallying from stats set directly."""

    def test_advantage_stat_costed(self):
        """adv_close_attack=10 as a stat costs 10 PP via stat_prefix."""
        char_attrs = {"stat": {"adv_close_attack": "10", "power_level": "10"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert result.costs["advantage"] == 10
        assert result.ability_costs["advantage"]["adv_close_attack"] == 10

    def test_multiple_advantage_stats(self):
        """Multiple adv_* stats are all tallied."""
        char_attrs = {
            "stat": {
                "adv_close_attack": "10",
                "adv_improved_initiative": "5",
                "adv_evasion": "2",
                "power_level": "10",
            }
        }
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert result.costs["advantage"] == 17

    def test_stat_and_ability_no_double_count(self):
        """If both adv_close_attack stat AND Close Attack ability exist, don't double-count."""
        char_attrs = {"stat": {"adv_close_attack": "5", "power_level": "10"}}
        abilities = [
            {"name": "Close Attack", "description": "", "category": "advantage", "uses": ""},
            {"name": "Close Attack", "description": "", "category": "advantage", "uses": ""},
            {"name": "Close Attack", "description": "", "category": "advantage", "uses": ""},
            {"name": "Close Attack", "description": "", "category": "advantage", "uses": ""},
            {"name": "Close Attack", "description": "", "category": "advantage", "uses": ""},
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        # Ability sets adv_close_attack=5 via effects → covered by ability cost (5 PP)
        # Stat adv_close_attack=5 should be skipped (key in covered_stats)
        assert result.costs["advantage"] == 5

    def test_effect_stat_costed(self):
        """effect_protection=10 as a stat costs 10 PP via stat_prefix on power rule."""
        char_attrs = {"stat": {"effect_protection": "10", "power_level": "10"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert result.costs["powers"] == 10

    def test_effect_stat_with_structured_power_no_double(self):
        """Structured power feeding effect_protection + stat should not double-count."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Armor", {"effect": "protection", "ranks": 10, "feeds": {"effect_protection": 10}}),
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        # Pipeline costs 10 PP. No stat to double-count since effect_protection
        # comes from feeds (covered).
        assert result.costs["powers"] == 10

    def test_effect_stat_with_explicit_cost_no_double(self):
        """Power with explicit cost + matching stat should not double-count."""
        char_attrs = {"stat": {"effect_protection": "10", "power_level": "10"}}
        abilities = [
            {"name": "Protection 10", "description": "Protection effect.", "category": "power", "uses": "", "cost": 10},
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        # Explicit cost 10 PP covers effect_protection.
        assert result.costs["powers"] == 10

    def test_mixed_stat_and_ability_advantages(self):
        """Stat advantages + ability advantages sum correctly."""
        char_attrs = {
            "stat": {
                "adv_close_attack": "10",
                "power_level": "10",
            }
        }
        abilities = [
            {"name": "Fearless", "description": "", "category": "advantage", "uses": ""},
            {"name": "Power Attack", "description": "", "category": "advantage", "uses": ""},
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        # adv_close_attack=10 (stat) + Fearless=1 + Power Attack=1 = 12
        assert result.costs["advantage"] == 12

    def test_zero_stat_ignored(self):
        """Stats with value 0 are not counted."""
        char_attrs = {"stat": {"adv_close_attack": "0", "power_level": "10"}}
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert "advantage" not in result.costs

    def test_budget_includes_stat_costs(self):
        """budget_spent sums all categories including stat-derived costs."""
        char_attrs = {
            "stat": {
                "str": "5",  # 10 PP
                "adv_close_attack": "5",  # 5 PP
                "effect_protection": "5",  # 5 PP
                "power_level": "10",
            }
        }
        result = process_build(MM3E_SYSTEM, char_attrs, [], level=1)
        assert result.budget_total == 150
        assert result.budget_spent == 20  # 10 + 5 + 5


class TestMM3eArrayOfDesc:
    """Test array_of detection from description JSON."""

    def test_array_of_in_desc_json(self):
        """array_of in description JSON is detected by _process_arrays."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blink", {"effect": "movement", "ranks": 11}),
            {
                "name": "Banish",
                "description": json.dumps({"array_of": "Blink", "desc": "Teleporte ofensivo"}),
                "category": "power",
                "uses": "",
            },
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs.get("arrays") == 1
        assert result.ability_costs["arrays"]["Banish"] == 1

    def test_array_of_with_dynamic(self):
        """Dynamic alternate in description JSON costs 2 PP."""
        char_attrs = {"stat": {"power_level": "10"}}
        abilities = [
            _power_ability("Blink", {"effect": "movement", "ranks": 11}),
            {
                "name": "Banish",
                "description": json.dumps({"array_of": "Blink", "dynamic": True}),
                "category": "power",
                "uses": "",
            },
        ]
        result = process_build(MM3E_SYSTEM, char_attrs, abilities, level=1)
        assert result.costs.get("arrays") == 2


class TestEquipmentPf2e:
    """PF2e equipment tests (split from TestEquipment for clarity)."""

    def test_equipment_pf2e_armor(self):
        """PF2e system: chain mail equipped writes correct stats."""
        char_items = [{"name": "Chain mail", "description": "", "quantity": 1}]
        result = process_build(PF2E_SYSTEM, {}, [], level=1, char_items=char_items)
        assert result.attributes["item_bonus_ac"] == 4
        assert result.attributes["armor_dex_cap"] == 1

    def test_equipment_pf2e_weapon(self):
        """PF2e system: longsword writes damage stats."""
        char_items = [{"name": "Longsword", "description": "", "quantity": 1}]
        result = process_build(PF2E_SYSTEM, {}, [], level=1, char_items=char_items)
        assert result.attributes["weapon_damage_die"] == "1d8"
        assert result.attributes["weapon_damage_type"] == "S"
