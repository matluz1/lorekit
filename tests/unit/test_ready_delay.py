"""Tests for ready and delay action support in encounters."""

import json
import os

import pytest

from lorekit.encounter import (
    advance_turn,
    delay_turn,
    end_encounter,
    execute_ready,
    get_status,
    ready_action,
    start_encounter,
    undelay,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "../fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


def _db():
    from lorekit.db import require_db

    return require_db()


def _start_3char_encounter(db, make_session, make_character):
    """Helper: 3-character encounter (A, B, C) in Arena zone, A goes first."""
    sid = make_session()
    c1 = make_character(sid, name="Alpha")
    c2 = make_character(sid, name="Bravo")
    c3 = make_character(sid, name="Charlie")

    zones = [{"name": "Arena"}]
    initiative = [
        {"character_id": c1, "roll": 30},
        {"character_id": c2, "roll": 20},
        {"character_id": c3, "roll": 10},
    ]
    placements = [
        {"character_id": c1, "zone": "Arena"},
        {"character_id": c2, "zone": "Arena"},
        {"character_id": c3, "zone": "Arena"},
    ]

    start_encounter(db, sid, zones, initiative, placements=placements)
    return sid, c1, c2, c3


class TestReadyAction:
    def test_ready_stores_and_advances(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            result = ready_action(db, sid, c1, "melee_attack", "when Bravo moves", targets="Bravo")
            assert "READY" in result
            assert "melee_attack" in result
            assert "when Bravo moves" in result

            # Verify combat_state row created
            row = db.execute(
                "SELECT metadata FROM combat_state WHERE character_id = ? AND duration_type = 'readied'",
                (c1,),
            ).fetchone()
            assert row is not None
            meta = json.loads(row[0])
            assert meta["action"] == "melee_attack"
            assert meta["trigger"] == "when Bravo moves"
            assert meta["targets"] == "Bravo"
        finally:
            db.close()

    def test_ready_wrong_turn_raises(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            from lorekit.db import LoreKitError

            with pytest.raises(LoreKitError, match="Not this character's turn"):
                ready_action(db, sid, c2, "melee_attack", "when Alpha moves")
        finally:
            db.close()

    def test_execute_ready_resolves_and_consumes(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            # Alpha readies (no target — GM resolves manually)
            ready_action(db, sid, c1, "melee_attack", "when Bravo moves")

            # Advance to Bravo's turn
            advance_turn(db, sid)

            # Execute Alpha's readied action (no pack_dir → manual resolution)
            result = execute_ready(db, sid, c1)
            assert "READIED ACTION" in result
            assert "melee_attack" in result

            # Readied row should be consumed
            row = db.execute(
                "SELECT id FROM combat_state WHERE character_id = ? AND duration_type = 'readied'",
                (c1,),
            ).fetchone()
            assert row is None
        finally:
            db.close()

    def test_execute_ready_no_action_raises(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            from lorekit.db import LoreKitError

            with pytest.raises(LoreKitError, match="no readied action"):
                execute_ready(db, sid, c1)
        finally:
            db.close()


class TestDelayTurn:
    def test_delay_removes_from_initiative(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            result = delay_turn(db, sid, c1)
            assert "DELAY" in result
            assert "Alpha" in result
            # Bravo should be next
            assert "Bravo" in result

            # Alpha should be marked delayed
            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_delayed'",
                (c1,),
            ).fetchone()
            assert row is not None
            assert row[0] == "1"

            # Initiative should only have Bravo and Charlie
            enc = db.execute(
                "SELECT initiative_order FROM encounter_state WHERE session_id = ? AND status = 'active'",
                (sid,),
            ).fetchone()
            init_order = json.loads(enc[0])
            assert c1 not in init_order
            assert c2 in init_order
            assert c3 in init_order
        finally:
            db.close()

    def test_delay_wrong_turn_raises(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            from lorekit.db import LoreKitError

            with pytest.raises(LoreKitError, match="Not this character's turn"):
                delay_turn(db, sid, c2)
        finally:
            db.close()

    def test_delay_shown_in_status(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            delay_turn(db, sid, c1)
            status = get_status(db, sid)
            assert "Delayed" in status
            assert "Alpha" in status
        finally:
            db.close()


class TestUndelay:
    def test_undelay_inserts_before_current(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            # Alpha delays
            delay_turn(db, sid, c1)

            # Now Bravo's turn. Undelay Alpha (inserts before Bravo).
            result = undelay(db, sid, c1)
            assert "UNDELAY" in result
            assert "Alpha" in result

            # Alpha should no longer be marked delayed
            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_delayed'",
                (c1,),
            ).fetchone()
            assert row is None

            # Alpha should be back in initiative
            enc = db.execute(
                "SELECT initiative_order, current_turn FROM encounter_state WHERE session_id = ? AND status = 'active'",
                (sid,),
            ).fetchone()
            init_order = json.loads(enc[0])
            assert c1 in init_order
            # Alpha should be at current_turn position
            assert init_order[enc[1]] == c1
        finally:
            db.close()

    def test_undelay_not_delayed_raises(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            from lorekit.db import LoreKitError

            with pytest.raises(LoreKitError, match="not delaying"):
                undelay(db, sid, c1)
        finally:
            db.close()

    def test_delay_last_wraps_round(self, make_session, make_character):
        """Delaying the last character in initiative wraps to next round."""
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            # Advance to Charlie (last in order)
            advance_turn(db, sid)  # Alpha -> Bravo
            advance_turn(db, sid)  # Bravo -> Charlie

            result = delay_turn(db, sid, c3)
            assert "DELAY" in result

            # Should wrap to next round with Alpha
            enc = db.execute(
                "SELECT round FROM encounter_state WHERE session_id = ? AND status = 'active'",
                (sid,),
            ).fetchone()
            # Round should have incremented since Charlie was last
            assert enc[0] >= 2
        finally:
            db.close()


class TestEndEncounterCleansDelayed:
    def test_end_clears_delayed_and_reaction_policy(self, make_session, make_character):
        db = _db()
        try:
            sid, c1, c2, c3 = _start_3char_encounter(db, make_session, make_character)

            # Delay Alpha
            delay_turn(db, sid, c1)

            # Set a reaction policy
            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'reaction_policy', 'Deflect', 'inactive')",
                (c2,),
            )
            db.commit()

            end_encounter(db, sid)

            # Delayed marker should be cleaned up
            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_delayed'",
                (c1,),
            ).fetchone()
            assert row is None

            # Reaction policy should be cleaned up
            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'reaction_policy'",
                (c2,),
            ).fetchone()
            assert row is None
        finally:
            db.close()
