"""Tests for the end_turn duration ticking engine."""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from combat_engine import end_turn

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


def _setup_character(db, make_session, make_character, set_attr, name="Fighter"):
    """Create a character with derived stats computed."""
    sid = make_session()
    cid = make_character(sid, name=name, level=5)
    for key, val in [
        ("str", "18"),
        ("dex", "14"),
        ("con", "12"),
        ("base_attack", "5"),
        ("hit_die_avg", "6"),
    ]:
        set_attr(db, cid, "stat", key, val)

    from rules_engine import rules_calc

    rules_calc(db, cid, TEST_SYSTEM)

    return sid, cid


class TestDecrementBehavior:
    def test_decrement_ticks_down(self, make_session, make_character):
        """Rounds modifier decrements from 3 to 2."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            # Add a 3-round buff
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "bonus_type, duration_type, duration) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, "haste", "bonus_melee_attack", "buff", 2, None, "rounds", 3),
            )
            db.commit()

            output = end_turn(db, cid, TEST_SYSTEM)

            assert "TICKED: haste (2 rounds remaining)" in output

            # Verify DB was updated
            row = db.execute(
                "SELECT duration FROM combat_state WHERE character_id = ? AND source = 'haste'",
                (cid,),
            ).fetchone()
            assert row[0] == 2
        finally:
            db.close()

    def test_decrement_expires_at_zero(self, make_session, make_character):
        """Modifier with duration=1 expires (removed) after decrement."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "bonus_type, duration_type, duration) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, "shield_of_faith", "bonus_defense", "buff", 2, None, "rounds", 1),
            )
            db.commit()

            output = end_turn(db, cid, TEST_SYSTEM)

            assert "EXPIRED: shield_of_faith" in output
            assert "removed" in output

            # Verify modifier was deleted
            row = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'shield_of_faith'",
                (cid,),
            ).fetchone()
            assert row[0] == 0
        finally:
            db.close()

    def test_encounter_duration_not_ticked(self, make_session, make_character):
        """Encounter-duration modifiers are NOT ticked by end_turn."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (cid, "rage", "bonus_melee_attack", "buff", 2, "encounter"),
            )
            db.commit()

            output = end_turn(db, cid, TEST_SYSTEM)

            # encounter modifiers are not mentioned (no tick config for them)
            assert "rage" not in output

            # Still exists in DB
            row = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'rage'",
                (cid,),
            ).fetchone()
            assert row[0] == 1
        finally:
            db.close()

    def test_multiple_modifiers_mixed(self, make_session, make_character):
        """Multiple modifiers: one ticks, one expires, one untouched."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            # 3-round buff → ticks to 2
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type, duration) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, "haste", "bonus_melee_attack", "buff", 1, "rounds", 3),
            )
            # 1-round buff → expires
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type, duration) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, "shield", "bonus_defense", "buff", 2, "rounds", 1),
            )
            # encounter buff → untouched
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (cid, "rage", "bonus_melee_attack", "buff", 2, "encounter"),
            )
            db.commit()

            output = end_turn(db, cid, TEST_SYSTEM)

            assert "TICKED: haste (2 rounds remaining)" in output
            assert "EXPIRED: shield" in output
            assert "rage" not in output

            # Verify: haste still exists with duration 2, shield gone, rage untouched
            remaining = db.execute(
                "SELECT source, duration FROM combat_state WHERE character_id = ? ORDER BY source",
                (cid,),
            ).fetchall()
            sources = {r[0]: r[1] for r in remaining}
            assert sources == {"haste": 2, "rage": None}
        finally:
            db.close()


class TestCheckBehavior:
    def test_check_save_success_removes(self, make_session, make_character):
        """Save-ends modifier: successful save removes the modifier."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            # Add a save-ends modifier (save on melee_attack, DC 15)
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type, save_stat, save_dc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, "paralysis", "bonus_melee_attack", "debuff", -4, "save_ends", "melee_attack", 15),
            )
            db.commit()

            # Mock: d20=18 → 18 + 9 (melee_attack) = 27 >= DC 15 → SUCCESS
            with patch("secrets.randbelow", return_value=17):  # 17+1=18
                output = end_turn(db, cid, TEST_SYSTEM)

            assert "SAVE: paralysis" in output
            assert "SUCCESS" in output
            assert "REMOVED: paralysis" in output

            # Verify removed from DB
            row = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'paralysis'",
                (cid,),
            ).fetchone()
            assert row[0] == 0
        finally:
            db.close()

    def test_check_save_failure_keeps(self, make_session, make_character):
        """Save-ends modifier: failed save keeps the modifier."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type, save_stat, save_dc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, "paralysis", "bonus_melee_attack", "debuff", -4, "save_ends", "melee_attack", 50),
            )
            db.commit()

            # Mock: d20=3 → 3 + 9 = 12 < DC 50 → FAILURE
            with patch("secrets.randbelow", return_value=2):
                output = end_turn(db, cid, TEST_SYSTEM)

            assert "SAVE: paralysis" in output
            assert "FAILURE" in output
            assert "REMOVED" not in output

            # Still in DB
            row = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'paralysis'",
                (cid,),
            ).fetchone()
            assert row[0] == 1
        finally:
            db.close()

    def test_check_missing_save_metadata_skipped(self, make_session, make_character):
        """Save-ends modifier without save_stat/save_dc is skipped."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (cid, "mystery", "bonus_defense", "debuff", -2, "save_ends"),
            )
            db.commit()

            output = end_turn(db, cid, TEST_SYSTEM)

            assert "SKIPPED: mystery" in output
            assert "missing save_stat/save_dc" in output
        finally:
            db.close()


class TestRecompute:
    def test_expired_modifier_triggers_recompute(self, make_session, make_character):
        """When a modifier expires, derived stats are recomputed."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            # Add and immediately expire a defense buff
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type, duration) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, "shield_spell", "bonus_defense", "buff", 4, "rounds", 1),
            )
            db.commit()

            # First, recompute with the buff active
            from rules_engine import rules_calc

            rules_calc(db, cid, TEST_SYSTEM)

            # Check defense with buff: 10 + dex_mod(2) + bonus_defense(4) = 16
            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'defense'",
                (cid,),
            ).fetchone()
            assert row[0] == "16"

            # Now end_turn expires it and recomputes
            output = end_turn(db, cid, TEST_SYSTEM)

            assert "EXPIRED: shield_spell" in output

            # Defense should be back to 12 (10 + 2 + 0)
            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'defense'",
                (cid,),
            ).fetchone()
            assert row[0] == "12"
        finally:
            db.close()


class TestNoModifiers:
    def test_no_modifiers(self, make_session, make_character):
        """End turn with no active modifiers."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            output = end_turn(db, cid, TEST_SYSTEM)

            assert "no active modifiers" in output
        finally:
            db.close()


class TestNoEndTurnConfig:
    def test_no_config_in_pack(self, make_session, make_character):
        """System pack without end_turn config returns informative message."""
        from _db import require_db
        from character import set_attr

        db = require_db()
        try:
            # Use a temporary system pack without end_turn
            import json
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                system = {
                    "meta": {"name": "No End Turn", "dice": "d20"},
                    "defaults": {"str": 10, "bonus_defense": 0},
                    "derived": {},
                }
                with open(os.path.join(tmpdir, "system.json"), "w") as f:
                    json.dump(system, f)

                sid = make_session()
                cid = make_character(sid, name="Test", level=1)

                output = end_turn(db, cid, tmpdir)
                assert "no end_turn config" in output
        finally:
            db.close()


# ===========================================================================
# start_turn tests
# ===========================================================================


class TestStartTurn:
    def test_removes_until_next_turn_modifiers(self, make_session, make_character):
        """start_turn removes modifiers with duration_type until_next_turn."""
        from _db import require_db
        from character import set_attr
        from combat_engine import start_turn

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'all_out', 'bonus_defense', 'debuff', -5, 'until_next_turn')",
                (cid,),
            )
            db.commit()

            output = start_turn(db, cid, TEST_SYSTEM)
            assert "EXPIRED" in output
            assert "all_out" in output

            rows = db.execute(
                "SELECT * FROM combat_state WHERE character_id = ? AND source = 'all_out'",
                (cid,),
            ).fetchall()
            assert len(rows) == 0
        finally:
            db.close()

    def test_skips_other_duration_types(self, make_session, make_character):
        """start_turn leaves rounds and encounter modifiers untouched."""
        from _db import require_db
        from character import set_attr
        from combat_engine import start_turn

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, duration_type, duration) "
                "VALUES (?, 'haste', 'bonus_defense', 'buff', 2, 'rounds', 3)",
                (cid,),
            )
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'terrain', 'bonus_defense', 'buff', 1, 'encounter')",
                (cid,),
            )
            db.commit()

            output = start_turn(db, cid, TEST_SYSTEM)
            assert output == ""

            rows = db.execute(
                "SELECT source FROM combat_state WHERE character_id = ?",
                (cid,),
            ).fetchall()
            assert len(rows) == 2
        finally:
            db.close()

    def test_no_config_returns_empty(self, make_session, make_character):
        """System pack without start_turn config returns empty string."""
        from _db import require_db
        from character import set_attr
        from combat_engine import start_turn

        db = require_db()
        try:
            import json
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                system = {
                    "meta": {"name": "No Start Turn", "dice": "d20"},
                    "defaults": {"str": 10, "bonus_defense": 0},
                    "derived": {},
                }
                with open(os.path.join(tmpdir, "system.json"), "w") as f:
                    json.dump(system, f)

                sid = make_session()
                cid = make_character(sid, name="Test", level=1)

                output = start_turn(db, cid, tmpdir)
                assert output == ""
        finally:
            db.close()

    def test_triggers_recompute(self, make_session, make_character):
        """Removing until_next_turn modifier triggers stat recompute."""
        from _db import require_db
        from character import set_attr
        from combat_engine import start_turn

        db = require_db()
        try:
            sid, cid = _setup_character(db, make_session, make_character, set_attr)

            # Get baseline defense
            from rules_engine import rules_calc

            rules_calc(db, cid, TEST_SYSTEM)
            base_def = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'defense'",
                (cid,),
            ).fetchone()[0]

            # Add a penalty modifier
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'penalty', 'bonus_defense', 'debuff', -5, 'until_next_turn')",
                (cid,),
            )
            db.commit()
            rules_calc(db, cid, TEST_SYSTEM)

            penalized_def = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'defense'",
                (cid,),
            ).fetchone()[0]
            assert int(penalized_def) < int(base_def)

            # start_turn should remove and recompute
            output = start_turn(db, cid, TEST_SYSTEM)
            assert "EXPIRED" in output

            restored_def = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'derived' AND key = 'defense'",
                (cid,),
            ).fetchone()[0]
            assert int(restored_def) == int(base_def)
        finally:
            db.close()
