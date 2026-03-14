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
    _set_attrs(db, cid, {
        "str": 18, "dex": 14, "con": 12,
        "base_attack": 5, "hit_die_avg": 6,
    })
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
            character_id=cid, action="add",
            source="shield_spell", target_stat="bonus_defense", value=2,
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
            character_id=cid, action="add",
            source="shield_spell", target_stat="bonus_defense", value=2,
        )
        result = combat_modifier(
            character_id=cid, action="remove", source="shield_spell",
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
            character_id=cid, action="add",
            source="buff1", target_stat="bonus_defense", value=3,
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
            character_id=c1, action="add",
            source="rage", target_stat="bonus_melee_attack", value=2,
            duration_type="rounds", duration=2,
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
            db, rules_session, zones, "auto",
            placements=placements, combat_cfg=COMBAT_CFG,
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
            db, rules_session, zones, initiative,
            placements=placements, combat_cfg=COMBAT_CFG,
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
            character_id=cid, action="add",
            source="Blessed", target_stat="bonus_melee_attack", value=1,
            duration_type="rounds", duration=3,
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
        from mcp_server import combat_modifier
        from rest import rest

        db = require_db()
        cid = make_character(rules_session, name="Fighter")
        _setup_character(db, cid)

        combat_modifier(
            character_id=cid, action="add",
            source="bless", target_stat="bonus_melee_attack", value=1,
            duration_type="encounter",
        )

        result = rest(db, rules_session, "short", TEST_SYSTEM)
        assert "Modifiers cleared: 1" in result

        # Verify modifier is gone
        count = db.execute(
            "SELECT COUNT(*) FROM combat_state WHERE character_id = ?", (cid,),
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
            character_id="Fighter", action="add",
            source="bless", target_stat="bonus_attack", value=1,
        )
        assert "MODIFIER ADDED" in result

    def test_npc_interact_by_name(self, make_session, make_character):
        """Verify resolve happens (NPC spawn may fail but ID resolves)."""
        from mcp_server import npc_interact

        sid = make_session()
        make_character(sid, name="Bartender", char_type="npc")

        # The NPC subprocess will likely fail in test env, but we verify
        # the name resolves (no "not found" error about the name)
        result = npc_interact(session_id=sid, npc_id="Bartender", message="Hello")
        assert "not found" not in result or "Bartender" not in result


class TestNoRecalcWithoutSystem:
    """Sessions without rules_system skip recalc silently."""

    def test_combat_modifier_no_system(self, make_session, make_character):
        from mcp_server import combat_modifier

        sid = make_session()
        cid = make_character(sid)

        result = combat_modifier(
            character_id=cid, action="add",
            source="buff", target_stat="bonus_defense", value=2,
        )
        assert "MODIFIER ADDED" in result
        assert "RULES_CALC" not in result
