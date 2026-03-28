"""Tests for the Pathfinder 2e system pack.

Validates that the PF2e system pack loads correctly and produces
accurate derived stats for various class/level combinations.

Note: The rules engine is domain-agnostic. Class proficiency values
(prof_*), hp_per_level, and key_ability_mod are character attributes
set by the build engine. Tests set them directly to match what the
build engine would write from class progression tables.
"""

import json
import math
import os

import cruncher_pf2e
import pytest

from cruncher.engine import recalculate
from cruncher.system_pack import load_system_pack
from cruncher.types import CharacterData

PF2E_SYSTEM = cruncher_pf2e.pack_path()


def _load_class_profs(class_name: str, level: int) -> dict[str, str]:
    """Load proficiency values from a class JSON at a given level.

    Simulates what the build engine would do: read the class's
    progression tables and return the prof_* values as a dict.
    """
    class_path = os.path.join(PF2E_SYSTEM, "classes", f"{class_name}.json")
    with open(class_path) as f:
        cls_data = json.load(f)

    profs = {}
    for var_name, table_key in cls_data["meta"]["progressions"].items():
        table = cls_data["tables"][table_key]
        if level <= len(table):
            profs[var_name] = str(table[level - 1])
    return profs


class TestPF2ESystemPack:
    def test_loads_successfully(self):
        pack = load_system_pack(PF2E_SYSTEM)
        assert pack.name == "Pathfinder 2e (Remaster)"
        assert pack.dice == "d20"

    def test_derived_formulas_present(self):
        pack = load_system_pack(PF2E_SYSTEM)
        assert "str_mod" in pack.derived
        assert "armor_class" in pack.derived
        assert "max_hp" in pack.derived

    def test_skill_formulas_present(self):
        pack = load_system_pack(PF2E_SYSTEM)
        assert "skill_athletics" in pack.derived
        assert "skill_stealth" in pack.derived
        assert "skill_arcana" in pack.derived
        assert "str_mod" in pack.derived["skill_athletics"]
        assert "dex_mod" in pack.derived["skill_stealth"]

    def test_defaults_present(self):
        pack = load_system_pack(PF2E_SYSTEM)
        assert pack.defaults["ancestry_hp"] == 0
        assert pack.defaults["item_bonus_ac"] == 0
        assert pack.defaults["armor_dex_cap"] == 99

    def test_build_section_present(self):
        pack_path = os.path.join(PF2E_SYSTEM, "system.json")
        with open(pack_path) as f:
            data = json.load(f)
        assert "build" in data
        assert "ancestry" in data["build"]
        assert "class" in data["build"]
        assert "feat" in data["build"]


class TestPF2EFighterCalc:
    """Test derived stat calculation for a PF2e Fighter."""

    def _make_fighter(
        self, level=1, str_score=18, dex_score=14, con_score=12, int_score=10, wis_score=12, cha_score=10, ancestry_hp=8
    ) -> CharacterData:
        char = CharacterData(
            character_id=1,
            session_id=1,
            name="Valeros",
            level=level,
            char_type="pc",
        )
        char.attributes["stat"] = {
            "str": str(str_score),
            "dex": str(dex_score),
            "con": str(con_score),
            "int": str(int_score),
            "wis": str(wis_score),
            "cha": str(cha_score),
        }
        key_mod = math.floor((str_score - 10) / 2)
        char.attributes["build"] = {
            "ancestry_hp": str(ancestry_hp),
            "hp_per_level": "10",
            "key_ability_mod": str(key_mod),
        }
        # Load proficiency progressions from fighter class tables
        profs = _load_class_profs("fighter", level)
        char.attributes["build"].update(profs)
        return char

    def test_level_1_hp(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, con_score=14)
        # ancestry_hp(8) + (hp_per_level(10) + con_mod(2)) * 1 = 8 + 12 = 20
        result = recalculate(pack, char)
        assert result.derived["max_hp"] == 20

    def test_level_5_hp(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=5, con_score=14)
        # 8 + (10 + 2) * 5 = 8 + 60 = 68
        result = recalculate(pack, char)
        assert result.derived["max_hp"] == 68

    def test_level_1_ac_unarmored(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, dex_score=14)
        # 10 + min(dex_mod(2), dex_cap(99)) + if(prof_unarmored(2)>0, 2+1, 0) + 0 + 0
        # = 10 + 2 + 3 = 15
        result = recalculate(pack, char)
        assert result.derived["armor_class"] == 15

    def test_level_1_saves(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, con_score=14, dex_score=14, wis_score=12)
        result = recalculate(pack, char)
        # Fort: con_mod(2) + if(prof(4)>0, 4+1, 0) = 2 + 5 = 7
        assert result.derived["fortitude"] == 7
        # Reflex: dex_mod(2) + if(prof(4)>0, 4+1, 0) = 2 + 5 = 7
        assert result.derived["reflex"] == 7
        # Will: wis_mod(1) + if(prof(2)>0, 2+1, 0) = 1 + 3 = 4
        assert result.derived["will"] == 4

    def test_level_1_perception(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, wis_score=12)
        # wis_mod(1) + if(prof(4)>0, 4+1, 0) = 1 + 5 = 6
        result = recalculate(pack, char)
        assert result.derived["perception"] == 6

    def test_level_1_class_dc(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, str_score=18)
        # 10 + key_ability_mod(4) + if(prof_class_dc(2)>0, 2+1, 0)
        # = 10 + 4 + 3 = 17
        result = recalculate(pack, char)
        assert result.derived["class_dc"] == 17

    def test_level_5_proficiency_bump(self):
        """At level 5, fighter gets weapon mastery (weapons → master)."""
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=5, con_score=14)
        result = recalculate(pack, char)
        # HP: 8 + (10+2)*5 = 68
        assert result.derived["max_hp"] == 68
        # Fort at level 5: con_mod(2) + if(prof(4)>0, 4+5, 0) = 2+9 = 11
        assert result.derived["fortitude"] == 11

    def test_level_10_fighter(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=10, str_score=20, con_score=16, dex_score=14, wis_score=12)
        result = recalculate(pack, char)
        # HP: 8 + (10+3)*10 = 138
        assert result.derived["max_hp"] == 138
        # Fort: level 9 juggernaut → master(6). 3 + (6+10) = 19
        assert result.derived["fortitude"] == 19
        # Will: level 3 bravery → expert(4). 1 + (4+10) = 15
        assert result.derived["will"] == 15

    def test_skill_athletics_trained(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, str_score=18)
        # Manually set athletics as trained
        char.attributes["proficiency"] = {"prof_athletics": "2"}
        result = recalculate(pack, char)
        # str_mod(4) + if(prof(2)>0, 2+1, 0) = 4 + 3 = 7
        assert result.derived["skill_athletics"] == 7

    def test_skill_untrained(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=5, str_score=18)
        # Athletics NOT set → defaults to 0 (untrained)
        result = recalculate(pack, char)
        # str_mod(4) + if(0>0, ..., 0) = 4 + 0 = 4
        assert result.derived["skill_athletics"] == 4

    def test_toughness_feat_via_bonus(self):
        """Toughness feat effect is pre-aggregated as bonus_hp by build engine."""
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=5, con_score=14)
        char.attributes["build"]["bonus_hp"] = "1"
        result = recalculate(pack, char)
        # HP: 8 + (10+2)*5 + 1 = 69
        assert result.derived["max_hp"] == 69

    def test_armor_speed_penalty(self):
        """Heavy armor reduces speed."""
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, dex_score=14)
        char.attributes["build"]["armor_speed_penalty"] = "-10"
        result = recalculate(pack, char)
        assert result.derived["speed"] == 15

    def test_armor_check_penalty_athletics(self):
        """Armor check penalty applies to STR/DEX skill checks."""
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, str_score=18)
        char.attributes["proficiency"] = {"prof_athletics": "2"}
        char.attributes["build"]["armor_check_penalty"] = "-3"
        result = recalculate(pack, char)
        assert result.derived["skill_athletics"] == 4

    def test_armor_check_penalty_stealth(self):
        """Armor check penalty applies to stealth."""
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, dex_score=14)
        char.attributes["proficiency"] = {"prof_stealth": "2"}
        char.attributes["build"]["armor_check_penalty"] = "-2"
        result = recalculate(pack, char)
        assert result.derived["skill_stealth"] == 3

    def test_no_armor_no_penalty(self):
        """Unarmored: no penalties (defaults are 0)."""
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, str_score=18)
        char.attributes["proficiency"] = {"prof_athletics": "2"}
        result = recalculate(pack, char)
        assert result.derived["skill_athletics"] == 7
        assert result.derived["speed"] == 25

    def test_bulk_limit(self):
        """Bulk limit is 5 + STR modifier."""
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, str_score=18)
        result = recalculate(pack, char)
        # 5 + str_mod(4) = 9
        assert result.derived["bulk_limit"] == 9
        assert result.derived["bulk_over"] == 0

    def test_bulk_over_limit(self):
        """Bulk over limit is tracked."""
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_fighter(level=1, str_score=14)
        char.attributes["build"]["total_bulk"] = "10"
        result = recalculate(pack, char)
        # bulk_limit = 5 + str_mod(2) = 7, over = max(0, 10 - 7) = 3
        assert result.derived["bulk_limit"] == 7
        assert result.derived["bulk_over"] == 3


class TestPF2EWizardCalc:
    """Test derived stat calculation for a PF2e Wizard."""

    def _make_wizard(self, level=1, int_score=18, con_score=12, dex_score=12, wis_score=14) -> CharacterData:
        char = CharacterData(
            character_id=2,
            session_id=1,
            name="Ezren",
            level=level,
            char_type="pc",
        )
        char.attributes["stat"] = {
            "str": "10",
            "dex": str(dex_score),
            "con": str(con_score),
            "int": str(int_score),
            "wis": str(wis_score),
            "cha": "10",
        }
        key_mod = math.floor((int_score - 10) / 2)
        char.attributes["build"] = {
            "ancestry_hp": "6",
            "hp_per_level": "6",
            "key_ability_mod": str(key_mod),
        }
        profs = _load_class_profs("wizard", level)
        char.attributes["build"].update(profs)
        return char

    def test_level_1_hp(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_wizard(level=1, con_score=12)
        # 6 + (6 + 1) * 1 = 13
        result = recalculate(pack, char)
        assert result.derived["max_hp"] == 13

    def test_level_1_spell_dc(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_wizard(level=1, int_score=18)
        # 10 + key_mod(4) + if(prof_spell_dc(2)>0, 2+1, 0) = 17
        result = recalculate(pack, char)
        assert result.derived["spell_dc"] == 17

    def test_level_7_expert_spellcaster(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_wizard(level=7, int_score=20)
        result = recalculate(pack, char)
        # Spell DC: 10 + 5 + if(4>0, 4+7, 0) = 10 + 5 + 11 = 26
        assert result.derived["spell_dc"] == 26

    def test_will_save_expert(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_wizard(level=1, wis_score=14)
        # wis_mod(2) + if(prof(4)>0, 4+1, 0) = 2 + 5 = 7
        result = recalculate(pack, char)
        assert result.derived["will"] == 7


class TestPF2ERogueCalc:
    """Test derived stat calculation for a PF2e Rogue."""

    def _make_rogue(self, level=1, dex_score=18, con_score=12) -> CharacterData:
        char = CharacterData(
            character_id=3,
            session_id=1,
            name="Merisiel",
            level=level,
            char_type="pc",
        )
        char.attributes["stat"] = {
            "str": "10",
            "dex": str(dex_score),
            "con": str(con_score),
            "int": "12",
            "wis": "14",
            "cha": "10",
        }
        key_mod = math.floor((dex_score - 10) / 2)
        char.attributes["build"] = {
            "ancestry_hp": "6",
            "hp_per_level": "8",
            "key_ability_mod": str(key_mod),
        }
        profs = _load_class_profs("rogue", level)
        char.attributes["build"].update(profs)
        return char

    def test_level_1_hp(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_rogue(level=1, con_score=12)
        # 6 + (8 + 1) * 1 = 15
        result = recalculate(pack, char)
        assert result.derived["max_hp"] == 15

    def test_perception_expert(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_rogue(level=1)
        # wis_mod(2) + if(prof(4)>0, 4+1, 0) = 2 + 5 = 7
        result = recalculate(pack, char)
        assert result.derived["perception"] == 7

    def test_reflex_expert(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_rogue(level=1, dex_score=18)
        # dex_mod(4) + if(prof(4)>0, 4+1, 0) = 4 + 5 = 9
        result = recalculate(pack, char)
        assert result.derived["reflex"] == 9

    def test_level_7_evasion(self):
        """At level 7, rogue gets Evasion (reflex → master)."""
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_rogue(level=7, dex_score=20)
        result = recalculate(pack, char)
        # Reflex: dex_mod(5) + if(prof(6)>0, 6+7, 0) = 5 + 13 = 18
        assert result.derived["reflex"] == 18


class TestPF2EBackgroundIntegration:
    """Test background effects on skill proficiencies and lore skills."""

    def _make_character_with_bg_effects(self, prof_attrs, level=1, int_score=14, wis_score=12):
        char = CharacterData(
            character_id=10,
            session_id=1,
            name="TestBG",
            level=level,
            char_type="pc",
        )
        char.attributes["stat"] = {
            "str": "10",
            "dex": "10",
            "con": "10",
            "int": str(int_score),
            "wis": str(wis_score),
            "cha": "10",
        }
        key_mod = math.floor((int_score - 10) / 2)
        char.attributes["build"] = {
            "ancestry_hp": "8",
            "hp_per_level": "8",
            "key_ability_mod": str(key_mod),
        }
        profs = _load_class_profs("wizard", level)
        char.attributes["build"].update(profs)
        for k, v in prof_attrs.items():
            char.attributes["build"][k] = str(v)
        return char

    def test_acolyte_trains_religion(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_character_with_bg_effects({"prof_religion": 2}, int_score=14, wis_score=14)
        result = recalculate(pack, char)
        # wis_mod(2) + if(2>0, 2+1, 0) = 2 + 3 = 5
        assert result.derived["skill_religion"] == 5

    def test_acolyte_has_lore_skill(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_character_with_bg_effects({"prof_lore_scribing": 2}, int_score=14)
        result = recalculate(pack, char)
        # int_mod(2) + if(2>0, 2+1, 0) = 2 + 3 = 5
        assert result.derived["skill_lore_scribing"] == 5

    def test_criminal_trains_stealth(self):
        pack = load_system_pack(PF2E_SYSTEM)
        char = self._make_character_with_bg_effects({"prof_stealth": 2}, int_score=10)
        result = recalculate(pack, char)
        # dex_mod(0) + if(2>0, 2+1, 0) + armor_check_penalty(0) = 0 + 3 = 3
        assert result.derived["skill_stealth"] == 3
