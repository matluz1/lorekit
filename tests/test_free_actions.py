"""Tests for free action support and on_hit_actions follow-up.

Validates that:
- free_action option bypasses the action counter
- on_hit_actions auto-resolves follow-ups on hit when ability is present
- on_hit_actions is skipped on miss or missing ability
"""

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


# ===========================================================================
# free_action flag
# ===========================================================================


class TestFreeAction:
    def test_free_action_skips_counter(self, make_session, make_character):
        """resolve_action with free_action=True doesn't increment action counter."""
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_character(db, sid, make_character, "Attacker")
            dfn = _make_character(db, sid, make_character, "Defender", char_type="pc")

            # Make attacker dazed (damage_condition = 2 → dazed in mm3e)
            from lorekit.character import set_attr

            set_attr(db, atk, "stat", "damage_condition", "2")

            # First action: normal (uses the 1 allowed action)
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            # Second action: free_action=True should NOT be blocked
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(
                    db,
                    atk,
                    dfn,
                    "close_attack",
                    MM3E_SYSTEM,
                    options={"free_action": True},
                )
            assert "HIT" in result or "MISS" in result  # resolved, not blocked
        finally:
            db.close()

    def test_normal_action_still_blocked_when_dazed(self, make_session, make_character):
        """Without free_action, second action while dazed is blocked."""
        from lorekit.combat import resolve_action
        from lorekit.db import LoreKitError, require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_character(db, sid, make_character, "Attacker")
            dfn = _make_character(db, sid, make_character, "Defender", char_type="pc")

            from lorekit.character import set_attr

            set_attr(db, atk, "stat", "damage_condition", "2")

            # First action: uses the 1 allowed
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            # Second action: should be BLOCKED
            with pytest.raises(LoreKitError, match="BLOCKED.*dazed"):
                resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)
        finally:
            db.close()


# ===========================================================================
# on_hit_actions
# ===========================================================================


class TestOnHitActions:
    def test_on_hit_actions_triggers_grab(self, make_session, make_character):
        """close_attack with Fast Grab ability auto-resolves grab on hit."""
        from lorekit.character import set_ability
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_character(db, sid, make_character, "Grabber")
            dfn = _make_character(db, sid, make_character, "Target", char_type="pc")

            # Give attacker Fast Grab advantage
            set_ability(db, atk, "Fast Grab", "Free grab on melee hit", "advantage")

            # d20=15 → hit close_attack, d20=5 → resist fail, d20=15 → hit grab, d20=1 → grab resist fail
            roll_calls = iter([14, 4, 14, 0])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            assert "FREE ACTION (grab)" in result
            assert "HIT" in result

            # Verify grab modifier was applied
            row = db.execute(
                "SELECT source FROM combat_state WHERE character_id = ? AND source = 'grab'",
                (dfn,),
            ).fetchone()
            assert row is not None
        finally:
            db.close()

    def test_on_hit_actions_skipped_without_ability(self, make_session, make_character):
        """close_attack without Fast Grab does NOT trigger follow-up grab."""
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_character(db, sid, make_character, "Puncher")
            dfn = _make_character(db, sid, make_character, "Target", char_type="pc")

            # No Fast Grab ability
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            assert "FREE ACTION" not in result
        finally:
            db.close()

    def test_on_hit_actions_skipped_on_miss(self, make_session, make_character):
        """close_attack miss with Fast Grab does NOT trigger follow-up."""
        from lorekit.character import set_ability
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_character(db, sid, make_character, "Grabber")
            dfn = _make_character(db, sid, make_character, "Target", char_type="pc", agl="10", fgt="10")

            set_ability(db, atk, "Fast Grab", "Free grab on melee hit", "advantage")

            # d20=1 → very likely miss against high-defense target
            roll_calls = iter([0])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            assert "FREE ACTION" not in result
        finally:
            db.close()

    def test_free_grab_while_dazed(self, make_session, make_character):
        """Fast Grab follow-up works even when attacker is dazed."""
        from lorekit.character import set_ability, set_attr
        from lorekit.combat import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            atk = _make_character(db, sid, make_character, "Grabber")
            dfn = _make_character(db, sid, make_character, "Target", char_type="pc")

            set_ability(db, atk, "Fast Grab", "Free grab on melee hit", "advantage")
            set_attr(db, atk, "stat", "damage_condition", "2")  # dazed

            # Hit: d20=15, resist fail: d20=5, grab hit: d20=15, grab resist fail: d20=1
            roll_calls = iter([14, 4, 14, 0])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, atk, dfn, "close_attack", MM3E_SYSTEM)

            # Attack succeeded + free grab resolved (not blocked by dazed)
            assert "HIT" in result
            assert "FREE ACTION (grab)" in result
        finally:
            db.close()
