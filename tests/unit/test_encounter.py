"""Tests for the zone-based combat positioning system."""

import json
import os

import pytest

from lorekit.encounter import (
    _build_adjacency,
    _shortest_path,
    advance_turn,
    check_range,
    end_encounter,
    get_status,
    move_character,
    start_encounter,
    update_zone_tags,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "../fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")

COMBAT_CFG = {
    "zone_scale": 30,
    "movement_unit": "ft",
    "melee_range": 0,
    "zone_tags": {
        "difficult_terrain": {"movement_multiplier": 2},
        "cover": {"target_stat": "bonus_defense", "value": 2, "modifier_type": "environment"},
        "elevated": {"target_stat": "bonus_ranged_attack", "value": 1, "modifier_type": "environment"},
    },
}


def _db():
    from lorekit.db import require_db

    return require_db()


class TestStartEncounter:
    def test_basic_start(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Valeros")
            c2 = make_character(sid, name="Goblin")

            zones = [{"name": "Entrance"}, {"name": "Hall"}, {"name": "Alcove"}]
            initiative = [
                {"character_id": c1, "roll": 22},
                {"character_id": c2, "roll": 18},
            ]
            placements = [
                {"character_id": c1, "zone": "Entrance"},
                {"character_id": c2, "zone": "Alcove"},
            ]

            result = start_encounter(db, sid, zones, initiative, placements=placements)

            assert "ENCOUNTER STARTED" in result
            assert "Round: 1" in result
            assert "Valeros (22)" in result
            assert "Goblin (18)" in result
            assert "Valeros → Entrance" in result
            assert "Goblin → Alcove" in result

            # Verify DB state
            enc = db.execute(
                "SELECT id, status, round FROM encounter_state WHERE session_id = ?",
                (sid,),
            ).fetchone()
            assert enc is not None
            assert enc[1] == "active"
            assert enc[2] == 1

            # Verify zones created
            zone_count = db.execute(
                "SELECT COUNT(*) FROM encounter_zones WHERE encounter_id = ?",
                (enc[0],),
            ).fetchone()[0]
            assert zone_count == 3

            # Verify linear adjacency
            adj_count = db.execute(
                "SELECT COUNT(*) FROM zone_adjacency za "
                "JOIN encounter_zones ez ON za.zone_a = ez.id "
                "WHERE ez.encounter_id = ?",
                (enc[0],),
            ).fetchone()[0]
            assert adj_count == 2  # Entrance↔Hall, Hall↔Alcove
        finally:
            db.close()

    def test_custom_adjacency(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="A")

            zones = [{"name": "X"}, {"name": "Y"}, {"name": "Z"}]
            initiative = [{"character_id": c1, "roll": 10}]
            adjacency = [
                {"from": "X", "to": "Y", "weight": 1},
                {"from": "Y", "to": "Z", "weight": 1},
                {"from": "X", "to": "Z", "weight": 2},
            ]

            result = start_encounter(db, sid, zones, initiative, adjacency=adjacency)
            assert "ENCOUNTER STARTED" in result

            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            adj_count = db.execute(
                "SELECT COUNT(*) FROM zone_adjacency za "
                "JOIN encounter_zones ez ON za.zone_a = ez.id "
                "WHERE ez.encounter_id = ?",
                (enc_id,),
            ).fetchone()[0]
            assert adj_count == 3
        finally:
            db.close()

    def test_duplicate_encounter_raises(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="A")
            zones = [{"name": "Z"}]
            initiative = [{"character_id": c1, "roll": 10}]

            start_encounter(db, sid, zones, initiative)

            from lorekit.db import LoreKitError

            with pytest.raises(LoreKitError, match="already active"):
                start_encounter(db, sid, zones, initiative)
        finally:
            db.close()

    def test_terrain_modifiers_on_placement(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Archer")

            zones = [{"name": "Tower", "tags": ["elevated", "cover"]}]
            initiative = [{"character_id": c1, "roll": 15}]
            placements = [{"character_id": c1, "zone": "Tower"}]

            result = start_encounter(
                db,
                sid,
                zones,
                initiative,
                placements=placements,
                combat_cfg=COMBAT_CFG,
            )

            assert "Terrain" in result

            # Check combat_state has terrain modifiers
            mods = db.execute(
                "SELECT source, target_stat, value FROM combat_state WHERE character_id = ? ORDER BY source",
                (c1,),
            ).fetchall()
            sources = {m[0] for m in mods}
            assert "zone:Tower:cover" in sources
            assert "zone:Tower:elevated" in sources
        finally:
            db.close()


class TestZoneGraph:
    def test_shortest_path_linear(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="A")
            zones = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
            init = [{"character_id": c1, "roll": 10}]

            start_encounter(db, sid, zones, init)
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            adj = _build_adjacency(db, enc_id)
            zone_a = db.execute(
                "SELECT id FROM encounter_zones WHERE encounter_id = ? AND name = 'A'",
                (enc_id,),
            ).fetchone()[0]
            zone_c = db.execute(
                "SELECT id FROM encounter_zones WHERE encounter_id = ? AND name = 'C'",
                (enc_id,),
            ).fetchone()[0]

            dist = _shortest_path(adj, zone_a, zone_c)
            assert dist == 2
        finally:
            db.close()

    def test_shortest_path_shortcut(self, make_session, make_character):
        """Direct edge is shorter than going through middle."""
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="A")
            zones = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
            init = [{"character_id": c1, "roll": 10}]
            adjacency = [
                {"from": "A", "to": "B", "weight": 1},
                {"from": "B", "to": "C", "weight": 1},
                {"from": "A", "to": "C", "weight": 1},  # shortcut
            ]

            start_encounter(db, sid, zones, init, adjacency=adjacency)
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            adj = _build_adjacency(db, enc_id)
            zone_a = db.execute(
                "SELECT id FROM encounter_zones WHERE encounter_id = ? AND name = 'A'",
                (enc_id,),
            ).fetchone()[0]
            zone_c = db.execute(
                "SELECT id FROM encounter_zones WHERE encounter_id = ? AND name = 'C'",
                (enc_id,),
            ).fetchone()[0]

            assert _shortest_path(adj, zone_a, zone_c) == 1
        finally:
            db.close()

    def test_same_zone_distance_zero(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="A")
            zones = [{"name": "Room"}]
            init = [{"character_id": c1, "roll": 10}]

            start_encounter(db, sid, zones, init)
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            adj = _build_adjacency(db, enc_id)
            zone_id = db.execute(
                "SELECT id FROM encounter_zones WHERE encounter_id = ?",
                (enc_id,),
            ).fetchone()[0]

            assert _shortest_path(adj, zone_id, zone_id) == 0
        finally:
            db.close()


class TestMovement:
    def test_basic_move(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Valeros")

            zones = [{"name": "A"}, {"name": "B"}]
            init = [{"character_id": c1, "roll": 10}]
            placements = [{"character_id": c1, "zone": "A"}]

            start_encounter(db, sid, zones, init, placements=placements)
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            result = move_character(db, enc_id, c1, "B")
            assert "MOVED" in result
            assert "Valeros → B" in result

            # Verify DB
            zone_b_id = db.execute(
                "SELECT id FROM encounter_zones WHERE encounter_id = ? AND name = 'B'",
                (enc_id,),
            ).fetchone()[0]
            actual = db.execute(
                "SELECT zone_id FROM character_zone WHERE encounter_id = ? AND character_id = ?",
                (enc_id, c1),
            ).fetchone()[0]
            assert actual == zone_b_id
        finally:
            db.close()

    def test_move_exceeds_budget(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Slow")

            zones = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
            init = [{"character_id": c1, "roll": 10}]
            placements = [{"character_id": c1, "zone": "A"}]

            start_encounter(db, sid, zones, init, placements=placements)
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            from lorekit.db import LoreKitError

            with pytest.raises(LoreKitError, match="Cannot reach"):
                move_character(db, enc_id, c1, "C", movement_budget=1)
        finally:
            db.close()

    def test_move_with_difficult_terrain(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Fighter")

            zones = [
                {"name": "Clear"},
                {"name": "Swamp", "tags": ["difficult_terrain"]},
            ]
            init = [{"character_id": c1, "roll": 10}]
            placements = [{"character_id": c1, "zone": "Clear"}]

            start_encounter(
                db,
                sid,
                zones,
                init,
                placements=placements,
                combat_cfg=COMBAT_CFG,
            )
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            # Difficult terrain doubles cost: 1 zone * 2 = 2
            from lorekit.db import LoreKitError

            with pytest.raises(LoreKitError, match="Cannot reach"):
                move_character(
                    db,
                    enc_id,
                    c1,
                    "Swamp",
                    combat_cfg=COMBAT_CFG,
                    movement_budget=1,
                )

            # Budget 2 should work
            result = move_character(
                db,
                enc_id,
                c1,
                "Swamp",
                combat_cfg=COMBAT_CFG,
                movement_budget=2,
            )
            assert "MOVED" in result
        finally:
            db.close()

    def test_move_swaps_terrain_modifiers(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Fighter")

            zones = [
                {"name": "Open"},
                {"name": "Pillars", "tags": ["cover"]},
            ]
            init = [{"character_id": c1, "roll": 10}]
            placements = [{"character_id": c1, "zone": "Open"}]

            start_encounter(
                db,
                sid,
                zones,
                init,
                placements=placements,
                combat_cfg=COMBAT_CFG,
            )
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            # No terrain mods in Open
            mods = db.execute("SELECT COUNT(*) FROM combat_state WHERE character_id = ?", (c1,)).fetchone()[0]
            assert mods == 0

            # Move to Pillars → gain cover
            move_character(db, enc_id, c1, "Pillars", combat_cfg=COMBAT_CFG)

            mods = db.execute(
                "SELECT source, target_stat, value FROM combat_state WHERE character_id = ?",
                (c1,),
            ).fetchall()
            assert len(mods) == 1
            assert mods[0][0] == "zone:Pillars:cover"
            assert mods[0][1] == "bonus_defense"
            assert mods[0][2] == 2

            # Move back to Open → lose cover
            move_character(db, enc_id, c1, "Open", combat_cfg=COMBAT_CFG)

            mods = db.execute("SELECT COUNT(*) FROM combat_state WHERE character_id = ?", (c1,)).fetchone()[0]
            assert mods == 0
        finally:
            db.close()


class TestAdvanceTurn:
    def test_advance_wraps_round(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="First")
            c2 = make_character(sid, name="Second")

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

            # Initial: turn 0 = First
            result = advance_turn(db, sid)
            assert "Round 1" in result
            assert "Second" in result

            # Advance past end → round 2
            result = advance_turn(db, sid)
            assert "Round 2" in result
            assert "First" in result
        finally:
            db.close()


class TestEncounterStatus:
    def test_status_shows_positions_and_distances(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Valeros")
            c2 = make_character(sid, name="Goblin")

            zones = [{"name": "Gate"}, {"name": "Bridge"}, {"name": "Tower"}]
            init = [
                {"character_id": c1, "roll": 22},
                {"character_id": c2, "roll": 18},
            ]
            placements = [
                {"character_id": c1, "zone": "Gate"},
                {"character_id": c2, "zone": "Tower"},
            ]

            start_encounter(
                db,
                sid,
                zones,
                init,
                placements=placements,
                combat_cfg=COMBAT_CFG,
            )

            result = get_status(db, sid, combat_cfg=COMBAT_CFG)

            assert "Round 1" in result
            assert "Turn: Valeros" in result
            assert "Gate" in result
            assert "Valeros" in result
            assert "Tower" in result
            assert "Goblin" in result
            assert "1 zone(s) (30ft)" in result  # adjacent zones
        finally:
            db.close()


class TestEndEncounter:
    def test_end_cleans_up(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Fighter")

            zones = [{"name": "Room", "tags": ["cover"]}]
            init = [{"character_id": c1, "roll": 15}]
            placements = [{"character_id": c1, "zone": "Room"}]

            start_encounter(
                db,
                sid,
                zones,
                init,
                placements=placements,
                combat_cfg=COMBAT_CFG,
            )

            # Add a non-terrain encounter modifier too
            db.execute(
                "INSERT INTO combat_state (character_id, source, target_stat, "
                "modifier_type, value, duration_type) "
                "VALUES (?, 'Bless', 'bonus_attack', 'buff', 1, 'encounter')",
                (c1,),
            )
            db.commit()

            result = end_encounter(db, sid)
            assert "COMBAT ENDED" in result

            # Verify cleanup
            enc = db.execute("SELECT status FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()
            assert enc[0] == "ended"

            zones_left = db.execute(
                "SELECT COUNT(*) FROM encounter_zones ez "
                "JOIN encounter_state es ON ez.encounter_id = es.id "
                "WHERE es.session_id = ?",
                (sid,),
            ).fetchone()[0]
            assert zones_left == 0

            char_zones = db.execute(
                "SELECT COUNT(*) FROM character_zone cz "
                "JOIN encounter_state es ON cz.encounter_id = es.id "
                "WHERE es.session_id = ?",
                (sid,),
            ).fetchone()[0]
            assert char_zones == 0

            mods = db.execute("SELECT COUNT(*) FROM combat_state WHERE character_id = ?", (c1,)).fetchone()[0]
            assert mods == 0
        finally:
            db.close()


class TestZoneUpdate:
    def test_update_tags_changes_modifiers(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="Fighter")

            zones = [{"name": "Room"}]
            init = [{"character_id": c1, "roll": 15}]
            placements = [{"character_id": c1, "zone": "Room"}]

            start_encounter(
                db,
                sid,
                zones,
                init,
                placements=placements,
                combat_cfg=COMBAT_CFG,
            )
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            # No modifiers initially
            mods = db.execute("SELECT COUNT(*) FROM combat_state WHERE character_id = ?", (c1,)).fetchone()[0]
            assert mods == 0

            # Add cover tag
            result = update_zone_tags(db, enc_id, "Room", ["cover"], combat_cfg=COMBAT_CFG)
            assert "ZONE UPDATED" in result

            mods = db.execute("SELECT source FROM combat_state WHERE character_id = ?", (c1,)).fetchall()
            assert len(mods) == 1
            assert mods[0][0] == "zone:Room:cover"

            # Remove all tags
            update_zone_tags(db, enc_id, "Room", [], combat_cfg=COMBAT_CFG)
            mods = db.execute("SELECT COUNT(*) FROM combat_state WHERE character_id = ?", (c1,)).fetchone()[0]
            assert mods == 0
        finally:
            db.close()


class TestRangeCheck:
    def test_melee_same_zone_ok(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="A")
            c2 = make_character(sid, name="B")

            zones = [{"name": "Room"}]
            init = [
                {"character_id": c1, "roll": 10},
                {"character_id": c2, "roll": 5},
            ]
            placements = [
                {"character_id": c1, "zone": "Room"},
                {"character_id": c2, "zone": "Room"},
            ]

            start_encounter(db, sid, zones, init, placements=placements)
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            err = check_range(db, enc_id, c1, c2, "melee", None, COMBAT_CFG)
            assert err is None
        finally:
            db.close()

    def test_melee_different_zone_fails(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="A")
            c2 = make_character(sid, name="B")

            zones = [{"name": "Near"}, {"name": "Far"}]
            init = [
                {"character_id": c1, "roll": 10},
                {"character_id": c2, "roll": 5},
            ]
            placements = [
                {"character_id": c1, "zone": "Near"},
                {"character_id": c2, "zone": "Far"},
            ]

            start_encounter(db, sid, zones, init, placements=placements)
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            err = check_range(db, enc_id, c1, c2, "melee", None, COMBAT_CFG)
            assert err is not None
            assert "out of range" in err.lower()
        finally:
            db.close()

    def test_ranged_in_range(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="A")
            c2 = make_character(sid, name="B")

            zones = [{"name": "Near"}, {"name": "Far"}]
            init = [
                {"character_id": c1, "roll": 10},
                {"character_id": c2, "roll": 5},
            ]
            placements = [
                {"character_id": c1, "zone": "Near"},
                {"character_id": c2, "zone": "Far"},
            ]

            start_encounter(db, sid, zones, init, placements=placements)
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            # 1 zone * 30ft = 30ft, weapon range 60ft → ok
            err = check_range(db, enc_id, c1, c2, "ranged", 60, COMBAT_CFG)
            assert err is None
        finally:
            db.close()

    def test_ranged_out_of_range(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            c1 = make_character(sid, name="A")
            c2 = make_character(sid, name="B")

            zones = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
            init = [
                {"character_id": c1, "roll": 10},
                {"character_id": c2, "roll": 5},
            ]
            placements = [
                {"character_id": c1, "zone": "A"},
                {"character_id": c2, "zone": "C"},
            ]

            start_encounter(db, sid, zones, init, placements=placements)
            enc_id = db.execute("SELECT id FROM encounter_state WHERE session_id = ?", (sid,)).fetchone()[0]

            # 2 zones * 30ft = 60ft, weapon range 30ft → out of range
            err = check_range(db, enc_id, c1, c2, "ranged", 30, COMBAT_CFG)
            assert err is not None
            assert "out of range" in err.lower()
        finally:
            db.close()
