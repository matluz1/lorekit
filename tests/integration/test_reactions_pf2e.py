"""PF2e reaction integration tests — Shield Block, Reactive Strike, pending flow."""

import json
import os
from unittest.mock import patch

import cruncher_pf2e
import pytest

from lorekit.character import set_attr
from lorekit.combat.resolve import resolve_action
from lorekit.db import require_db
from lorekit.encounter import start_encounter
from lorekit.rules import rules_calc

PF2E_SYSTEM = cruncher_pf2e.pack_path()


def _pf2e_combat_cfg():
    with open(os.path.join(PF2E_SYSTEM, "system.json")) as f:
        return json.load(f)["combat"]


def _make_pf2e_char(db, session_id, make_character, name, char_type="pc", **overrides):
    cid = make_character(session_id, name=name, char_type=char_type)
    defaults = {
        "str": "16",
        "dex": "14",
        "con": "14",
        "int": "10",
        "wis": "12",
        "cha": "10",
        "level": "3",
        "ancestry_hp": "8",
        "hp_per_level": "10",
        "prof_simple_weapons": "2",
        "prof_unarmored": "2",
        "prof_perception": "2",
        "prof_fortitude": "4",
        "prof_reflex": "2",
        "prof_will": "2",
        "item_bonus_ac": "4",
        "armor_dex_cap": "3",
    }
    defaults.update(overrides)
    for key, val in defaults.items():
        set_attr(db, cid, "stat", key, str(val))
    rules_calc(db, cid, PF2E_SYSTEM)
    set_attr(db, cid, "build", "weapon_damage_die", "1d8")
    return cid


def _add_shield_block(db, char_id, policy="active"):
    set_attr(db, char_id, "combat", "shield_hardness", "5")
    set_attr(db, char_id, "combat", "shield_hp", "20")
    db.execute(
        "INSERT INTO combat_state "
        "(character_id, source, target_stat, modifier_type, value, "
        "duration_type, duration, metadata) "
        "VALUES (?, ?, '_reaction', 'reaction', 0, 'reaction', 1, ?)",
        (
            char_id,
            "shield_block",
            json.dumps(
                {
                    "hook": "damage_reduction",
                    "reaction_key": "shield_block",
                    "effects": [
                        {"type": "reduce_damage", "stat": "shield_hardness"},
                        {"type": "damage_item", "item_stat": "shield_hp"},
                    ],
                }
            ),
        ),
    )
    if policy != "active":
        set_attr(db, char_id, "reaction_policy", "shield_block", policy)
    db.commit()


def _add_reactive_strike(db, char_id, policy="active"):
    db.execute(
        "INSERT INTO combat_state "
        "(character_id, source, target_stat, modifier_type, value, "
        "duration_type, duration, metadata) "
        "VALUES (?, ?, '_reaction', 'reaction', 0, 'reaction', 1, ?)",
        (
            char_id,
            "reactive_strike",
            json.dumps(
                {
                    "hook": "after_hit",
                    "reaction_key": "reactive_strike",
                    "effects": [{"type": "counter_attack", "action": "melee_attack"}],
                }
            ),
        ),
    )
    if policy != "active":
        set_attr(db, char_id, "reaction_policy", "reactive_strike", policy)
    db.commit()


class TestShieldBlockActive:
    def test_active_shield_block_reduces_damage(self, make_session, make_character):
        """NPC with active Shield Block: damage auto-reduced."""
        db = require_db()
        try:
            sid = make_session()
            cfg = _pf2e_combat_cfg()
            atk = _make_pf2e_char(db, sid, make_character, "Goblin", char_type="npc")
            dfn = _make_pf2e_char(db, sid, make_character, "Fighter", char_type="npc")
            _add_shield_block(db, dfn, policy="active")

            start_encounter(
                db,
                sid,
                [{"name": "Arena"}],
                [{"character_id": atk, "roll": 20}, {"character_id": dfn, "roll": 10}],
                placements=[{"character_id": atk, "zone": "Arena"}, {"character_id": dfn, "zone": "Arena"}],
                combat_cfg=cfg,
            )

            max_hp = int(
                db.execute(
                    "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'max_hp'",
                    (dfn,),
                ).fetchone()[0]
            )

            # d20=18 (hit), d8=7 -> damage = 7 + str_mod(3) = 10, minus 5 hardness = 5 net
            roll_calls = iter([17, 6])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "melee_attack", PF2E_SYSTEM)

            assert "HIT!" in output
            assert "SHIELD BLOCK" in output

            hp = int(
                db.execute(
                    "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'current_hp'",
                    (dfn,),
                ).fetchone()[0]
            )
            assert hp == max_hp - 5
        finally:
            db.close()

    def test_inactive_skips_shield_block(self, make_session, make_character):
        """Inactive Shield Block: full damage applied."""
        db = require_db()
        try:
            sid = make_session()
            cfg = _pf2e_combat_cfg()
            atk = _make_pf2e_char(db, sid, make_character, "Goblin", char_type="npc")
            dfn = _make_pf2e_char(db, sid, make_character, "Fighter", char_type="npc")
            _add_shield_block(db, dfn, policy="inactive")

            start_encounter(
                db,
                sid,
                [{"name": "Arena"}],
                [{"character_id": atk, "roll": 20}, {"character_id": dfn, "roll": 10}],
                placements=[{"character_id": atk, "zone": "Arena"}, {"character_id": dfn, "zone": "Arena"}],
                combat_cfg=cfg,
            )

            max_hp = int(
                db.execute(
                    "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'max_hp'",
                    (dfn,),
                ).fetchone()[0]
            )

            roll_calls = iter([17, 6])  # damage = 10
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "melee_attack", PF2E_SYSTEM)

            assert "HIT!" in output
            assert "SHIELD BLOCK" not in output

            hp = int(
                db.execute(
                    "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'current_hp'",
                    (dfn,),
                ).fetchone()[0]
            )
            assert hp == max_hp - 10
        finally:
            db.close()


class TestShieldBlockPending:
    def test_pending_pauses_then_confirm_reduces(self, make_session, make_character):
        """PC Shield Block with pending: two-phase resolution."""
        db = require_db()
        try:
            sid = make_session()
            cfg = _pf2e_combat_cfg()
            atk = _make_pf2e_char(db, sid, make_character, "Goblin", char_type="npc")
            dfn = _make_pf2e_char(db, sid, make_character, "Fighter", char_type="pc")
            _add_shield_block(db, dfn, policy="pending")

            start_encounter(
                db,
                sid,
                [{"name": "Arena"}],
                [{"character_id": atk, "roll": 20}, {"character_id": dfn, "roll": 10}],
                placements=[{"character_id": atk, "zone": "Arena"}, {"character_id": dfn, "zone": "Arena"}],
                combat_cfg=cfg,
            )

            max_hp = int(
                db.execute(
                    "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'max_hp'",
                    (dfn,),
                ).fetchone()[0]
            )

            roll_calls = iter([17, 6])  # damage = 10
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "melee_attack", PF2E_SYSTEM)

            assert "PENDING REACTION" in output

            # HP unchanged
            hp_row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'current_hp'",
                (dfn,),
            ).fetchone()
            if hp_row:
                assert int(hp_row[0]) == max_hp

            # Confirm with shield_block
            pending_row = db.execute(
                "SELECT id FROM pending_resolutions WHERE session_id = ?",
                (sid,),
            ).fetchone()
            from lorekit.combat.pending import confirm_pending

            result = confirm_pending(db, pending_row[0], reactions=["shield_block"])
            assert "SHIELD BLOCK" in result

            hp = int(
                db.execute(
                    "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'current_hp'",
                    (dfn,),
                ).fetchone()[0]
            )
            assert hp == max_hp - 5  # 10 - 5 hardness
        finally:
            db.close()

    def test_pending_declined_full_damage(self, make_session, make_character):
        """PC declines Shield Block: full damage on confirm."""
        db = require_db()
        try:
            sid = make_session()
            cfg = _pf2e_combat_cfg()
            atk = _make_pf2e_char(db, sid, make_character, "Goblin", char_type="npc")
            dfn = _make_pf2e_char(db, sid, make_character, "Fighter", char_type="pc")
            _add_shield_block(db, dfn, policy="pending")

            start_encounter(
                db,
                sid,
                [{"name": "Arena"}],
                [{"character_id": atk, "roll": 20}, {"character_id": dfn, "roll": 10}],
                placements=[{"character_id": atk, "zone": "Arena"}, {"character_id": dfn, "zone": "Arena"}],
                combat_cfg=cfg,
            )

            max_hp = int(
                db.execute(
                    "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'max_hp'",
                    (dfn,),
                ).fetchone()[0]
            )

            roll_calls = iter([17, 6])
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "melee_attack", PF2E_SYSTEM)

            assert "PENDING REACTION" in output

            pending_row = db.execute(
                "SELECT id FROM pending_resolutions WHERE session_id = ?",
                (sid,),
            ).fetchone()
            from lorekit.combat.pending import confirm_pending

            confirm_pending(db, pending_row[0], reactions=[])

            hp = int(
                db.execute(
                    "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'current_hp'",
                    (dfn,),
                ).fetchone()[0]
            )
            assert hp == max_hp - 10  # Full damage
        finally:
            db.close()


class TestReactiveStrike:
    def test_reactive_strike_counter_attacks(self, make_session, make_character):
        """Reactive Strike fires counter-attack after being hit."""
        db = require_db()
        try:
            sid = make_session()
            cfg = _pf2e_combat_cfg()
            atk = _make_pf2e_char(db, sid, make_character, "Goblin", char_type="npc")
            dfn = _make_pf2e_char(db, sid, make_character, "Fighter", char_type="npc")
            _add_reactive_strike(db, dfn, policy="active")

            start_encounter(
                db,
                sid,
                [{"name": "Arena"}],
                [{"character_id": atk, "roll": 20}, {"character_id": dfn, "roll": 10}],
                placements=[{"character_id": atk, "zone": "Arena"}, {"character_id": dfn, "zone": "Arena"}],
                combat_cfg=cfg,
            )

            # Main attack hits, counter also resolves
            roll_calls = iter([17, 6, 15, 4])  # main d20, main dmg, counter d20, counter dmg
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, atk, dfn, "melee_attack", PF2E_SYSTEM)

            assert "HIT!" in output
            assert "REACTION [reactive_strike]" in output
            assert "counter-attacks" in output
        finally:
            db.close()
