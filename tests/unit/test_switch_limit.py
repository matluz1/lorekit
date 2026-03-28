"""Tests for alternate switching limits during encounters."""

import json
import os

import pytest

from lorekit.combat.powers import _check_switch_limit, _increment_switches, switch_alternate
from lorekit.encounter import advance_turn, start_encounter

FIXTURES = os.path.join(os.path.dirname(__file__), "../fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


def _db():
    from lorekit.db import require_db

    return require_db()


def _make_array(db, character_id, array_name, alternates):
    """Insert abilities that form a power array for testing switches.

    alternates: list of (name, action_key) tuples.
    The first is treated as the primary (base).
    """
    import json as _json

    # Primary ability
    db.execute(
        "INSERT INTO character_abilities (character_id, name, category, uses, description) "
        "VALUES (?, ?, 'power', 'at_will', ?)",
        (
            character_id,
            array_name,
            _json.dumps(
                {
                    "desc": f"{array_name} primary",
                    "action": {"key": array_name.lower().replace(" ", "_")},
                }
            ),
        ),
    )

    for alt_name, action_key in alternates:
        db.execute(
            "INSERT INTO character_abilities (character_id, name, category, uses, description) "
            "VALUES (?, ?, 'power', 'at_will', ?)",
            (
                character_id,
                alt_name,
                _json.dumps(
                    {
                        "desc": f"{alt_name} alternate",
                        "array_of": array_name,
                        "action": {"key": action_key},
                    }
                ),
            ),
        )

    # Set initial active alternate to the primary
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) VALUES (?, 'active_alternate', ?, ?)",
        (character_id, array_name, array_name),
    )
    db.commit()


class TestSwitchLimitEnforcement:
    def test_no_limit_without_config(self, make_session, make_character):
        """Without alternate_switching config, switches are unlimited."""
        from cruncher.system_pack import load_system_pack
        from lorekit.character import set_attr
        from lorekit.rules import load_character_data

        db = _db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Hero", level=1)

            # Set up stats so rules_calc works
            for key, val in [("str", "10"), ("dex", "10"), ("con", "10")]:
                set_attr(db, cid, "stat", key, val)
            from lorekit.rules import rules_calc

            rules_calc(db, cid, TEST_SYSTEM)

            pack = load_system_pack(TEST_SYSTEM)
            char = load_character_data(db, cid)

            # No encounter active, no config → should not raise
            _check_switch_limit(db, char, pack)
        finally:
            db.close()

    def test_limit_blocks_excess_switches(self, make_session, make_character):
        """During an encounter with max_per_turn=1, second switch is blocked."""
        from cruncher.system_pack import load_system_pack
        from lorekit.character import set_attr
        from lorekit.rules import load_character_data

        db = _db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Hero", level=1)
            other = make_character(sid, name="Foe", level=1)

            for key, val in [("str", "10"), ("dex", "10"), ("con", "10")]:
                set_attr(db, cid, "stat", key, val)
                set_attr(db, other, "stat", key, val)

            from lorekit.rules import rules_calc

            rules_calc(db, cid, TEST_SYSTEM)
            rules_calc(db, other, TEST_SYSTEM)

            # Start encounter
            zones = [{"name": "Arena"}]
            init = [
                {"character_id": cid, "roll": 20},
                {"character_id": other, "roll": 10},
            ]
            placements = [
                {"character_id": cid, "zone": "Arena"},
                {"character_id": other, "zone": "Arena"},
            ]
            start_encounter(db, sid, zones, init, placements=placements)

            # Simulate switch counter at 1
            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'internal', '_switches_this_turn', '1')",
                (cid,),
            )
            db.commit()

            # Load a pack with max_per_turn = 1
            pack = load_system_pack(TEST_SYSTEM)
            # Patch the pack's combat config to add switching limit
            if not pack.combat:
                pack.combat = {}
            pack.combat["alternate_switching"] = {"max_per_turn": 1, "action_cost": "free"}

            char = load_character_data(db, cid)

            from lorekit.db import LoreKitError

            with pytest.raises(LoreKitError, match="BLOCKED"):
                _check_switch_limit(db, char, pack)
        finally:
            db.close()

    def test_switches_reset_on_advance_turn(self, make_session, make_character):
        """Advancing turns resets the per-turn switch counter."""
        from lorekit.character import set_attr

        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Alpha", level=1)
            c2 = make_character(sid, name="Bravo", level=1)

            for cid in (c1, c2):
                for key, val in [("str", "10"), ("dex", "10"), ("con", "10")]:
                    set_attr(db, cid, "stat", key, val)

            # Start encounter
            zones = [{"name": "Arena"}]
            init = [
                {"character_id": c1, "roll": 20},
                {"character_id": c2, "roll": 10},
            ]
            placements = [
                {"character_id": c1, "zone": "Arena"},
                {"character_id": c2, "zone": "Arena"},
            ]
            start_encounter(db, sid, zones, init, placements=placements)

            # Set switch counter for Alpha
            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'internal', '_switches_this_turn', '2')",
                (c1,),
            )
            db.commit()

            # Advance turn (Alpha -> Bravo), should reset Alpha's counter
            advance_turn(db, sid)

            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_switches_this_turn'",
                (c1,),
            ).fetchone()
            assert row is None
        finally:
            db.close()

    def test_increment_switches_during_encounter(self, make_session, make_character):
        """_increment_switches increments the counter when encounter is active."""
        from lorekit.character import set_attr
        from lorekit.rules import load_character_data as _load_cd

        db = _db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Hero", level=1)
            other = make_character(sid, name="Foe", level=1)

            for c in (cid, other):
                for key, val in [("str", "10"), ("dex", "10"), ("con", "10")]:
                    set_attr(db, c, "stat", key, val)

            zones = [{"name": "Arena"}]
            init = [
                {"character_id": cid, "roll": 20},
                {"character_id": other, "roll": 10},
            ]
            placements = [
                {"character_id": cid, "zone": "Arena"},
                {"character_id": other, "zone": "Arena"},
            ]
            start_encounter(db, sid, zones, init, placements=placements)

            char = _load_cd(db, cid)

            _increment_switches(db, char)

            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_switches_this_turn'",
                (cid,),
            ).fetchone()
            assert row is not None
            assert row[0] == "1"

            # Increment again
            _increment_switches(db, char)
            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_switches_this_turn'",
                (cid,),
            ).fetchone()
            assert row[0] == "2"
        finally:
            db.close()

    def test_bypass_limit_skips_check(self, make_session, make_character):
        """switch_alternate with _bypass_limit=True ignores the limit."""
        from lorekit.character import set_attr
        from lorekit.rules import rules_calc

        db = _db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Hero", level=1)
            other = make_character(sid, name="Foe", level=1)

            for c in (cid, other):
                for key, val in [("str", "10"), ("dex", "10"), ("con", "10")]:
                    set_attr(db, c, "stat", key, val)
                rules_calc(db, c, TEST_SYSTEM)

            _make_array(db, cid, "Blast", [("Fire Blast", "fire_blast")])

            zones = [{"name": "Arena"}]
            init = [
                {"character_id": cid, "roll": 20},
                {"character_id": other, "roll": 10},
            ]
            placements = [
                {"character_id": cid, "zone": "Arena"},
                {"character_id": other, "zone": "Arena"},
            ]
            start_encounter(db, sid, zones, init, placements=placements)

            # Exhaust switch counter
            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'internal', '_switches_this_turn', '99')",
                (cid,),
            )
            db.commit()

            # _bypass_limit should succeed even with counter exhausted
            result = switch_alternate(db, cid, "Blast", "Fire Blast", TEST_SYSTEM, _bypass_limit=True)
            assert "SWITCH ALTERNATE" in result
        finally:
            db.close()
