"""Tests for system_info formatting."""

import cruncher_mm3e
import cruncher_pf2e

from lorekit.rules import system_info

MM3E = cruncher_mm3e.pack_path()
PF2E = cruncher_pf2e.pack_path()


def test_all_section_mm3e():
    result = system_info(MM3E, "all")
    assert "d20 Hero SRD (3e)" in result
    assert "ACTIONS:" in result
    assert "close_attack" in result
    assert "DEFAULTS" in result
    assert "DERIVED" in result
    assert "RESOLUTION:" in result
    assert "COMBAT" in result


def test_all_section_pf2e():
    result = system_info(PF2E, "all")
    assert "Pathfinder 2e" in result
    assert "melee_attack" in result
    assert "grapple" in result
    assert "shove" in result


def test_actions_section():
    result = system_info(MM3E, "actions")
    assert "close_attack:" in result
    assert "ranged_attack:" in result
    assert "grab:" in result
    assert "DEFAULTS" not in result
    assert "DERIVED" not in result


def test_defaults_section():
    result = system_info(MM3E, "defaults")
    assert "bonus_*:" in result
    assert "bonus_dodge" in result
    assert "ranks_*:" in result
    assert "ACTIONS:" not in result


def test_derived_section_shows_formulas():
    result = system_info(MM3E, "derived")
    assert "skill_*:" in result
    assert "dodge" in result
    assert "FORMULAS:" in result
    assert "dodge = " in result


def test_derived_all_no_formulas():
    """When section=all, derived shows groups but not individual formulas."""
    result = system_info(MM3E, "all")
    assert "DERIVED (computed stats):" in result
    assert "FORMULAS:" not in result


def test_build_section():
    result = system_info(MM3E, "build")
    assert "BUILD" in result
    assert "budget:" in result
    assert "ability:" in result
    assert "defense:" in result


def test_resolution_section():
    result = system_info(MM3E, "resolution")
    assert "type=degree" in result
    assert "degree 1:" in result
    assert "degree 4:" in result


def test_combat_section():
    result = system_info(PF2E, "combat")
    assert "zone_scale=30" in result
    assert "difficult_terrain" in result
    assert "cover" in result


def test_constraints_section():
    result = system_info(MM3E, "constraints")
    assert "CONSTRAINTS:" in result
    assert "pl_dodge_toughness" in result


def test_invalid_section():
    result = system_info(MM3E, "bogus")
    assert "ERROR:" in result
    assert "Unknown section" in result


def test_pf2e_defaults_grouped():
    result = system_info(PF2E, "defaults")
    assert "prof_*:" in result
    assert "bonus_*:" in result


def test_pf2e_actions():
    result = system_info(PF2E, "actions")
    assert "melee_attack:" in result
    assert "ranged_attack:" in result
    assert "grapple:" in result
    assert "trip:" in result
    assert "disarm:" in result
