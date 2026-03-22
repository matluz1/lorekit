"""GM-assisted effect tests — gm_hints fallback in resolve_action."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

MM3E_SYSTEM = os.path.join(os.path.dirname(__file__), "..", "systems", "mm3e")


def _make_character(db, session_id, make_character, name, char_type="npc", **stats):
    from character import set_attr
    from rules_engine import rules_calc

    cid = make_character(session_id, name=name, char_type=char_type)
    for key, val in {
        "fgt": "6",
        "agl": "2",
        "dex": "2",
        "str": "4",
        "sta": "4",
        "int": "0",
        "awe": "2",
        "pre": "2",
        **stats,
    }.items():
        set_attr(db, cid, "stat", key, str(val))
    rules_calc(db, cid, MM3E_SYSTEM)
    return cid


class TestGmHints:
    def test_gm_assisted_effect_returns_hints(self, make_session, make_character):
        """Calling resolve_action with a gm_assisted effect returns hints instead of error."""
        from _db import require_db
        from combat_engine import resolve_action

        db = require_db()
        try:
            sid = make_session()
            a = _make_character(db, sid, make_character, "Caster")
            b = _make_character(db, sid, make_character, "Target", char_type="pc")

            result = resolve_action(db, a, b, "illusion", MM3E_SYSTEM)

            assert "GM-ASSISTED EFFECT" in result
            assert "Illusion" in result
            assert "sustained" in result.lower()
        finally:
            db.close()

    def test_gm_hints_include_check_info(self, make_session, make_character):
        """Illusion gm_hints should include check type and DC formula."""
        from _db import require_db
        from combat_engine import resolve_action

        db = require_db()
        try:
            sid = make_session()
            a = _make_character(db, sid, make_character, "Caster")
            b = _make_character(db, sid, make_character, "Target", char_type="pc")

            result = resolve_action(db, a, b, "illusion", MM3E_SYSTEM)

            assert "Insight" in result
            assert "rank + 10" in result
        finally:
            db.close()

    def test_unknown_action_still_errors(self, make_session, make_character):
        """A truly unknown action (not in actions or effects) should still error."""
        from _db import LoreKitError, require_db
        from combat_engine import resolve_action

        db = require_db()
        try:
            sid = make_session()
            a = _make_character(db, sid, make_character, "Caster")
            b = _make_character(db, sid, make_character, "Target", char_type="pc")

            with pytest.raises(LoreKitError, match="Unknown action"):
                resolve_action(db, a, b, "totally_fake_action", MM3E_SYSTEM)
        finally:
            db.close()

    def test_non_gm_assisted_effect_still_errors(self, make_session, make_character):
        """An engine-resolved effect used as action name should error (not return hints)."""
        from _db import LoreKitError, require_db
        from combat_engine import resolve_action

        db = require_db()
        try:
            sid = make_session()
            a = _make_character(db, sid, make_character, "Caster")
            b = _make_character(db, sid, make_character, "Target", char_type="pc")

            # "damage" is attack_vs_defense, not gm_assisted — should not return hints
            with pytest.raises(LoreKitError, match="Unknown action"):
                resolve_action(db, a, b, "damage", MM3E_SYSTEM)
        finally:
            db.close()
