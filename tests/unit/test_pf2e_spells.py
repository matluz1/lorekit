"""Tests for the PF2e spell catalog.

Validates that spells.json loads correctly, every entry has required
fields, and action blocks reference valid engine stats.
"""

import json
import os

import cruncher_pf2e
import pytest

PF2E_DATA = cruncher_pf2e.pack_path()

VALID_TRADITIONS = {"arcane", "divine", "occult", "primal"}
VALID_COMPONENTS = {"somatic", "verbal", "material", "focus"}
VALID_DEFENSE_STATS = {"fortitude", "reflex", "will", "armor_class"}
VALID_USES = {"at_will", "per_day", "per_encounter"}
REQUIRED_FIELDS = {"name", "rank", "traditions", "cast", "components", "traits", "description"}


@pytest.fixture(scope="module")
def spells():
    with open(os.path.join(PF2E_DATA, "spells.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def system():
    with open(os.path.join(PF2E_DATA, "system.json")) as f:
        return json.load(f)


class TestSpellCatalogSchema:
    def test_templates_section_exists(self, system):
        assert "templates" in system
        assert system["templates"]["source"] == "spells.json"
        assert system["templates"]["ability_category"] == "spell"

    def test_spells_file_loads(self, spells):
        assert isinstance(spells, dict)
        assert len(spells) > 0

    def test_all_entries_have_required_fields(self, spells):
        for slug, entry in spells.items():
            for field in REQUIRED_FIELDS:
                assert field in entry, f"{slug} missing required field: {field}"

    def test_ranks_are_valid(self, spells):
        for slug, entry in spells.items():
            assert isinstance(entry["rank"], int), f"{slug}: rank must be int"
            assert 0 <= entry["rank"] <= 10, f"{slug}: rank {entry['rank']} out of range"

    def test_traditions_are_valid(self, spells):
        for slug, entry in spells.items():
            for t in entry["traditions"]:
                assert t in VALID_TRADITIONS, f"{slug}: invalid tradition '{t}'"

    def test_components_are_valid(self, spells):
        for slug, entry in spells.items():
            for c in entry["components"]:
                assert c in VALID_COMPONENTS, f"{slug}: invalid component '{c}'"

    def test_uses_are_valid(self, spells):
        for slug, entry in spells.items():
            if "uses" in entry:
                assert entry["uses"] in VALID_USES, f"{slug}: invalid uses '{entry['uses']}'"

    def test_cantrips_are_at_will(self, spells):
        for slug, entry in spells.items():
            if entry["rank"] == 0:
                uses = entry.get("uses", "at_will")
                assert uses == "at_will", f"{slug}: cantrip must be at_will"

    def test_focus_spells_are_per_encounter(self, spells):
        for slug, entry in spells.items():
            if entry.get("focus"):
                uses = entry.get("uses", "per_encounter")
                assert uses == "per_encounter", f"{slug}: focus spell must be per_encounter"

    def test_action_blocks_have_valid_defense_stats(self, spells):
        for slug, entry in spells.items():
            action = entry.get("action")
            if action and "defense_stat" in action:
                assert action["defense_stat"] in VALID_DEFENSE_STATS, (
                    f"{slug}: invalid defense_stat '{action['defense_stat']}'"
                )

    def test_action_blocks_have_valid_attack_stats(self, spells):
        valid_attack = {"spell_attack", "spell_dc"}
        for slug, entry in spells.items():
            action = entry.get("action")
            if action and "attack_stat" in action:
                assert action["attack_stat"] in valid_attack, f"{slug}: invalid attack_stat '{action['attack_stat']}'"


class TestSpellCatalogCoverage:
    def test_has_cantrips(self, spells):
        cantrips = [s for s, e in spells.items() if e["rank"] == 0]
        assert len(cantrips) >= 20, f"Expected 20+ cantrips, got {len(cantrips)}"

    def test_has_rank_1(self, spells):
        r1 = [s for s, e in spells.items() if e["rank"] == 1]
        assert len(r1) >= 30, f"Expected 30+ rank-1 spells, got {len(r1)}"

    def test_has_rank_2(self, spells):
        r2 = [s for s, e in spells.items() if e["rank"] == 2]
        assert len(r2) >= 25, f"Expected 25+ rank-2 spells, got {len(r2)}"

    def test_has_rank_3(self, spells):
        r3 = [s for s, e in spells.items() if e["rank"] == 3]
        assert len(r3) >= 20, f"Expected 20+ rank-3 spells, got {len(r3)}"

    def test_has_focus_spells(self, spells):
        focus = [s for s, e in spells.items() if e.get("focus")]
        assert len(focus) >= 10, f"Expected 10+ focus spells, got {len(focus)}"

    def test_all_traditions_represented_at_each_rank(self, spells):
        for rank in range(0, 4):
            rank_spells = [e for e in spells.values() if e["rank"] == rank]
            traditions_present = set()
            for s in rank_spells:
                traditions_present.update(s["traditions"])
            for t in VALID_TRADITIONS:
                assert t in traditions_present, f"Rank {rank} missing tradition: {t}"


class TestSpellSpotChecks:
    """Spot-check specific spells for data accuracy."""

    def test_fireball_basics(self, spells):
        fb = spells["fireball"]
        assert fb["name"] == "Fireball"
        assert fb["rank"] == 3
        assert set(fb["traditions"]) == {"arcane", "primal"}
        assert "fire" in fb["traits"]
        assert fb["action"]["defense_stat"] == "reflex"
        assert fb["action"]["on_hit"]["damage_roll"]["dice"] == "6d6"

    def test_heal_is_healing(self, spells):
        h = spells["heal"]
        assert h["rank"] == 1
        assert "healing" in h["traits"]
        assert h["action"]["on_hit"]["add_to"] == "current_hp"

    def test_electric_arc_cantrip(self, spells):
        ea = spells["electric_arc"]
        assert ea["rank"] == 0
        assert ea["uses"] == "at_will"
        assert ea["auto_heighten"] is True

    def test_fear_applies_frightened(self, spells):
        f = spells["fear"]
        assert f["rank"] == 1
        mods = f["action"]["on_hit"]["apply_modifiers"]
        conditions = [m.get("condition") for m in mods]
        assert "frightened" in conditions

    def test_lay_on_hands_is_focus(self, spells):
        loh = spells["lay_on_hands"]
        assert loh["focus"] is True
        assert loh["uses"] == "per_encounter"
        assert loh["class"] == "champion"

    def test_shield_cantrip_buff(self, spells):
        s = spells["shield"]
        assert s["rank"] == 0
        assert s["uses"] == "at_will"
        mods = s["action"]["on_hit"]["apply_modifiers"]
        assert any(m["target_stat"] == "bonus_ac" for m in mods)

    def test_magic_missile_auto_hit(self, spells):
        mm = spells["magic_missile"]
        assert "attack_stat" not in mm["action"]
        assert "defense_stat" not in mm["action"]
        assert mm["action"]["on_hit"]["subtract_from"] == "current_hp"

    def test_haste_buff(self, spells):
        h = spells["haste"]
        assert h["rank"] == 3
        mods = h["action"]["on_hit"]["apply_modifiers"]
        conditions = [m.get("condition") for m in mods]
        assert "quickened" in conditions
