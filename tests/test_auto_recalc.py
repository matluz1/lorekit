"""Tests for P1: auto-recalc on write.

Verifies that derived stats in the DB are automatically recalculated
after every combat_state or terrain modifier write, without the GM
needing to call rules_calc manually.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")

COMBAT_CFG = {
    "zone_scale": 30,
    "movement_unit": "ft",
    "melee_range": 0,
    "initiative_stat": "melee_attack",
    "hud": {
        "vital_stat": {"current": "current_hp", "max": "max_hp", "label": "HP"},
    },
    "zone_tags": {
        "difficult_terrain": {"movement_multiplier": 2},
        "cover": {
            "target_stat": "bonus_defense",
            "value": 2,
            "modifier_type": "environment",
        },
        "elevated": {
            "target_stat": "bonus_ranged_attack",
            "value": 1,
            "modifier_type": "environment",
        },
    },
}


@pytest.fixture
def rules_session(make_session, tmp_path):
    """Create a session with rules_system pointing at the test_system fixture.

    Symlinks systems/test_system so try_rules_calc can resolve it.
    """
    sid = make_session()
    from _db import require_db

    db = require_db()

    # Create symlink: <project>/systems/test_system -> tests/fixtures/test_system
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    link_path = os.path.join(project_root, "systems", "test_system")
    if not os.path.exists(link_path):
        os.symlink(TEST_SYSTEM, link_path)

    db.execute(
        "INSERT INTO session_meta (session_id, key, value) VALUES (?, 'rules_system', 'test_system')",
        (sid,),
    )
    db.commit()
    db.close()

    yield sid

    # Cleanup symlink
    if os.path.islink(link_path):
        os.unlink(link_path)


def _set_attrs(db, cid, attrs):
    for key, val in attrs.items():
        db.execute(
            "INSERT INTO character_attributes (character_id, category, key, value) "
            "VALUES (?, 'stat', ?, ?) "
            "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
            (cid, key, str(val)),
        )
    db.commit()


def _get_derived(db, cid, stat):
    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'derived' AND key = ?",
        (cid, stat),
    ).fetchone()
    return int(row[0]) if row else None


def _setup_character(db, cid):
    """Set up base stats so derived formulas can compute."""
    _set_attrs(
        db,
        cid,
        {
            "str": 18,
            "dex": 14,
            "con": 12,
            "base_attack": 5,
            "hit_die_avg": 6,
        },
    )
    # Run initial rules_calc to populate derived stats
    from rules_engine import rules_calc

    rules_calc(db, cid, TEST_SYSTEM)


class TestCombatModifierAutoRecalc:
    """combat_modifier add/remove/clear auto-recalc derived stats."""

    def test_add_recalcs(self, rules_session, make_character):
        from _db import require_db

        from mcp_server import combat_modifier

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        defense_before = _get_derived(db, cid, "defense")
        assert defense_before is not None

        # Add +2 bonus_defense via combat_modifier
        result = combat_modifier(
            character_id=cid,
            action="add",
            source="shield_spell",
            target_stat="bonus_defense",
            value=2,
        )
        assert "MODIFIER ADDED" in result
        assert "RULES_CALC" in result

        # Derived defense should be +2 in the DB without manual rules_calc
        db2 = require_db()
        defense_after = _get_derived(db2, cid, "defense")
        assert defense_after == defense_before + 2
        db.close()
        db2.close()

    def test_remove_recalcs(self, rules_session, make_character):
        from _db import require_db

        from mcp_server import combat_modifier

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        defense_before = _get_derived(db, cid, "defense")

        # Add then remove
        combat_modifier(
            character_id=cid,
            action="add",
            source="shield_spell",
            target_stat="bonus_defense",
            value=2,
        )
        result = combat_modifier(
            character_id=cid,
            action="remove",
            source="shield_spell",
        )
        assert "REMOVED" in result
        assert "RULES_CALC" in result

        db2 = require_db()
        defense_after = _get_derived(db2, cid, "defense")
        assert defense_after == defense_before
        db.close()
        db2.close()

    def test_clear_recalcs(self, rules_session, make_character):
        from _db import require_db

        from mcp_server import combat_modifier

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        defense_before = _get_derived(db, cid, "defense")

        combat_modifier(
            character_id=cid,
            action="add",
            source="buff1",
            target_stat="bonus_defense",
            value=3,
            duration_type="encounter",
        )

        result = combat_modifier(character_id=cid, action="clear")
        assert "CLEARED" in result
        assert "RULES_CALC" in result

        db2 = require_db()
        defense_after = _get_derived(db2, cid, "defense")
        assert defense_after == defense_before
        db.close()
        db2.close()


class TestEncounterMoveAutoRecalc:
    """move_character auto-recalcs after terrain modifier changes."""

    def test_move_to_cover_zone(self, rules_session, make_character):
        from _db import require_db
        from encounter import move_character, start_encounter

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        defense_before = _get_derived(db, cid, "defense")

        zones = [{"name": "Open"}, {"name": "Behind Wall", "tags": ["cover"]}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Open"}]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        result = move_character(db, 1, cid, "Behind Wall", combat_cfg=COMBAT_CFG)
        assert "MOVED" in result
        assert "RULES_CALC" in result

        defense_after = _get_derived(db, cid, "defense")
        assert defense_after == defense_before + 2  # cover = +2 bonus_defense
        db.close()

    def test_move_out_of_cover_zone(self, rules_session, make_character):
        from _db import require_db
        from encounter import move_character, start_encounter

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        zones = [{"name": "Open"}, {"name": "Behind Wall", "tags": ["cover"]}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Behind Wall"}]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        defense_in_cover = _get_derived(db, cid, "defense")

        result = move_character(db, 1, cid, "Open", combat_cfg=COMBAT_CFG)
        assert "MOVED" in result

        defense_in_open = _get_derived(db, cid, "defense")
        assert defense_in_open == defense_in_cover - 2
        db.close()


class TestEncounterZoneUpdateAutoRecalc:
    """update_zone_tags auto-recalcs for all characters in the zone."""

    def test_add_cover_to_zone(self, rules_session, make_character):
        from _db import require_db
        from encounter import start_encounter, update_zone_tags

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        defense_before = _get_derived(db, cid, "defense")

        zones = [{"name": "Hall"}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Hall"}]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        result = update_zone_tags(db, 1, "Hall", ["cover"], combat_cfg=COMBAT_CFG)
        assert "ZONE UPDATED" in result
        assert "RULES_CALC" in result

        defense_after = _get_derived(db, cid, "defense")
        assert defense_after == defense_before + 2
        db.close()


class TestEncounterStartAutoRecalc:
    """start_encounter auto-recalcs when placing in terrain zones."""

    def test_placement_in_cover_zone(self, rules_session, make_character):
        from _db import require_db
        from encounter import start_encounter

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        defense_before = _get_derived(db, cid, "defense")

        zones = [{"name": "Bunker", "tags": ["cover"]}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Bunker"}]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        defense_after = _get_derived(db, cid, "defense")
        assert defense_after == defense_before + 2
        db.close()


class TestEncounterEndAutoRecalc:
    """end_encounter auto-recalcs after clearing modifiers."""

    def test_end_clears_and_recalcs(self, rules_session, make_character):
        from _db import require_db
        from encounter import end_encounter, start_encounter

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        defense_before = _get_derived(db, cid, "defense")

        zones = [{"name": "Bunker", "tags": ["cover"]}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Bunker"}]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        # Verify defense is boosted during encounter
        defense_in_cover = _get_derived(db, cid, "defense")
        assert defense_in_cover == defense_before + 2

        result = end_encounter(db, rules_session)
        assert "COMBAT ENDED" in result

        defense_after = _get_derived(db, cid, "defense")
        assert defense_after == defense_before
        db.close()


class TestApplyOnHitAutoRecalc:
    """_apply_on_hit with conditions recalcs defender stats after resolution."""

    def test_grapple_applies_modifier_and_recalcs(self, rules_session, make_character):
        """Grapple applies -2 bonus_defense to defender, derived defense updates."""
        from _db import require_db
        from combat_engine import resolve_action
        from encounter import start_encounter

        db = require_db()
        attacker = make_character(rules_session, name="Fighter")
        defender = make_character(rules_session, name="Goblin")
        _setup_character(db, attacker)
        _setup_character(db, defender)
        from rules_engine import rules_calc

        rules_calc(db, attacker, TEST_SYSTEM)
        rules_calc(db, defender, TEST_SYSTEM)

        defense_before = _get_derived(db, defender, "defense")

        # Need an encounter for contested actions
        zones = [{"name": "Arena"}]
        initiative = [
            {"character_id": attacker, "roll": 20},
            {"character_id": defender, "roll": 10},
        ]
        placements = [
            {"character_id": attacker, "zone": "Arena"},
            {"character_id": defender, "zone": "Arena"},
        ]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        # Grapple is contested — result depends on dice, but if it hits,
        # it applies -2 bonus_defense to defender via on_hit.apply_modifiers.
        # Run it multiple times to get a hit (contested rolls are random).
        hit = False
        for _ in range(20):
            result = resolve_action(db, attacker, defender, "grapple", TEST_SYSTEM)
            if "HIT" in result:
                hit = True
                break
            # Clean up modifier if miss so we can retry
            db.execute("DELETE FROM combat_state WHERE character_id = ? AND source = 'grapple'", (defender,))
            db.commit()

        if hit:
            # Verify defender's defense dropped by 2 in the DB
            defense_after = _get_derived(db, defender, "defense")
            assert defense_after == defense_before - 2
        # If no hit in 20 tries, skip (extremely unlikely but not impossible)
        db.close()


class TestCharacterViewAfterModifier:
    """character_view shows correct (fresh) stats after combat_modifier."""

    def test_view_reflects_modifier(self, rules_session, make_character):
        from _db import require_db

        from mcp_server import character_view, combat_modifier

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)
        from rules_engine import rules_calc

        rules_calc(db, cid, TEST_SYSTEM)

        defense_before = _get_derived(db, cid, "defense")
        db.close()

        # Add modifier
        combat_modifier(
            character_id=cid,
            action="add",
            source="shield_spell",
            target_stat="bonus_defense",
            value=3,
        )

        # character_view should show the updated derived defense
        view_result = character_view(character_id=cid)
        # defense = 10 + dex_mod(2) + bonus_defense(3) = 15
        expected_defense = defense_before + 3
        assert str(expected_defense) in view_result


class TestFullCombatIntegration:
    """Full GM combat flow through MCP tool functions with auto-recalc at every step."""

    def test_full_combat_flow(self, rules_session, make_character):
        from _db import require_db

        from mcp_server import (
            combat_modifier,
            encounter_advance_turn,
            encounter_end,
            encounter_start,
            rules_resolve,
        )

        db = require_db()
        pc = make_character(rules_session, name="Fighter", char_type="pc")
        npc = make_character(rules_session, name="Goblin", char_type="npc")
        _setup_character(db, pc)
        _setup_character(db, npc)
        _set_attrs(db, pc, {"weapon_damage_die": "1d6", "current_hp": 20})
        _set_attrs(db, npc, {"weapon_damage_die": "1d4", "current_hp": 15})
        from rules_engine import rules_calc

        rules_calc(db, pc, TEST_SYSTEM)
        rules_calc(db, npc, TEST_SYSTEM)

        pc_defense_base = _get_derived(db, pc, "defense")
        npc_defense_base = _get_derived(db, npc, "defense")
        db.close()

        # 1. encounter_start — auto-recalc on placement
        zones = '[{"name":"North","tags":["cover"]},{"name":"South"}]'
        initiative = json.dumps(
            [
                {"character_id": pc, "roll": 20},
                {"character_id": npc, "roll": 10},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": pc, "zone": "North"},
                {"character_id": npc, "zone": "North"},
            ]
        )
        result = encounter_start(
            session_id=rules_session,
            zones=zones,
            initiative=initiative,
            placements=placements,
        )
        assert "ENCOUNTER STARTED" in result

        # PC in cover zone should have +2 defense
        db2 = require_db()
        assert _get_derived(db2, pc, "defense") == pc_defense_base + 2
        db2.close()

        # 2. combat_modifier — auto-recalc
        result = combat_modifier(
            character_id=npc,
            action="add",
            source="rage",
            target_stat="bonus_melee_attack",
            value=2,
            duration_type="rounds",
            duration=3,
        )
        assert "MODIFIER ADDED" in result
        assert "RULES_CALC" in result

        db3 = require_db()
        npc_melee_before = _get_derived(db3, npc, "melee_attack")
        db3.close()

        # 3. rules_resolve — attack
        result = rules_resolve(
            attacker_id=pc,
            defender_id=npc,
            action="melee_attack",
        )
        assert "ACTION" in result

        # 4. encounter_advance_turn — auto end_turn on PC
        result = encounter_advance_turn(session_id=rules_session)
        assert "END TURN" in result
        assert "Goblin" in result  # Now Goblin's turn

        # 5. encounter_advance_turn again — auto end_turn on NPC (rage ticks)
        result = encounter_advance_turn(session_id=rules_session)
        assert "TICKED: rage" in result
        assert "Fighter" in result  # Back to Fighter's turn

        # 6. encounter_end — auto-recalc + combat summary
        result = encounter_end(session_id=rules_session)
        assert "COMBAT ENDED" in result
        assert "Journal saved" in result

        # After encounter end, cover modifier should be gone
        db4 = require_db()
        pc_defense_after = _get_derived(db4, pc, "defense")
        assert pc_defense_after == pc_defense_base  # No more cover
        db4.close()


class TestFullCombatIntegrationMM3e:
    """Full GM combat flow with M&M3e degree resolution + auto-recalc."""

    @pytest.fixture
    def mm3e_session(self, make_session, tmp_path):
        """Create a session with rules_system=mm3e."""
        sid = make_session()
        from _db import require_db

        db = require_db()
        db.execute(
            "INSERT INTO session_meta (session_id, key, value) VALUES (?, 'rules_system', 'mm3e')",
            (sid,),
        )
        db.commit()
        db.close()
        return sid

    def _setup_mm3e_char(self, db, cid, fgt=4, agl=2, str_=4, sta=4):
        """Set M&M3e base stats and compute derived."""
        mm3e_path = os.path.join(os.path.dirname(__file__), "..", "systems", "mm3e")
        for key, val in {
            "fgt": str(fgt),
            "agl": str(agl),
            "str": str(str_),
            "sta": str(sta),
            "dex": "0",
            "int": "0",
            "awe": "2",
            "pre": "0",
            "power_level": "10",
        }.items():
            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'stat', ?, ?) "
                "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
                (cid, key, val),
            )
        db.commit()
        from rules_engine import rules_calc

        rules_calc(db, cid, mm3e_path)

    def test_mm3e_degree_combat_flow(self, mm3e_session, make_character):
        from _db import require_db

        from mcp_server import (
            combat_modifier,
            encounter_advance_turn,
            encounter_end,
            encounter_start,
            rules_resolve,
        )

        db = require_db()
        hero = make_character(mm3e_session, name="Paragon", char_type="pc")
        villain = make_character(mm3e_session, name="Brute", char_type="npc")
        self._setup_mm3e_char(db, hero, fgt=8, agl=4, str_=8, sta=6)
        self._setup_mm3e_char(db, villain, fgt=6, agl=2, str_=6, sta=4)

        hero_dodge_base = _get_derived(db, hero, "dodge")
        villain_parry_base = _get_derived(db, villain, "parry")
        db.close()

        # 1. encounter_start with cover zone
        zones = '[{"name":"Rooftop","tags":["cover"]},{"name":"Street"}]'
        initiative = json.dumps(
            [
                {"character_id": hero, "roll": 20},
                {"character_id": villain, "roll": 10},
            ]
        )
        placements = json.dumps(
            [
                {"character_id": hero, "zone": "Rooftop"},
                {"character_id": villain, "zone": "Rooftop"},
            ]
        )
        result = encounter_start(
            session_id=mm3e_session,
            zones=zones,
            initiative=initiative,
            placements=placements,
        )
        assert "ENCOUNTER STARTED" in result

        # Hero in cover should have +2 dodge
        db2 = require_db()
        assert _get_derived(db2, hero, "dodge") == hero_dodge_base + 2
        db2.close()

        # 2. combat_modifier — buff villain
        result = combat_modifier(
            character_id=villain,
            action="add",
            source="power_boost",
            target_stat="bonus_close_attack",
            value=2,
            duration_type="rounds",
            duration=3,
        )
        assert "MODIFIER ADDED" in result
        assert "RULES_CALC" in result

        # 3. rules_resolve — degree resolution (close_attack)
        result = rules_resolve(
            attacker_id=hero,
            defender_id=villain,
            action="close_attack",
        )
        assert "ACTION" in result
        # Degree resolution shows resistance check
        assert "RESIST" in result or "MISS" in result

        # 4. advance turn — auto end_turn on hero
        result = encounter_advance_turn(session_id=mm3e_session)
        assert "END TURN" in result
        assert "Brute" in result

        # 5. advance again — auto end_turn on villain (power_boost ticks)
        result = encounter_advance_turn(session_id=mm3e_session)
        assert "TICKED: power_boost" in result
        assert "Paragon" in result

        # 6. encounter_end
        result = encounter_end(session_id=mm3e_session)
        assert "COMBAT ENDED" in result
        assert "Paragon (pc)" in result
        assert "Brute (npc)" in result

        # Cover modifier gone after encounter
        db3 = require_db()
        assert _get_derived(db3, hero, "dodge") == hero_dodge_base
        db3.close()


class TestAdvanceTurnAutoEndTurn:
    """advance_turn automatically calls end_turn on the previous character."""

    def test_modifiers_tick_on_advance(self, rules_session, make_character):
        from _db import require_db
        from encounter import advance_turn, start_encounter

        from mcp_server import combat_modifier

        db = require_db()
        c1 = make_character(rules_session, name="Fighter")
        c2 = make_character(rules_session, name="Goblin")
        _setup_character(db, c1)
        _setup_character(db, c2)

        zones = [{"name": "Arena"}]
        initiative = [
            {"character_id": c1, "roll": 20},
            {"character_id": c2, "roll": 10},
        ]
        placements = [
            {"character_id": c1, "zone": "Arena"},
            {"character_id": c2, "zone": "Arena"},
        ]
        start_encounter(db, rules_session, zones, initiative, placements=placements)

        # Add a 2-round modifier to Fighter (whose turn is current)
        combat_modifier(
            character_id=c1,
            action="add",
            source="rage",
            target_stat="bonus_melee_attack",
            value=2,
            duration_type="rounds",
            duration=2,
        )

        # Advance: should end Fighter's turn (tick rage to 1 round), start Goblin's
        result = advance_turn(db, rules_session)
        assert "END TURN" in result
        assert "TICKED: rage (1 rounds remaining)" in result
        assert "Goblin" in result

        # Advance again: end Goblin's turn (no modifiers), start Fighter's (round 2)
        result = advance_turn(db, rules_session)
        assert "Fighter" in result

        # Advance again: end Fighter's turn → rage expires (0 remaining)
        result = advance_turn(db, rules_session)
        assert "EXPIRED: rage" in result
        db.close()

    def test_advance_without_system_still_works(self, make_session, make_character):
        """Sessions without rules_system skip end_turn gracefully."""
        from _db import require_db
        from encounter import advance_turn, start_encounter

        db = require_db()
        sid = make_session()
        c1 = make_character(sid, name="Fighter")
        c2 = make_character(sid, name="Goblin")

        zones = [{"name": "Arena"}]
        initiative = [
            {"character_id": c1, "roll": 20},
            {"character_id": c2, "roll": 10},
        ]
        placements = [
            {"character_id": c1, "zone": "Arena"},
            {"character_id": c2, "zone": "Arena"},
        ]
        start_encounter(db, sid, zones, initiative, placements=placements)

        result = advance_turn(db, sid)
        assert "TURN" in result
        assert "Goblin" in result
        # No END TURN section since no rules_system
        assert "END TURN" not in result
        db.close()


class TestInitiativeAutoRoll:
    """encounter_start with initiative='auto' rolls d20 + derived stat."""

    def test_auto_roll_produces_valid_order(self, rules_session, make_character):
        from _db import require_db
        from encounter import start_encounter

        db = require_db()
        c1 = make_character(rules_session, name="Fighter")
        c2 = make_character(rules_session, name="Rogue")
        _setup_character(db, c1)
        _setup_character(db, c2)

        zones = [{"name": "Arena"}]
        placements = [
            {"character_id": c1, "zone": "Arena"},
            {"character_id": c2, "zone": "Arena"},
        ]

        result = start_encounter(
            db,
            rules_session,
            zones,
            "auto",
            placements=placements,
            combat_cfg=COMBAT_CFG,
        )
        assert "ENCOUNTER STARTED" in result
        assert "d20(" in result  # auto-roll detail shown
        assert "Fighter" in result
        assert "Rogue" in result

        # Verify initiative order was stored
        enc = db.execute(
            "SELECT initiative_order FROM encounter_state WHERE session_id = ?",
            (rules_session,),
        ).fetchone()
        import json

        order = json.loads(enc[0])
        assert len(order) == 2
        assert set(order) == {c1, c2}
        db.close()

    def test_auto_roll_requires_placements(self, rules_session, make_character):
        from _db import LoreKitError, require_db
        from encounter import start_encounter

        db = require_db()
        zones = [{"name": "Arena"}]

        with pytest.raises(LoreKitError, match="requires placements"):
            start_encounter(db, rules_session, zones, "auto", combat_cfg=COMBAT_CFG)
        db.close()

    def test_manual_override_still_works(self, rules_session, make_character):
        from _db import require_db
        from encounter import start_encounter

        db = require_db()
        c1 = make_character(rules_session, name="Fighter")
        c2 = make_character(rules_session, name="Rogue")

        zones = [{"name": "Arena"}]
        initiative = [
            {"character_id": c1, "roll": 5},
            {"character_id": c2, "roll": 20},
        ]
        placements = [
            {"character_id": c1, "zone": "Arena"},
            {"character_id": c2, "zone": "Arena"},
        ]

        result = start_encounter(
            db,
            rules_session,
            zones,
            initiative,
            placements=placements,
            combat_cfg=COMBAT_CFG,
        )
        assert "Rogue (20)" in result
        assert "Fighter (5)" in result
        # Rogue should be first (higher roll)
        assert result.index("Rogue") < result.index("Fighter")
        db.close()


class TestCombatHUD:
    """encounter_status shows zone-grouped HUD with vitals and modifiers."""

    def test_hud_shows_hp(self, rules_session, make_character):
        from _db import require_db
        from encounter import get_status, start_encounter

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)
        # max_hp = hit_die_avg(6) * level(1) + con_mod(1) * level(1) = 7
        # Set current_hp to 5 (wounded)
        _set_attrs(db, cid, {"current_hp": 5})
        from rules_engine import rules_calc

        rules_calc(db, cid, TEST_SYSTEM)

        zones = [{"name": "Hall"}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Hall"}]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        result = get_status(db, rules_session, combat_cfg=COMBAT_CFG)
        assert "HP 5/7" in result
        assert "Fighter" in result
        assert "Hall" in result
        db.close()

    def test_hud_shows_modifiers(self, rules_session, make_character):
        from _db import require_db
        from encounter import get_status, start_encounter

        from mcp_server import combat_modifier

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        zones = [{"name": "Hall"}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Hall"}]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        combat_modifier(
            character_id=cid,
            action="add",
            source="Blessed",
            target_stat="bonus_melee_attack",
            value=1,
            duration_type="rounds",
            duration=3,
        )

        result = get_status(db, rules_session, combat_cfg=COMBAT_CFG)
        assert "Blessed +1 3r" in result
        db.close()

    def test_hud_without_config(self, make_session, make_character):
        """Graceful fallback when no hud config exists."""
        from _db import require_db
        from encounter import get_status, start_encounter

        db = require_db()
        sid = make_session()
        cid = make_character(sid, name="Fighter")

        zones = [{"name": "Hall"}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Hall"}]
        # No combat_cfg → no hud config
        start_encounter(db, sid, zones, initiative, placements=placements)

        result = get_status(db, sid)
        assert "Round 1" in result
        assert "Fighter" in result
        # No HP shown (no hud config)
        assert "HP" not in result
        db.close()

    def test_hud_current_turn_marker(self, rules_session, make_character):
        from _db import require_db
        from encounter import get_status, start_encounter

        db = require_db()
        c1 = make_character(rules_session, name="Fighter")
        c2 = make_character(rules_session, name="Goblin")

        zones = [{"name": "Arena"}]
        initiative = [
            {"character_id": c1, "roll": 20},
            {"character_id": c2, "roll": 10},
        ]
        placements = [
            {"character_id": c1, "zone": "Arena"},
            {"character_id": c2, "zone": "Arena"},
        ]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        result = get_status(db, rules_session, combat_cfg=COMBAT_CFG)
        # Fighter has current turn marker
        assert "Fighter" in result
        assert "►" in result
        db.close()


class TestNpcCombatTurn:
    """NPC combat turn: context builder, intent parser, orchestrator."""

    def test_parse_intent_json_block(self):
        from npc_combat import parse_combat_intent

        response = """The orc snarls!
```json
{"action": "melee_attack", "target": "Fighter", "move_to": "Center", "narration": "Charges forward!"}
```"""
        intent = parse_combat_intent(response)
        assert intent["action"] == "melee_attack"
        assert intent["target"] == "Fighter"
        assert intent["move_to"] == "Center"
        assert intent["narration"] == "Charges forward!"

    def test_parse_intent_null_fields(self):
        from npc_combat import parse_combat_intent

        response = """```json
{"action": null, "target": null, "move_to": null, "narration": "The priest prays silently."}
```"""
        intent = parse_combat_intent(response)
        assert intent["action"] is None
        assert intent["target"] is None
        assert intent["move_to"] is None
        assert intent["narration"] == "The priest prays silently."

    def test_parse_intent_no_json(self):
        from npc_combat import parse_combat_intent

        response = "The goblin shrieks and runs away!"
        intent = parse_combat_intent(response)
        assert intent["action"] is None
        assert intent["target"] is None
        assert intent["move_to"] is None
        assert intent["narration"] == "The goblin shrieks and runs away!"

    def test_build_combat_context(self, rules_session, make_character):
        from _db import require_db
        from encounter import start_encounter
        from npc_combat import build_combat_context

        db = require_db()
        pc = make_character(rules_session, name="Fighter", char_type="pc")
        npc = make_character(rules_session, name="Goblin", char_type="npc")
        _setup_character(db, pc)
        _setup_character(db, npc)

        zones = [{"name": "North"}, {"name": "South"}]
        initiative = [
            {"character_id": npc, "roll": 20},
            {"character_id": pc, "roll": 10},
        ]
        placements = [
            {"character_id": pc, "zone": "North"},
            {"character_id": npc, "zone": "South"},
        ]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        ctx = build_combat_context(db, npc, rules_session, COMBAT_CFG)
        assert "Goblin" in ctx
        assert "Fighter" in ctx
        assert "North" in ctx
        assert "South" in ctx
        assert "Enemies:" in ctx
        assert "json" in ctx  # JSON template
        db.close()

    def test_execute_narrative_only(self, rules_session, make_character):
        """Narrative-only turn (null intent) still advances initiative."""
        from _db import require_db
        from encounter import start_encounter
        from npc_combat import execute_combat_turn

        db = require_db()
        pc = make_character(rules_session, name="Fighter", char_type="pc")
        npc = make_character(rules_session, name="Goblin", char_type="npc")
        _setup_character(db, pc)
        _setup_character(db, npc)

        zones = [{"name": "Arena"}]
        initiative = [
            {"character_id": npc, "roll": 20},
            {"character_id": pc, "roll": 10},
        ]
        placements = [
            {"character_id": pc, "zone": "Arena"},
            {"character_id": npc, "zone": "Arena"},
        ]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        intent = {"action": None, "target": None, "move_to": None, "narration": "Hesitates."}
        lines = execute_combat_turn(db, rules_session, npc, intent, COMBAT_CFG, TEST_SYSTEM)
        result = "\n".join(lines)

        # Should advance to Fighter's turn
        assert "Fighter" in result
        assert "TURN" in result
        db.close()

    def test_execute_move_and_attack(self, rules_session, make_character):
        """NPC moves and attacks."""
        from _db import require_db
        from encounter import start_encounter
        from npc_combat import execute_combat_turn

        db = require_db()
        pc = make_character(rules_session, name="Fighter", char_type="pc")
        npc = make_character(rules_session, name="Goblin", char_type="npc")
        _setup_character(db, pc)
        _setup_character(db, npc)
        # Give both characters weapon damage die for melee_attack
        _set_attrs(db, pc, {"weapon_damage_die": "1d6"})
        _set_attrs(db, npc, {"weapon_damage_die": "1d4"})
        from rules_engine import rules_calc

        rules_calc(db, pc, TEST_SYSTEM)
        rules_calc(db, npc, TEST_SYSTEM)

        zones = [{"name": "North"}, {"name": "South"}]
        initiative = [
            {"character_id": npc, "roll": 20},
            {"character_id": pc, "roll": 10},
        ]
        placements = [
            {"character_id": pc, "zone": "North"},
            {"character_id": npc, "zone": "South"},
        ]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        intent = {"action": "melee_attack", "target": "Fighter", "move_to": "North", "narration": None}
        lines = execute_combat_turn(db, rules_session, npc, intent, COMBAT_CFG, TEST_SYSTEM)
        result = "\n".join(lines)

        assert "MOVED" in result  # movement happened
        # Attack should resolve (hit or miss)
        assert "ATTACK" in result or "ACTION FAILED" in result
        # Should advance to Fighter's turn
        assert "Fighter" in result
        db.close()


class TestEncounterTemplates:
    """encounter_start with template loads zones/adjacency from system pack."""

    def test_template_creates_zones(self, rules_session, make_character):
        from _db import require_db
        from encounter import start_encounter

        db = require_db()
        c1 = make_character(rules_session, name="Fighter")

        placements = [{"character_id": c1, "zone": "North"}]
        initiative = [{"character_id": c1, "roll": 15}]

        result = start_encounter(
            db,
            rules_session,
            initiative=initiative,
            placements=placements,
            combat_cfg=COMBAT_CFG,
            template="arena",
            pack_dir=TEST_SYSTEM,
        )
        assert "ENCOUNTER STARTED" in result
        assert "North" in result
        assert "Center" in result
        assert "South" in result

        # Verify 3 zones were created
        enc_id = db.execute(
            "SELECT id FROM encounter_state WHERE session_id = ?",
            (rules_session,),
        ).fetchone()[0]
        zone_count = db.execute(
            "SELECT COUNT(*) FROM encounter_zones WHERE encounter_id = ?",
            (enc_id,),
        ).fetchone()[0]
        assert zone_count == 3
        db.close()

    def test_template_with_custom_zones_override(self, rules_session, make_character):
        from _db import require_db
        from encounter import start_encounter

        db = require_db()
        c1 = make_character(rules_session, name="Fighter")

        # Custom zones override template zones
        custom_zones = [{"name": "Custom1"}, {"name": "Custom2"}]
        placements = [{"character_id": c1, "zone": "Custom1"}]
        initiative = [{"character_id": c1, "roll": 15}]

        result = start_encounter(
            db,
            rules_session,
            zones=custom_zones,
            initiative=initiative,
            placements=placements,
            combat_cfg=COMBAT_CFG,
            template="arena",
            pack_dir=TEST_SYSTEM,
        )
        assert "Custom1" in result
        assert "Custom2" in result
        # Template zones should NOT appear
        assert "North" not in result
        db.close()

    def test_unknown_template_error(self, rules_session, make_character):
        from _db import require_db
        from encounter import start_encounter

        db = require_db()
        c1 = make_character(rules_session, name="Fighter")

        try:
            start_encounter(
                db,
                rules_session,
                initiative=[{"character_id": c1, "roll": 15}],
                combat_cfg=COMBAT_CFG,
                template="nonexistent",
                pack_dir=TEST_SYSTEM,
            )
            assert False, "Should have raised"
        except Exception as e:
            assert "Unknown template" in str(e)
        db.close()


class TestRest:
    """rest tool applies system pack rest rules to all PCs."""

    def test_short_rest_partial_heal(self, rules_session, make_character):
        from _db import require_db
        from rest import rest

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)
        # max_hp = 7 (hit_die_avg=6*1 + con_mod=1*1)
        # short rest restores floor(max_hp / 2) = floor(3.5) = 3
        _set_attrs(db, cid, {"current_hp": 1})
        from rules_engine import rules_calc

        rules_calc(db, cid, TEST_SYSTEM)

        result = rest(db, rules_session, "short", TEST_SYSTEM)
        assert "REST (SHORT)" in result
        assert "current_hp: 1 → 3" in result

        hp = _get_derived(db, cid, "current_hp")
        # current_hp is a stat, not derived — check stat category
        row = db.execute(
            "SELECT value FROM character_attributes "
            "WHERE character_id = ? AND category = 'stat' AND key = 'current_hp'",
            (cid,),
        ).fetchone()
        assert row is not None
        assert int(row[0]) == 3
        db.close()

    def test_long_rest_full_heal(self, rules_session, make_character):
        from _db import require_db
        from rest import rest

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)
        _set_attrs(db, cid, {"current_hp": 1})
        from rules_engine import rules_calc

        rules_calc(db, cid, TEST_SYSTEM)

        result = rest(db, rules_session, "long", TEST_SYSTEM)
        assert "REST (LONG)" in result
        assert "current_hp: 1 → 7" in result
        db.close()

    def test_clears_modifiers(self, rules_session, make_character):
        from _db import require_db
        from rest import rest

        from mcp_server import combat_modifier

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        combat_modifier(
            character_id=cid,
            action="add",
            source="bless",
            target_stat="bonus_melee_attack",
            value=1,
            duration_type="encounter",
        )

        result = rest(db, rules_session, "short", TEST_SYSTEM)
        assert "Modifiers cleared: 1" in result

        # Verify modifier is gone
        count = db.execute(
            "SELECT COUNT(*) FROM combat_state WHERE character_id = ?",
            (cid,),
        ).fetchone()[0]
        assert count == 0
        db.close()

    def test_only_affects_pcs(self, rules_session, make_character):
        from _db import require_db
        from rest import rest

        db = require_db()
        pc = make_character(rules_session, name="Fighter", char_type="pc")
        npc = make_character(rules_session, name="Goblin", char_type="npc")
        _setup_character(db, pc)
        _setup_character(db, npc)
        _set_attrs(db, pc, {"current_hp": 1})
        _set_attrs(db, npc, {"current_hp": 1})
        from rules_engine import rules_calc

        rules_calc(db, pc, TEST_SYSTEM)
        rules_calc(db, npc, TEST_SYSTEM)

        result = rest(db, rules_session, "long", TEST_SYSTEM)
        assert "Fighter" in result
        assert "Goblin" not in result

        # NPC HP unchanged
        row = db.execute(
            "SELECT value FROM character_attributes "
            "WHERE character_id = ? AND category = 'stat' AND key = 'current_hp'",
            (npc,),
        ).fetchone()
        assert int(row[0]) == 1
        db.close()

    def test_invalid_rest_type(self, rules_session, make_character):
        from _db import require_db
        from rest import rest

        db = require_db()
        make_character(rules_session, name="Fighter")

        try:
            rest(db, rules_session, "mega", TEST_SYSTEM)
            assert False, "Should have raised"
        except Exception as e:
            assert "Unknown rest type" in str(e)
        db.close()


class TestCombatSummary:
    """encounter_end generates combat summary with participants and vitals."""

    def test_summary_with_defeated(self, rules_session, make_character):
        from _db import require_db
        from encounter import end_encounter, start_encounter

        db = require_db()
        c1 = make_character(rules_session, name="Fighter")
        c2 = make_character(rules_session, name="Goblin", char_type="npc")
        _setup_character(db, c1)
        _setup_character(db, c2)

        # Mark goblin as defeated
        db.execute("UPDATE characters SET status = 'defeated' WHERE id = ?", (c2,))
        db.commit()

        zones = [{"name": "Arena"}]
        initiative = [
            {"character_id": c1, "roll": 20},
            {"character_id": c2, "roll": 10},
        ]
        placements = [
            {"character_id": c1, "zone": "Arena"},
            {"character_id": c2, "zone": "Arena"},
        ]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        result = end_encounter(db, rules_session, combat_cfg=COMBAT_CFG)
        assert "COMBAT ENDED" in result
        assert "Fighter (pc)" in result
        assert "Goblin (npc)" in result
        assert "Defeated: Goblin" in result
        assert "Journal saved" in result
        db.close()

    def test_summary_with_vitals(self, rules_session, make_character):
        from _db import require_db
        from encounter import end_encounter, start_encounter

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)
        _set_attrs(db, cid, {"current_hp": 3})
        from rules_engine import rules_calc

        rules_calc(db, cid, TEST_SYSTEM)

        zones = [{"name": "Arena"}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Arena"}]
        start_encounter(db, rules_session, zones, initiative, placements=placements, combat_cfg=COMBAT_CFG)

        result = end_encounter(db, rules_session, combat_cfg=COMBAT_CFG)
        assert "HP 3/7" in result
        db.close()

    def test_summary_without_hud_config(self, make_session, make_character):
        from _db import require_db
        from encounter import end_encounter, start_encounter

        db = require_db()
        sid = make_session()
        cid = make_character(sid, name="Fighter")

        zones = [{"name": "Arena"}]
        initiative = [{"character_id": cid, "roll": 15}]
        placements = [{"character_id": cid, "zone": "Arena"}]
        start_encounter(db, sid, zones, initiative, placements=placements)

        result = end_encounter(db, sid)
        assert "COMBAT ENDED" in result
        assert "Fighter (pc)" in result
        # No HP shown (no hud config)
        assert "HP" not in result
        db.close()


class TestCharacterLookupByName:
    """Tools accept character name instead of numeric ID."""

    def test_character_view_by_name(self, make_session, make_character):
        from mcp_server import character_view

        sid = make_session()
        cid = make_character(sid, name="Valeria")

        result = character_view(character_id="Valeria")
        assert "Valeria" in result
        assert f"ID: {cid}" in result

    def test_case_insensitive(self, make_session, make_character):
        from mcp_server import character_view

        sid = make_session()
        make_character(sid, name="Valeria")

        result = character_view(character_id="valeria")
        assert "Valeria" in result

    def test_numeric_passthrough(self, make_session, make_character):
        from mcp_server import character_view

        sid = make_session()
        cid = make_character(sid, name="Valeria")

        result = character_view(character_id=cid)
        assert "Valeria" in result

    def test_numeric_string_passthrough(self, make_session, make_character):
        from mcp_server import character_view

        sid = make_session()
        cid = make_character(sid, name="Valeria")

        result = character_view(character_id=str(cid))
        assert "Valeria" in result

    def test_not_found(self, make_session, make_character):
        from mcp_server import character_view

        sid = make_session()
        make_character(sid, name="Valeria")

        result = character_view(character_id="Nobody")
        assert "ERROR" in result
        assert "not found" in result

    def test_ambiguous(self, make_session, make_character):
        from mcp_server import character_view

        sid = make_session()
        make_character(sid, name="Goblin")
        make_character(sid, name="Goblin")

        result = character_view(character_id="Goblin")
        assert "ERROR" in result
        assert "Ambiguous" in result

    def test_combat_modifier_by_name(self, make_session, make_character):
        from mcp_server import combat_modifier

        sid = make_session()
        make_character(sid, name="Fighter")

        result = combat_modifier(
            character_id="Fighter",
            action="add",
            source="bless",
            target_stat="bonus_attack",
            value=1,
        )
        assert "MODIFIER ADDED" in result

    def test_npc_interact_by_name(self, make_session, make_character):
        """Verify name resolution works (mock subprocess to avoid LLM call)."""
        from unittest.mock import patch

        from mcp_server import npc_interact

        sid = make_session()
        make_character(sid, name="Bartender", char_type="npc")

        # Mock subprocess to return a valid stream-json response
        mock_stdout = '{"type":"result","subtype":"success","result":"Hello traveler!"}\n'
        mock_proc = type("Proc", (), {"returncode": 0, "stdout": mock_stdout, "stderr": ""})()

        with patch("subprocess.run", return_value=mock_proc):
            result = npc_interact(session_id=sid, npc_id="Bartender", message="Hello")
        assert "not found" not in result or "Bartender" not in result


class TestNoRecalcWithoutSystem:
    """Sessions without rules_system skip recalc silently."""

    def test_combat_modifier_no_system(self, make_session, make_character):
        from mcp_server import combat_modifier

        sid = make_session()
        cid = make_character(sid)

        result = combat_modifier(
            character_id=cid,
            action="add",
            source="buff",
            target_stat="bonus_defense",
            value=2,
        )
        assert "MODIFIER ADDED" in result
        assert "RULES_CALC" not in result
