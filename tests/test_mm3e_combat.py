"""M&M3e-specific combat tests through execute_combat_turn.

Validates degree resolution, contested skill actions, grab conditions,
and damage_penalty tracking — features specific to the M&M3e system pack.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

MM3E_SYSTEM = os.path.join(os.path.dirname(__file__), "..", "systems", "mm3e")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _combat_cfg():
    """Return the combat config from the M&M3e system pack."""
    with open(os.path.join(MM3E_SYSTEM, "system.json")) as f:
        return json.load(f)["combat"]


def _make_character(db, session_id, make_character, name, char_type="npc", **stats):
    """Create a character with M&M3e stats and run rules_calc."""
    from character import set_attr
    from rules_engine import rules_calc

    cid = make_character(session_id, name=name, char_type=char_type)
    defaults = {
        "fgt": "6",
        "agl": "2",
        "dex": "2",
        "str": "4",
        "sta": "4",
        "int": "0",
        "awe": "2",
        "pre": "2",
    }
    defaults.update(stats)
    for key, val in defaults.items():
        set_attr(db, cid, "stat", key, str(val))
    rules_calc(db, cid, MM3E_SYSTEM)
    return cid


def _start_encounter(db, session_id, characters, zones, placements):
    """Start an encounter with given zones and placements."""
    from encounter import start_encounter

    cfg = _combat_cfg()
    start_encounter(
        db,
        session_id,
        zones,
        [{"character_id": cid, "roll": 20 - i} for i, cid in enumerate(characters)],
        placements=[{"character_id": cid, "zone": z} for cid, z in placements],
        combat_cfg=cfg,
    )


# ===========================================================================
# Degree resolution — close_attack
# ===========================================================================


class TestCloseAttack:
    def test_hit_applies_damage_penalty(self, make_session, make_character):
        """Hit + failed resistance → damage_penalty incremented."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Villain")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "close_attack", "target": "Hero"}

            # Attack d20=15 → hit, Resistance d20=5 → fail
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output
            assert "RESISTANCE:" in output

            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'damage_penalty'",
                (hero,),
            ).fetchone()
            assert row is not None
            assert int(row[0]) > 0
        finally:
            db.close()

    def test_miss_against_high_dodge(self, make_session, make_character):
        """Low attack vs high dodge → miss, no resistance check."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Villain", fgt="2")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", agl="8", ranks_dodge="4")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "close_attack", "target": "Hero"}

            # d20=3 → 3 + 2 = 5 vs DC 10+12 = 22
            roll_calls = iter([2])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "MISS!" in output
        finally:
            db.close()


# ===========================================================================
# Contested skill actions — setup_deception / setup_intimidation
# ===========================================================================


class TestSetupActions:
    def test_deception_applies_vulnerable(self, make_session, make_character):
        """Deception wins contested roll → vulnerable modifiers on target."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Trickster", pre="6", ranks_deception="8")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", awe="2", ranks_insight="0")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "setup_deception", "target": "Hero"}

            # NPC 15 + skill_deception(14) = 29, Hero 5 + skill_insight(2) = 7
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output

            mods = db.execute(
                "SELECT source, target_stat FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            mod_stats = {m[1] for m in mods}
            assert "bonus_parry" in mod_stats or "bonus_dodge" in mod_stats
        finally:
            db.close()

    def test_intimidation_applies_vulnerable(self, make_session, make_character):
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Brute", pre="6", ranks_intimidation="8")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", awe="2", ranks_insight="0")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "setup_intimidation", "target": "Hero"}

            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output

            mods = db.execute(
                "SELECT source, target_stat FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            mod_stats = {m[1] for m in mods}
            assert "bonus_parry" in mod_stats or "bonus_dodge" in mod_stats
        finally:
            db.close()

    def test_contested_miss(self, make_session, make_character):
        """Defender wins → no modifiers applied."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Trickster", pre="2", ranks_deception="0")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", awe="6", ranks_insight="8")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "setup_deception", "target": "Hero"}

            # NPC 5 + 2 = 7, Hero 15 + 14 = 29
            roll_calls = iter([4, 14])
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "MISS!" in output

            mods = db.execute(
                "SELECT source FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            assert len(mods) == 0
        finally:
            db.close()

    def test_setup_then_verify_modifiers(self, make_session, make_character):
        """Full cycle: setup applies vulnerable, modifiers exist on target."""
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            trickster = _make_character(db, sid, make_character, "Trickster", pre="6", ranks_deception="8")
            hero = _make_character(
                db, sid, make_character, "Hero", char_type="pc", fgt="4", agl="4", ranks_parry="2", ranks_dodge="2"
            )
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [trickster, hero],
                [{"name": "Arena"}],
                [(trickster, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "setup_deception", "target": "Hero"}

            roll_calls = iter([17, 2])  # 18 vs 3, easy win
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, trickster, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output

            mods = db.execute(
                "SELECT target_stat, value FROM combat_state WHERE character_id = ? AND source = 'vulnerable'",
                (hero,),
            ).fetchall()
            assert len(mods) > 0, "Vulnerable modifiers should be applied"
            mod_stats = {m[0] for m in mods}
            assert "bonus_parry" in mod_stats or "bonus_dodge" in mod_stats
        finally:
            db.close()


# ===========================================================================
# Grab — on_hit modifiers without resistance check
# ===========================================================================


class TestGrab:
    def test_grab_applies_until_escape_modifiers(self, make_session, make_character):
        from _db import require_db
        from npc_combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Grappler", fgt="8")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc", fgt="2")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena"}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            intent = {"sequence": ["action"], "action": "grab", "target": "Hero"}

            roll_calls = iter([14])  # d20=15 → hit
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, npc, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "HIT!" in output

            mods = db.execute(
                "SELECT source, target_stat, duration_type FROM combat_state WHERE character_id = ?",
                (hero,),
            ).fetchall()
            mod_stats = {m[1] for m in mods}
            assert "bonus_dodge" in mod_stats
            assert "bonus_speed" in mod_stats
            for m in mods:
                assert m[2] == "until_escape"
        finally:
            db.close()
