"""Tests for NPC combat orchestration (npc_combat.py).

System-agnostic tests using fixtures/test_system. Validates the
orchestration wiring: parse_combat_intent, build_combat_context,
execute_combat_turn (move/action/move_others sequencing, error handling).
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

TEST_SYSTEM = os.path.join(os.path.dirname(__file__), "fixtures", "test_system")

COMBAT_CFG = {
    "zone_scale": 30,
    "movement_unit": "ft",
    "melee_range": 0,
    "initiative_stat": "melee_attack",
    "hud": {
        "vital_stat": {"current": "current_hp", "max": "max_hp", "label": "HP"},
    },
    "zone_tags": {
        "cover": {"target_stat": "bonus_defense", "value": 2, "modifier_type": "environment"},
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fighter(db, session_id, make_character, name, char_type="npc", **overrides):
    """Create a character for the test system with basic combat stats."""
    from character import set_attr
    from rules_engine import rules_calc

    cid = make_character(session_id, name=name, char_type=char_type)
    defaults = {"str": "18", "dex": "14", "con": "12", "base_attack": "5", "hit_die_avg": "6"}
    defaults.update(overrides)
    for key, val in defaults.items():
        set_attr(db, cid, "stat", key, str(val))
    set_attr(db, cid, "combat", "base_attack", defaults["base_attack"])
    set_attr(db, cid, "combat", "hit_die_avg", defaults["hit_die_avg"])
    rules_calc(db, cid, TEST_SYSTEM)
    set_attr(db, cid, "build", "weapon_damage_die", "1d8")
    return cid


def _start_encounter(db, session_id, characters, zones, placements, teams=None):
    """Start an encounter with given zones and placements, optionally setting teams."""
    from encounter import start_encounter

    start_encounter(
        db,
        session_id,
        zones,
        [{"character_id": cid, "roll": 20 - i} for i, cid in enumerate(characters)],
        placements=[{"character_id": cid, "zone": z} for cid, z in placements],
        combat_cfg=COMBAT_CFG,
    )

    if teams:
        enc_id = db.execute(
            "SELECT id FROM encounter_state WHERE session_id = ? AND status = 'active'",
            (session_id,),
        ).fetchone()[0]
        for cid, team in teams.items():
            db.execute(
                "UPDATE character_zone SET team = ? WHERE encounter_id = ? AND character_id = ?",
                (team, enc_id, cid),
            )
        db.commit()


def _set_session_system(db, session_id):
    """Point session at the test system pack so build_combat_context can find it."""
    db.execute(
        "INSERT OR REPLACE INTO session_meta (session_id, key, value) VALUES (?, 'rules_system', ?)",
        (session_id, "../tests/fixtures/test_system"),
    )
    db.commit()


def _get_zone(db, session_id, character_id):
    """Return the zone name a character is in."""
    enc_id = db.execute(
        "SELECT id FROM encounter_state WHERE session_id = ? AND status = 'active'",
        (session_id,),
    ).fetchone()[0]
    row = db.execute(
        "SELECT ez.name FROM character_zone cz "
        "JOIN encounter_zones ez ON ez.id = cz.zone_id "
        "WHERE cz.encounter_id = ? AND cz.character_id = ?",
        (enc_id, character_id),
    ).fetchone()
    return row[0] if row else None


# ===========================================================================
# parse_combat_intent
# ===========================================================================


class TestParseCombatIntent:
    def test_parses_json_block(self):
        from npc_combat import parse_combat_intent

        response = """Here's my plan:
```json
{
  "sequence": ["move", "action"],
  "action": "close_attack",
  "target": "Hero",
  "move_to": "Street",
  "narration": "I charge forward!"
}
```"""
        intent = parse_combat_intent(response)
        assert intent["action"] == "close_attack"
        assert intent["target"] == "Hero"
        assert intent["move_to"] == "Street"
        assert intent["sequence"] == ["move", "action"]
        assert intent["narration"] == "I charge forward!"

    def test_parses_bare_json(self):
        from npc_combat import parse_combat_intent

        response = '{"action": "ranged_attack", "target": "Villain", "move_to": null}'
        intent = parse_combat_intent(response)
        assert intent["action"] == "ranged_attack"
        assert intent["target"] == "Villain"
        assert intent["move_to"] is None

    def test_filters_invalid_sequence_steps(self):
        from npc_combat import parse_combat_intent

        response = '{"sequence": ["move", "attack_power", "action", "dance"], "action": "melee_attack", "target": "X"}'
        intent = parse_combat_intent(response)
        assert intent["sequence"] == ["move", "action"]

    def test_fallback_narrative_only(self):
        from npc_combat import parse_combat_intent

        response = "I look around warily, assessing the situation."
        intent = parse_combat_intent(response)
        assert intent["action"] is None
        assert intent["target"] is None
        assert intent["move_to"] is None
        assert intent["narration"] == response

    def test_null_action_treated_as_none(self):
        from npc_combat import parse_combat_intent

        response = '{"action": null, "target": null, "move_to": "Alley"}'
        intent = parse_combat_intent(response)
        assert intent["action"] is None
        assert intent["move_to"] == "Alley"

    def test_empty_string_action_treated_as_none(self):
        from npc_combat import parse_combat_intent

        response = '{"action": "", "target": "", "move_to": ""}'
        intent = parse_combat_intent(response)
        assert intent["action"] is None
        assert intent["target"] is None
        assert intent["move_to"] is None

    def test_multi_move_list(self):
        from npc_combat import parse_combat_intent

        response = '{"sequence": ["move", "action", "move"], "action": "melee_attack", "target": "X", "move_to": ["Near", "Far"]}'
        intent = parse_combat_intent(response)
        assert intent["move_to"] == ["Near", "Far"]
        assert intent["sequence"] == ["move", "action", "move"]

    def test_move_others(self):
        from npc_combat import parse_combat_intent

        response = '{"action": null, "move_others": [{"character": "Ally", "zone": "Rooftop"}]}'
        intent = parse_combat_intent(response)
        assert intent["move_others"] == [{"character": "Ally", "zone": "Rooftop"}]

    def test_ally_field(self):
        from npc_combat import parse_combat_intent

        response = '{"action": "grapple", "target": "Enemy", "ally": "Friend"}'
        intent = parse_combat_intent(response)
        assert intent["ally"] == "Friend"


# ===========================================================================
# build_combat_context
# ===========================================================================


class TestBuildCombatContext:
    def test_includes_all_actions(self, make_session, make_character):
        """Context string must list every action from the system pack."""
        from _db import require_db
        from npc_combat import build_combat_context

        db = require_db()
        try:
            sid = make_session()
            _set_session_system(db, sid)
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Zone A"}, {"name": "Zone B"}],
                [(npc, "Zone A"), (hero, "Zone B")],
            )

            ctx = build_combat_context(db, npc, sid, COMBAT_CFG)

            for action_name in ["melee_attack", "grapple", "shove", "fireball"]:
                assert action_name in ctx, f"Missing action: {action_name}"
        finally:
            db.close()

    def test_lists_enemies_and_allies_by_team(self, make_session, make_character):
        """Characters on the same team appear as allies, others as enemies."""
        from _db import require_db
        from npc_combat import build_combat_context

        db = require_db()
        try:
            sid = make_session()
            _set_session_system(db, sid)
            npc = _make_fighter(db, sid, make_character, "Orc")
            minion = _make_fighter(db, sid, make_character, "Goblin")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, minion, hero],
                [{"name": "Field"}],
                [(npc, "Field"), (minion, "Field"), (hero, "Field")],
                teams={npc: "monsters", minion: "monsters", hero: "heroes"},
            )

            ctx = build_combat_context(db, npc, sid, COMBAT_CFG)

            enemies_section = ctx.split("Enemies:")[1].split("Allies:")[0]
            allies_section = ctx.split("Allies:")[1].split("Zones:")[0]

            assert "Hero" in enemies_section
            assert "Goblin" in allies_section
            assert "Hero" not in allies_section
            assert "Goblin" not in enemies_section
        finally:
            db.close()

    def test_includes_zone_names_and_tags(self, make_session, make_character):
        from _db import require_db
        from npc_combat import build_combat_context

        db = require_db()
        try:
            sid = make_session()
            _set_session_system(db, sid)
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Hilltop", "tags": ["cover"]}, {"name": "Valley"}],
                [(npc, "Hilltop"), (hero, "Valley")],
            )

            ctx = build_combat_context(db, npc, sid, COMBAT_CFG)

            assert "Hilltop" in ctx
            assert "Valley" in ctx
            assert "cover" in ctx
        finally:
            db.close()

    def test_includes_npc_abilities(self, make_session, make_character):
        """NPC abilities should appear in the context."""
        from _db import require_db
        from npc_combat import build_combat_context

        db = require_db()
        try:
            sid = make_session()
            _set_session_system(db, sid)
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            db.execute(
                "INSERT INTO character_abilities (character_id, name, uses, description, category) "
                "VALUES (?, 'Cleave', 'at_will', 'Hit two adjacent targets', 'feat')",
                (npc,),
            )
            db.commit()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            ctx = build_combat_context(db, npc, sid, COMBAT_CFG)
            assert "Cleave" in ctx
            assert "Hit two adjacent targets" in ctx
        finally:
            db.close()

    def test_shows_relative_health(self, make_session, make_character):
        """HP-based health shows wound level."""
        from _db import require_db
        from character import set_attr
        from npc_combat import _get_relative_health, build_combat_context

        db = require_db()
        try:
            sid = make_session()
            _set_session_system(db, sid)
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            # max_hp = hit_die_avg(6)*1 + con_mod(1)*1 = 7, set current below half
            set_attr(db, hero, "derived", "current_hp", "3")

            hud = COMBAT_CFG["hud"]

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            ctx = build_combat_context(db, npc, sid, COMBAT_CFG)
            assert "wounded" in ctx
        finally:
            db.close()


# ===========================================================================
# execute_combat_turn — action resolution
# ===========================================================================


class TestExecuteAction:
    def test_melee_hit(self, make_session, make_character):
        from _db import require_db
        from character import set_attr
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")
            set_attr(db, hero, "combat", "current_hp", "35")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "melee_attack", "target": "Hero"}

            roll_calls = iter([17, 5])  # d20=18 (hit), d8=6
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output
            assert "DAMAGE:" in output
        finally:
            db.close()

    def test_melee_miss(self, make_session, make_character):
        from _db import require_db
        from character import set_attr
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc", str="10", base_attack="1")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc", dex="20")
            set_attr(db, hero, "combat", "current_hp", "35")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "melee_attack", "target": "Hero"}

            roll_calls = iter([0])  # d20=1
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)

            output = "\n".join(lines)
            assert "MISS!" in output
        finally:
            db.close()

    def test_contested_hit_applies_modifiers(self, make_session, make_character):
        """Grapple win applies combat_state modifiers to target."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "grapple", "target": "Hero"}

            roll_calls = iter([17, 4])  # attacker 18, defender 5
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output

            mods = db.execute(
                "SELECT source, target_stat FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            assert any(m[0] == "grapple" for m in mods)
        finally:
            db.close()

    def test_contested_miss_no_modifiers(self, make_session, make_character):
        """Grapple loss applies no modifiers."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc", str="10", base_attack="1")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "grapple", "target": "Hero"}

            roll_calls = iter([2, 17])  # attacker 3, defender 18
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)

            output = "\n".join(lines)
            assert "MISS!" in output

            mods = db.execute(
                "SELECT source FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            assert len(mods) == 0
        finally:
            db.close()


# ===========================================================================
# execute_combat_turn — movement
# ===========================================================================


class TestExecuteMovement:
    def test_move_then_attack(self, make_session, make_character):
        """NPC moves to target's zone then attacks."""
        from _db import require_db
        from character import set_attr
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")
            set_attr(db, hero, "combat", "current_hp", "35")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Near"}, {"name": "Far"}],
                [(npc, "Near"), (hero, "Far")],
            )

            intent = {
                "sequence": ["move", "action"],
                "action": "melee_attack",
                "target": "Hero",
                "move_to": "Far",
            }

            roll_calls = iter([17, 5])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)

            output = "\n".join(lines)
            assert "Far" in output
            assert "HIT!" in output or "MISS!" in output
        finally:
            db.close()

    def test_attack_then_move(self, make_session, make_character):
        """NPC attacks then repositions (Move-by Action pattern)."""
        from _db import require_db
        from character import set_attr
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")
            set_attr(db, hero, "combat", "current_hp", "35")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Near"}, {"name": "Far"}],
                [(npc, "Near"), (hero, "Near")],
            )

            intent = {
                "sequence": ["action", "move"],
                "action": "melee_attack",
                "target": "Hero",
                "move_to": "Far",
            }

            roll_calls = iter([17, 5])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output or "MISS!" in output
            assert _get_zone(db, sid, npc) == "Far"
        finally:
            db.close()

    def test_multi_move(self, make_session, make_character):
        """NPC moves through multiple zones in sequence."""
        from _db import require_db
        from character import set_attr
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")
            set_attr(db, hero, "combat", "current_hp", "35")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "North"}, {"name": "Center"}, {"name": "South"}],
                [(npc, "North"), (hero, "South")],
            )

            intent = {
                "sequence": ["move", "action", "move"],
                "action": "melee_attack",
                "target": "Hero",
                "move_to": ["South", "Center"],
            }

            roll_calls = iter([17, 5])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)

            assert _get_zone(db, sid, npc) == "Center"
        finally:
            db.close()


# ===========================================================================
# execute_combat_turn — error handling
# ===========================================================================


class TestExecuteErrorHandling:
    def test_unknown_action_reports_error(self, make_session, make_character):
        """NPC uses an invalid action name → error line, not crash."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "dragon_breath", "target": "Hero"}

            lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)
            output = "\n".join(lines)
            assert "FAILED" in output or "NOTE:" in output
        finally:
            db.close()

    def test_missing_target_reports_error(self, make_session, make_character):
        """Target name doesn't match any character → error line."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "melee_attack", "target": "Ghost"}

            lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)
            output = "\n".join(lines)
            assert "not found" in output.lower() or "FAILED" in output
        finally:
            db.close()

    def test_action_without_target_skipped(self, make_session, make_character):
        """Action specified but no target → skip with message."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "melee_attack", "target": None}

            lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)
            output = "\n".join(lines)
            assert "SKIPPED" in output
        finally:
            db.close()

    def test_narrative_only_turn(self, make_session, make_character):
        """No action and no movement → just advance turn."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {
                "sequence": ["move", "action"],
                "action": None,
                "target": None,
                "move_to": None,
                "narration": "I wait and observe.",
            }

            lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)
            output = "\n".join(lines)
            assert "Round" in output or "Turn" in output or "advanced" in output.lower()
        finally:
            db.close()

    def test_melee_out_of_range_reported(self, make_session, make_character):
        """Melee from a different zone without moving first → error."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Orc")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "North"}, {"name": "South"}],
                [(npc, "North"), (hero, "South")],
            )

            intent = {"sequence": ["action"], "action": "melee_attack", "target": "Hero"}

            lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)
            output = "\n".join(lines)
            assert "FAILED" in output
            assert "range" in output.lower()
        finally:
            db.close()


# ===========================================================================
# execute_combat_turn — move_others
# ===========================================================================


class TestExecuteMoveOthers:
    def test_move_others(self, make_session, make_character):
        """NPC can move other characters via move_others intent."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_fighter(db, sid, make_character, "Caster")
            ally = _make_fighter(db, sid, make_character, "Ally")
            hero = _make_fighter(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [npc, ally, hero],
                [{"name": "North"}, {"name": "South"}],
                [(npc, "North"), (ally, "North"), (hero, "South")],
            )

            intent = {
                "sequence": ["move_others"],
                "action": None,
                "target": None,
                "move_others": [{"character": "Ally", "zone": "South"}],
            }

            lines = execute_combat_turn(db, npc, sid, intent, COMBAT_CFG, TEST_SYSTEM)
            assert _get_zone(db, sid, ally) == "South"
        finally:
            db.close()
