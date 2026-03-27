"""Sustained power tests — condition cancellation and sustain warnings."""

import json
import os
from unittest.mock import patch

import cruncher_mm3e
import pytest

MM3E_SYSTEM = cruncher_mm3e.pack_path()


def _combat_cfg():
    with open(os.path.join(MM3E_SYSTEM, "system.json")) as f:
        return json.load(f)["combat"]


def _make_character(db, session_id, make_character, name, char_type="npc", **stats):
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
    rules_calc(db, cid, MM3E_SYSTEM)
    return cid


def _start_encounter(db, session_id, characters, zones, placements):
    from lorekit.encounter import start_encounter

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
# 3.1 — Condition-based cancellation
# ===========================================================================


class TestConditionCancellation:
    def test_stunned_cancels_sustained_modifiers(self, make_session, make_character):
        """When stunned activates, sustained modifiers should be removed."""
        from lorekit.combat.conditions import sync_condition_modifiers
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(db, sid, [cid], [{"name": "Arena"}], [(cid, "Arena")])

            # Add a sustained modifier (e.g. Force Field → protection)
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'force_field', 'bonus_toughness', 'power', 8, 'sustained')",
                (cid,),
            )
            db.commit()

            # Verify it's there
            count = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'force_field'",
                (cid,),
            ).fetchone()[0]
            assert count == 1

            # Now apply stunned condition (insert source = "stunned" marker)
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'stunned', 'bonus_dodge', 'condition', 0, 'rounds')",
                (cid,),
            )
            db.commit()

            # Sync conditions — should detect stunned and cancel sustained modifiers
            condition_rules = cfg.get("condition_rules", {})
            combined = cfg.get("combined_conditions", {})
            changed = sync_condition_modifiers(db, cid, condition_rules, combined)
            assert changed is True

            # Force field should be gone
            remaining = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'force_field'",
                (cid,),
            ).fetchone()[0]
            assert remaining == 0
        finally:
            db.close()

    def test_stunned_does_not_cancel_non_sustained(self, make_session, make_character):
        """Stunned should not remove modifiers with other duration types (e.g. rounds)."""
        from lorekit.combat.conditions import sync_condition_modifiers
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(db, sid, [cid], [{"name": "Arena"}], [(cid, "Arena")])

            # Add a rounds-based modifier (should survive stunned)
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type, duration) "
                "VALUES (?, 'buff', 'bonus_dodge', 'circumstance', 2, 'rounds', 3)",
                (cid,),
            )
            # Add stunned
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'stunned', 'bonus_dodge', 'condition', 0, 'rounds')",
                (cid,),
            )
            db.commit()

            condition_rules = cfg.get("condition_rules", {})
            combined = cfg.get("combined_conditions", {})
            sync_condition_modifiers(db, cid, condition_rules, combined)

            # Rounds-based buff should still be there
            remaining = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'buff'",
                (cid,),
            ).fetchone()[0]
            assert remaining == 1
        finally:
            db.close()

    def test_no_cancellation_without_stunned(self, make_session, make_character):
        """Without a cancelling condition, sustained modifiers should persist."""
        from lorekit.combat.conditions import sync_condition_modifiers
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_character(db, sid, make_character, "Hero", char_type="pc")
            cfg = _combat_cfg()

            _start_encounter(db, sid, [cid], [{"name": "Arena"}], [(cid, "Arena")])

            # Add sustained modifier
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'force_field', 'bonus_toughness', 'power', 8, 'sustained')",
                (cid,),
            )
            db.commit()

            condition_rules = cfg.get("condition_rules", {})
            combined = cfg.get("combined_conditions", {})
            sync_condition_modifiers(db, cid, condition_rules, combined)

            # Should still be present
            remaining = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'force_field'",
                (cid,),
            ).fetchone()[0]
            assert remaining == 1
        finally:
            db.close()


# ===========================================================================
# 3.2 — Sustain warning on start-of-turn
# ===========================================================================


class TestSustainWarning:
    def test_sustained_modifier_emits_warning(self, make_session, make_character):
        """start_turn should warn about sustained modifiers."""
        from lorekit.combat.turns import start_turn
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_character(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(db, sid, [cid], [{"name": "Arena"}], [(cid, "Arena")])

            # Add sustained modifier
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'force_field', 'bonus_toughness', 'power', 8, 'sustained')",
                (cid,),
            )
            db.commit()

            result = start_turn(db, cid, MM3E_SYSTEM)

            assert "SUSTAINED" in result
            assert "force_field" in result
            assert "free action" in result.lower()
        finally:
            db.close()

    def test_no_warning_without_sustained(self, make_session, make_character):
        """start_turn should not warn when there are no sustained modifiers."""
        from lorekit.combat.turns import start_turn
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_character(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(db, sid, [cid], [{"name": "Arena"}], [(cid, "Arena")])

            result = start_turn(db, cid, MM3E_SYSTEM)
            assert result == ""
        finally:
            db.close()

    def test_warning_and_removal_coexist(self, make_session, make_character):
        """Both warn (sustained) and remove (until_next_turn) should work in same start_turn."""
        from lorekit.combat.turns import start_turn
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            cid = _make_character(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(db, sid, [cid], [{"name": "Arena"}], [(cid, "Arena")])

            # Sustained modifier
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'force_field', 'bonus_toughness', 'power', 8, 'sustained')",
                (cid,),
            )
            # until_next_turn modifier (should be removed)
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, modifier_type, value, duration_type) "
                "VALUES (?, 'all_out_attack', 'bonus_dodge', 'debuff', -3, 'until_next_turn')",
                (cid,),
            )
            db.commit()

            result = start_turn(db, cid, MM3E_SYSTEM)

            # Should have both warning and removal
            assert "SUSTAINED" in result
            assert "EXPIRED" in result
            assert "all_out_attack" in result

            # until_next_turn should be removed, sustained should stay
            sustained_count = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'force_field'",
                (cid,),
            ).fetchone()[0]
            assert sustained_count == 1

            removed_count = db.execute(
                "SELECT COUNT(*) FROM combat_state WHERE character_id = ? AND source = 'all_out_attack'",
                (cid,),
            ).fetchone()[0]
            assert removed_count == 0
        finally:
            db.close()
