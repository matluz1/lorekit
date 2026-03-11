"""Integration tests: combat_state + stacking + rules_calc pipeline."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


def _set_attr(db, cid, category, key, value):
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
        (cid, category, key, str(value)),
    )
    db.commit()


def _add_combat_modifier(db, cid, source, target_stat, value,
                         modifier_type="buff", bonus_type=None,
                         duration_type="encounter"):
    db.execute(
        "INSERT INTO combat_state "
        "(character_id, source, target_stat, modifier_type, value, bonus_type, duration_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cid, source, target_stat, modifier_type, value, bonus_type, duration_type),
    )
    db.commit()


class TestCombatStateLoading:
    """Test that combat_state modifiers are loaded into the formula context."""

    def test_combat_modifier_affects_derived(self, make_session, make_character):
        from _db import require_db
        from rules_engine import load_character_data, load_system_pack, recalculate

        db = require_db()
        sid = make_session()
        cid = make_character(sid, level=5)

        # Set base stats
        for key, val in {"str": "18", "dex": "14", "con": "12",
                         "base_attack": "5", "hit_die_avg": "6"}.items():
            _set_attr(db, cid, "stat", key, val)

        pack = load_system_pack(TEST_SYSTEM)
        char = load_character_data(db, cid)

        # Baseline: no combat modifiers
        result_before = recalculate(pack, char, db=db)
        defense_before = result_before.derived["defense"]

        # Add a combat modifier: +2 bonus_defense
        _add_combat_modifier(db, cid, "shield_spell", "bonus_defense", 2)

        # Recalc with combat state
        result_after = recalculate(pack, char, db=db)
        defense_after = result_after.derived["defense"]

        assert defense_after == defense_before + 2
        db.close()

    def test_negative_modifier(self, make_session, make_character):
        from _db import require_db
        from rules_engine import load_character_data, load_system_pack, recalculate

        db = require_db()
        sid = make_session()
        cid = make_character(sid, level=5)

        for key, val in {"str": "18", "dex": "14", "con": "12",
                         "base_attack": "5", "hit_die_avg": "6"}.items():
            _set_attr(db, cid, "stat", key, val)

        pack = load_system_pack(TEST_SYSTEM)
        char = load_character_data(db, cid)

        result_before = recalculate(pack, char, db=db)
        melee_before = result_before.derived["melee_attack"]

        _add_combat_modifier(db, cid, "frightened", "bonus_melee_attack", -2)

        result_after = recalculate(pack, char, db=db)
        melee_after = result_after.derived["melee_attack"]

        assert melee_after == melee_before - 2
        db.close()


class TestTypedStackingIntegration:
    """Test typed stacking with a system pack that declares it."""

    def test_same_type_doesnt_stack(self, make_session, make_character):
        """Two circumstance bonuses to the same stat — only highest applies."""
        from _db import require_db
        from rules_engine import load_character_data, load_system_pack, recalculate

        db = require_db()
        sid = make_session()
        cid = make_character(sid, level=5)

        for key, val in {"str": "18", "dex": "14", "con": "12",
                         "base_attack": "5", "hit_die_avg": "6"}.items():
            _set_attr(db, cid, "stat", key, val)

        # Use a system pack with grouped stacking (group by bonus_type)
        pack = load_system_pack(TEST_SYSTEM)
        pack.stacking = {
            "group_by": "bonus_type",
            "positive": "max",
            "negative": "sum",
        }

        char = load_character_data(db, cid)
        result_base = recalculate(pack, char, db=db)
        defense_base = result_base.derived["defense"]

        # Add two circumstance bonuses — only +3 should apply
        _add_combat_modifier(db, cid, "cover", "bonus_defense", 2,
                             bonus_type="circumstance")
        _add_combat_modifier(db, cid, "shield", "bonus_defense", 3,
                             bonus_type="circumstance")

        result = recalculate(pack, char, db=db)
        assert result.derived["defense"] == defense_base + 3  # not +5

        db.close()

    def test_different_types_stack(self, make_session, make_character):
        """Circumstance + status bonuses stack with each other."""
        from _db import require_db
        from rules_engine import load_character_data, load_system_pack, recalculate

        db = require_db()
        sid = make_session()
        cid = make_character(sid, level=5)

        for key, val in {"str": "18", "dex": "14", "con": "12",
                         "base_attack": "5", "hit_die_avg": "6"}.items():
            _set_attr(db, cid, "stat", key, val)

        pack = load_system_pack(TEST_SYSTEM)
        pack.stacking = {
            "group_by": "bonus_type",
            "positive": "max",
            "negative": "sum",
        }

        char = load_character_data(db, cid)
        result_base = recalculate(pack, char, db=db)
        defense_base = result_base.derived["defense"]

        _add_combat_modifier(db, cid, "cover", "bonus_defense", 2,
                             bonus_type="circumstance")
        _add_combat_modifier(db, cid, "bless", "bonus_defense", 1,
                             bonus_type="status")

        result = recalculate(pack, char, db=db)
        assert result.derived["defense"] == defense_base + 3  # +2 circ + +1 status

        db.close()


class TestMCPCombatModifier:
    """Test the combat_modifier MCP tool."""

    def test_add_and_list(self, make_session, make_character):
        from mcp_server import combat_modifier

        sid = make_session()
        cid = make_character(sid)

        result = combat_modifier(
            character_id=cid, action="add",
            source="bless", target_stat="bonus_attack", value=1,
            bonus_type="status",
        )
        assert "MODIFIER ADDED" in result
        assert "bless" in result

        listing = combat_modifier(character_id=cid, action="list")
        assert "bless" in listing
        assert "+1" in listing

    def test_remove(self, make_session, make_character):
        from mcp_server import combat_modifier

        sid = make_session()
        cid = make_character(sid)

        combat_modifier(character_id=cid, action="add",
                        source="bless", target_stat="bonus_attack", value=1)
        result = combat_modifier(character_id=cid, action="remove", source="bless")
        assert "REMOVED" in result

        listing = combat_modifier(character_id=cid, action="list")
        assert "No active modifiers" in listing

    def test_clear(self, make_session, make_character):
        from mcp_server import combat_modifier

        sid = make_session()
        cid = make_character(sid)

        combat_modifier(character_id=cid, action="add",
                        source="buff1", target_stat="bonus_ac", value=2,
                        duration_type="encounter")
        combat_modifier(character_id=cid, action="add",
                        source="curse", target_stat="bonus_will", value=-2,
                        duration_type="permanent")

        result = combat_modifier(character_id=cid, action="clear")
        assert "CLEARED: 1" in result  # only encounter, not permanent

        listing = combat_modifier(character_id=cid, action="list")
        assert "curse" in listing  # permanent survives


class TestBuildEngineTypedEffects:
    """Test that _apply_effects handles dict-format effects."""

    def test_dict_format_effects(self):
        from build_engine import BuildResult, _apply_effects

        source_data = {
            "toughness": {
                "name": "Toughness",
                "effects": {
                    "bonus_hp": {"value": 5, "type": "untyped"},
                },
            },
        }
        abilities = [{"name": "Toughness", "description": "", "category": "feat", "uses": "at_will"}]
        result = BuildResult()
        _apply_effects(source_data, abilities, result)
        assert result.attributes["bonus_hp"] == 5

    def test_plain_number_still_works(self):
        from build_engine import BuildResult, _apply_effects

        source_data = {
            "toughness": {
                "name": "Toughness",
                "effects": {"bonus_hp": 5},
            },
        }
        abilities = [{"name": "Toughness", "description": "", "category": "feat", "uses": "at_will"}]
        result = BuildResult()
        _apply_effects(source_data, abilities, result)
        assert result.attributes["bonus_hp"] == 5
