"""Condition enforcement tests — miss_chance, max_move, escape_check."""

import json
import os
from unittest.mock import patch

import cruncher_mm3e
import cruncher_pf2e
import pytest

MM3E_SYSTEM = cruncher_mm3e.pack_path()
PF2E_SYSTEM = cruncher_pf2e.pack_path()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _combat_cfg(system_dir=MM3E_SYSTEM):
    with open(os.path.join(system_dir, "system.json")) as f:
        return json.load(f)["combat"]


def _make_character(db, session_id, make_character, name, system_dir=MM3E_SYSTEM, char_type="npc", **stats):
    from lorekit.character import set_attr
    from lorekit.rules import rules_calc

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
    rules_calc(db, cid, system_dir)
    return cid


def _start_encounter(db, session_id, characters, zones, placements, system_dir=MM3E_SYSTEM):
    from lorekit.encounter import start_encounter

    cfg = _combat_cfg(system_dir)
    start_encounter(
        db,
        session_id,
        zones,
        [{"character_id": cid, "roll": 20 - i} for i, cid in enumerate(characters)],
        placements=[{"character_id": cid, "zone": z} for cid, z in placements],
        combat_cfg=cfg,
    )


# ===========================================================================
# 1.1 — miss_chance
# ===========================================================================


class TestMissChance:
    def test_miss_chance_converts_hit_to_miss(self, make_session, make_character):
        """When defender has concealment (miss_chance), a hit can become a miss."""
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            attacker = _make_character(db, sid, make_character, "Attacker")
            defender = _make_character(db, sid, make_character, "Defender", char_type="pc")
            cfg = _combat_cfg()

            # Both in same zone with concealment (defender has concealment)
            _start_encounter(
                db,
                sid,
                [attacker, defender],
                [{"name": "Fog", "tags": ["concealment"]}],
                [(attacker, "Fog"), (defender, "Fog")],
            )

            intent = {"sequence": ["action"], "action": "close_attack", "targets": ["Defender"]}

            # d20=19 → guaranteed hit, but random.random() returns 0.1 < 0.2 → miss
            roll_calls = iter([18])  # d20=19
            with (
                patch("secrets.randbelow", side_effect=roll_calls),
                patch("lorekit.combat.resolve.random.random", return_value=0.1),
            ):
                lines = execute_combat_turn(db, attacker, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "MISS CHANCE" in output
            assert "MISS!" in output
        finally:
            db.close()

    def test_miss_chance_does_not_affect_actual_miss(self, make_session, make_character):
        """miss_chance should not trigger when the attack already missed."""
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            attacker = _make_character(db, sid, make_character, "Attacker")
            defender = _make_character(db, sid, make_character, "Defender", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [attacker, defender],
                [{"name": "Fog", "tags": ["concealment"]}],
                [(attacker, "Fog"), (defender, "Fog")],
            )

            intent = {"sequence": ["action"], "action": "close_attack", "targets": ["Defender"]}

            # d20=1 → miss naturally; miss_chance should not appear
            roll_calls = iter([0])  # d20=1
            with patch("secrets.randbelow", side_effect=roll_calls):
                lines = execute_combat_turn(db, attacker, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "MISS CHANCE" not in output
            assert "MISS!" in output
        finally:
            db.close()

    def test_miss_chance_pass_still_hits(self, make_session, make_character):
        """When the percentile roll exceeds miss_chance, the hit stands."""
        from lorekit.db import require_db
        from lorekit.npc.combat import execute_combat_turn

        db = require_db()
        try:
            sid = make_session()
            attacker = _make_character(db, sid, make_character, "Attacker")
            defender = _make_character(db, sid, make_character, "Defender", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [attacker, defender],
                [{"name": "Fog", "tags": ["concealment"]}],
                [(attacker, "Fog"), (defender, "Fog")],
            )

            intent = {"sequence": ["action"], "action": "close_attack", "targets": ["Defender"]}

            # d20=19 → hit, random.random()=0.5 > 0.2 → miss chance fails, hit stands
            # Also need a resistance roll
            roll_calls = iter([18, 4])  # attack d20=19, resist d20=5
            with (
                patch("secrets.randbelow", side_effect=roll_calls),
                patch("lorekit.combat.resolve.random.random", return_value=0.5),
            ):
                lines = execute_combat_turn(db, attacker, sid, intent, cfg, MM3E_SYSTEM)

            output = "\n".join(lines)
            assert "MISS CHANCE" not in output
            assert "HIT!" in output
        finally:
            db.close()


# ===========================================================================
# 1.2 — max_move
# ===========================================================================


class TestMaxMove:
    def test_immobile_condition_prevents_movement(self, make_session, make_character):
        """A character with an active immobile condition (max_move: 0) cannot move."""
        from lorekit.db import LoreKitError, require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_character(db, sid, make_character, "Victim", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [cid],
                [{"name": "A"}, {"name": "B"}],
                [(cid, "A")],
            )
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            # Manually insert a modifier with source "immobile" → triggers condition
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'immobile', 'bonus_speed', 'condition', -999, 'encounter')",
                (cid,),
            )
            db.commit()

            from lorekit.encounter import move_character

            with pytest.raises(LoreKitError, match="Cannot move.*immobile"):
                move_character(db, enc_id, cid, "B", combat_cfg=cfg)
        finally:
            db.close()

    def test_grab_condition_prevents_movement(self, make_session, make_character):
        """A grabbed character (max_move: 0) cannot move."""
        from lorekit.db import LoreKitError, require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_character(db, sid, make_character, "Grabbed", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [cid],
                [{"name": "A"}, {"name": "B"}],
                [(cid, "A")],
            )
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            # Insert grab marker → triggers grab condition via condition_rules
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'grab', 'bonus_dodge', 'condition', 0, 'until_escape')",
                (cid,),
            )
            db.commit()

            from lorekit.encounter import move_character

            with pytest.raises(LoreKitError, match="Cannot move.*grab"):
                move_character(db, enc_id, cid, "B", combat_cfg=cfg)
        finally:
            db.close()

    def test_normal_movement_still_works(self, make_session, make_character):
        """Without blocking conditions, movement should work normally."""
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_character(db, sid, make_character, "Free", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [cid],
                [{"name": "A"}, {"name": "B"}],
                [(cid, "A")],
            )
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            from lorekit.encounter import move_character

            result = move_character(db, enc_id, cid, "B", combat_cfg=cfg)
            assert "MOVED" in result
        finally:
            db.close()


# ===========================================================================
# 1.3 — until_escape (escape_check)
# ===========================================================================


class TestEscapeCheck:
    def test_escape_check_succeeds_removes_modifier(self, make_session, make_character):
        """Successful escape check removes the until_escape modifier."""
        from lorekit.combat.turns import end_turn
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            grabber = _make_character(db, sid, make_character, "Grabber")
            victim = _make_character(db, sid, make_character, "Victim", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [grabber, victim],
                [{"name": "Arena"}],
                [(grabber, "Arena"), (victim, "Arena")],
            )

            # Insert until_escape modifier (grab) with applied_by = grabber
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type, applied_by) "
                "VALUES (?, 'grab', 'bonus_dodge', 'condition', 0, 'until_escape', ?)",
                (victim, grabber),
            )
            db.commit()

            # Escape roll: d20=18 → 18 + athletics bonus vs grab_dc
            # With high roll, should succeed
            roll_calls = iter([17])  # d20=18
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = end_turn(db, victim, MM3E_SYSTEM)

            assert "ESCAPE" in result
            assert "ESCAPED" in result or "FREED" in result

            # Modifier should be removed
            remaining = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'grab'",
                (victim,),
            ).fetchone()[0]
            assert remaining == 0
        finally:
            db.close()

    def test_escape_check_fails_keeps_modifier(self, make_session, make_character):
        """Failed escape check keeps the until_escape modifier."""
        from lorekit.combat.turns import end_turn
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            grabber = _make_character(db, sid, make_character, "Grabber", str="10")
            victim = _make_character(db, sid, make_character, "Victim", char_type="pc", str="0")
            cfg = _combat_cfg()

            _start_encounter(
                db,
                sid,
                [grabber, victim],
                [{"name": "Arena"}],
                [(grabber, "Arena"), (victim, "Arena")],
            )

            # Insert until_escape modifier
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type, applied_by) "
                "VALUES (?, 'grab', 'bonus_dodge', 'condition', 0, 'until_escape', ?)",
                (victim, grabber),
            )
            db.commit()

            # Low escape roll: d20=2
            roll_calls = iter([1])  # d20=2
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = end_turn(db, victim, MM3E_SYSTEM)

            assert "ESCAPE" in result
            assert "HELD" in result

            # Modifier should still be present
            remaining = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'grab'",
                (victim,),
            ).fetchone()[0]
            assert remaining == 1
        finally:
            db.close()
