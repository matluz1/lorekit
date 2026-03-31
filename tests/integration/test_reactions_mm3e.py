"""MM3e reaction integration tests — Interpose, Deflect, Weapon Bind with composable effects."""

import json
import os
from unittest.mock import patch

import cruncher_mm3e
import pytest

from lorekit.character import set_attr
from lorekit.combat.resolve import resolve_action
from lorekit.db import require_db
from lorekit.encounter import start_encounter
from lorekit.rules import rules_calc

MM3E_SYSTEM = cruncher_mm3e.pack_path()


def _mm3e_combat_cfg():
    with open(os.path.join(MM3E_SYSTEM, "system.json")) as f:
        return json.load(f)["combat"]


def _make_mm3e_char(db, session_id, make_character, name, char_type="npc", **overrides):
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
    defaults.update(overrides)
    for key, val in defaults.items():
        set_attr(db, cid, "stat", key, str(val))
    rules_calc(db, cid, MM3E_SYSTEM)
    return cid


def _add_weapon_bind(db, char_id, policy="active"):
    db.execute(
        "INSERT INTO combat_state "
        "(character_id, source, target_stat, modifier_type, value, "
        "duration_type, duration, metadata) "
        "VALUES (?, ?, '_reaction', 'reaction', 0, 'reaction', 1, ?)",
        (
            char_id,
            "weapon_bind",
            json.dumps(
                {
                    "hook": "after_hit",
                    "reaction_key": "counter_attack",
                    "effects": [{"type": "counter_attack", "action": "close_attack"}],
                }
            ),
        ),
    )
    if policy != "active":
        set_attr(db, char_id, "reaction_policy", "weapon_bind", policy)
    db.commit()


class TestWeaponBind:
    def test_weapon_bind_counter_on_hit(self, make_session, make_character):
        """Weapon Bind: counter-attack after being hit."""
        db = require_db()
        try:
            sid = make_session()
            cfg = _mm3e_combat_cfg()
            villain = _make_mm3e_char(db, sid, make_character, "Villain")
            hero = _make_mm3e_char(db, sid, make_character, "Hero", char_type="pc")
            _add_weapon_bind(db, hero, policy="active")

            start_encounter(
                db,
                sid,
                [{"name": "Arena"}],
                [{"character_id": villain, "roll": 20}, {"character_id": hero, "roll": 10}],
                placements=[
                    {"character_id": villain, "zone": "Arena"},
                    {"character_id": hero, "zone": "Arena"},
                ],
                combat_cfg=cfg,
            )

            # Main attack hits, hero counter-attacks
            roll_calls = iter([14, 9, 14, 9])  # main atk, main resist, counter atk, counter resist
            with patch("secrets.randbelow", side_effect=roll_calls):
                output = resolve_action(db, villain, hero, "close_attack", MM3E_SYSTEM)

            assert "HIT!" in output
            assert "REACTION [weapon_bind]" in output
            assert "counter-attacks" in output
        finally:
            db.close()


class TestCrossCutting:
    def test_confirm_invalid_pending_id_raises(self, make_session):
        """Confirming a nonexistent pending ID raises an error."""
        from lorekit.combat.pending import confirm_pending
        from lorekit.db import LoreKitError

        db = require_db()
        try:
            with pytest.raises(LoreKitError, match="No pending resolution"):
                confirm_pending(db, 99999, reactions=[])
        finally:
            db.close()

    def test_new_pending_replaces_old(self, make_session, make_character):
        """A new pending resolution replaces any existing one for the session."""
        from lorekit.combat.pending import store_pending

        db = require_db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Char1")
            c2 = make_character(sid, name="Char2")
            id1 = store_pending(db, sid, c1, c2, "test", "/fake", {"total_damage": 10, "lines": []}, [])
            id2 = store_pending(db, sid, c1, c2, "test", "/fake", {"total_damage": 20, "lines": []}, [])

            assert db.execute("SELECT id FROM pending_resolutions WHERE id = ?", (id1,)).fetchone() is None
            assert db.execute("SELECT id FROM pending_resolutions WHERE id = ?", (id2,)).fetchone() is not None
        finally:
            db.close()
