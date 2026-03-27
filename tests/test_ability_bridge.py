"""Tests for the ability-to-action bridge.

Validates that abilities with action/uses_action/movement fields
auto-register the correct mechanical bridges during character_build.
"""

import json
import os
import re
from unittest.mock import patch

import cruncher_mm3e
import pytest

MM3E_SYSTEM = cruncher_mm3e.pack_path()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_id(result):
    m = re.search(r":\s*(\d+)", result)
    assert m, f"Could not extract ID from: {result}"
    return int(m.group(1))


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


def _start_encounter(db, session_id, characters, zones, placements, adjacency=None):
    from lorekit.encounter import start_encounter

    cfg = _combat_cfg()
    start_encounter(
        db,
        session_id,
        zones,
        [{"character_id": cid, "roll": 20 - i} for i, cid in enumerate(characters)],
        adjacency=adjacency,
        placements=[{"character_id": cid, "zone": z} for cid, z in placements],
        combat_cfg=cfg,
    )


# ===========================================================================
# action field → action_override
# ===========================================================================


class TestActionField:
    def test_build_creates_action_override(self, make_session):
        """Ability with 'action' field auto-creates action_override attribute."""
        from lorekit.tools.character import character_build

        sid = make_session()
        result = character_build(
            session=sid,
            name="Mage",
            level=8,
            type="npc",
            abilities=json.dumps(
                [
                    {
                        "name": "Ether Thorns",
                        "category": "power",
                        "uses": "at_will",
                        "desc": "Ranged Damage 8",
                        "cost": 16,
                        "action": {
                            "key": "ether_thorns",
                            "attack_stat": "ranged_attack",
                            "defense_stat": "dodge",
                            "damage_rank_stat": "ranged_damage",
                            "range": "ranged",
                        },
                    }
                ]
            ),
        )
        assert "CHARACTER_BUILT" in result

        from lorekit.db import require_db

        db = require_db()
        try:
            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = 1 AND category = 'action_override' AND key = 'ether_thorns'",
            ).fetchone()
            assert row is not None
            action_def = json.loads(row[0])
            assert action_def["attack_stat"] == "ranged_attack"
            assert action_def["defense_stat"] == "dodge"
            assert action_def["range"] == "ranged"
            # 'key' should NOT be in the stored action def
            assert "key" not in action_def
        finally:
            db.close()

    def test_action_override_resolves_in_combat(self, make_session, make_character):
        """Action override created from ability is usable in resolve_action."""
        from lorekit.combat.resolve import resolve_action
        from lorekit.db import require_db

        db = require_db()
        try:
            sid = make_session()
            npc = _make_character(db, sid, make_character, "Blaster")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")

            # Manually set action_override (same as what character_build would create)
            from lorekit.character import set_attr

            override = json.dumps(
                {
                    "attack_stat": "close_attack",
                    "defense_stat": "parry",
                    "range": "melee",
                    "effect_rank": 10,
                }
            )
            set_attr(db, npc, "action_override", "mind_blast", override)

            # d20=15 → hit, resistance d20=5 → fail
            roll_calls = iter([14, 4])
            with patch("secrets.randbelow", side_effect=roll_calls):
                result = resolve_action(db, npc, hero, "mind_blast", MM3E_SYSTEM)
            assert "HIT" in result
        finally:
            db.close()

    def test_action_key_defaults_to_name(self, make_session):
        """When 'key' is omitted from action, ability name is slugified."""
        from lorekit.tools.character import character_build

        sid = make_session()
        character_build(
            session=sid,
            name="Mage",
            level=8,
            type="npc",
            abilities=json.dumps(
                [
                    {
                        "name": "Ether Thorns",
                        "category": "power",
                        "uses": "at_will",
                        "desc": "Ranged Damage 8",
                        "action": {
                            "attack_stat": "ranged_attack",
                            "defense_stat": "dodge",
                            "range": "ranged",
                        },
                    }
                ]
            ),
        )

        from lorekit.db import require_db

        db = require_db()
        try:
            row = db.execute(
                "SELECT key FROM character_attributes WHERE character_id = 1 AND category = 'action_override'",
            ).fetchone()
            assert row is not None
            assert row[0] == "ether_thorns"
        finally:
            db.close()


# ===========================================================================
# uses_action field → embedded in description + prompt hint
# ===========================================================================


class TestUsesAction:
    def test_build_embeds_uses_action(self, make_session):
        """Ability with 'uses_action' embeds it in the description JSON."""
        from lorekit.tools.character import character_build

        sid = make_session()
        character_build(
            session=sid,
            name="Trickster",
            level=8,
            type="npc",
            abilities=json.dumps(
                [
                    {
                        "name": "Daze",
                        "category": "advantage",
                        "uses": "at_will",
                        "desc": "Deception vs Insight — target is Dazed",
                        "uses_action": "setup_deception",
                    }
                ]
            ),
        )

        from lorekit.db import require_db

        db = require_db()
        try:
            row = db.execute(
                "SELECT description FROM character_abilities WHERE character_id = 1 AND name = 'Daze'",
            ).fetchone()
            assert row is not None
            desc_data = json.loads(row[0])
            assert desc_data["uses_action"] == "setup_deception"
            assert "Deception vs Insight" in desc_data["desc"]
        finally:
            db.close()

    def test_uses_action_shown_in_combat_context(self, make_session, make_character):
        """build_combat_context includes [uses action: ...] hint for abilities."""
        from lorekit.db import require_db
        from lorekit.narrative.session import meta_set

        db = require_db()
        try:
            sid = make_session()
            meta_set(db, sid, "rules_system", MM3E_SYSTEM)

            npc = _make_character(db, sid, make_character, "Trickster")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")

            # Manually set ability with uses_action embedded
            from lorekit.character import set_ability

            desc = json.dumps({"desc": "Deception vs Insight", "uses_action": "setup_deception"})
            set_ability(db, npc, "Daze", desc, "advantage", "at_will")

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena", "tags": []}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            from lorekit.npc.combat import build_combat_context

            cfg = _combat_cfg()
            context = build_combat_context(db, npc, sid, cfg)
            assert "[uses action: setup_deception]" in context
        finally:
            db.close()


# ===========================================================================
# movement field → movement_mode attribute + skip_adjacency
# ===========================================================================


class TestMovementMode:
    def test_build_creates_movement_mode(self, make_session):
        """Ability with 'movement' field stores movement_mode attribute."""
        from lorekit.tools.character import character_build

        sid = make_session()
        character_build(
            session=sid,
            name="Teleporter",
            level=8,
            type="npc",
            abilities=json.dumps(
                [
                    {
                        "name": "Blink",
                        "category": "power",
                        "uses": "at_will",
                        "desc": "Teleport 11",
                        "cost": 11,
                        "movement": {"mode": "teleport", "skip_adjacency": True},
                    }
                ]
            ),
        )

        from lorekit.db import require_db

        db = require_db()
        try:
            row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = 1 AND category = 'movement_mode' AND key = 'teleport'",
            ).fetchone()
            assert row is not None
            mode_data = json.loads(row[0])
            assert mode_data["skip_adjacency"] is True
        finally:
            db.close()

    def test_teleport_skips_adjacency(self, make_session, make_character):
        """Character with teleport movement_mode can move to non-adjacent zone."""
        from lorekit.db import require_db
        from lorekit.encounter import _require_active_encounter, move_character

        db = require_db()
        try:
            sid = make_session()
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")

            # Zones: A -- B -- C (A not adjacent to C)
            _start_encounter(
                db,
                sid,
                [hero],
                [
                    {"name": "Zone A", "tags": []},
                    {"name": "Zone B", "tags": []},
                    {"name": "Zone C", "tags": []},
                ],
                [(hero, "Zone A")],
                adjacency=[
                    {"from": "Zone A", "to": "Zone B", "weight": 1},
                    {"from": "Zone B", "to": "Zone C", "weight": 1},
                ],
            )

            enc_id = _require_active_encounter(db, sid)[0]

            # Teleport from Zone A to Zone C (not adjacent) with skip_adjacency
            result = move_character(db, enc_id, hero, "Zone C", skip_adjacency=True)
            assert "MOVED" in result
            assert "Zone C" in result
        finally:
            db.close()

    def test_normal_movement_blocked_by_budget(self, make_session, make_character):
        """Without skip_adjacency, non-adjacent move is blocked by budget."""
        from lorekit.db import LoreKitError, require_db
        from lorekit.encounter import _require_active_encounter, move_character

        db = require_db()
        try:
            sid = make_session()
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")

            _start_encounter(
                db,
                sid,
                [hero],
                [
                    {"name": "Zone A", "tags": []},
                    {"name": "Zone B", "tags": []},
                    {"name": "Zone C", "tags": []},
                ],
                [(hero, "Zone A")],
                adjacency=[
                    {"from": "Zone A", "to": "Zone B", "weight": 1},
                    {"from": "Zone B", "to": "Zone C", "weight": 1},
                ],
            )

            enc_id = _require_active_encounter(db, sid)[0]

            # Budget of 1 — can reach B (cost 1) but not C (cost 2)
            with pytest.raises(LoreKitError, match="Cannot reach"):
                move_character(db, enc_id, hero, "Zone C", movement_budget=1)
        finally:
            db.close()

    def test_movement_mode_shown_in_combat_context(self, make_session, make_character):
        """build_combat_context includes movement mode note."""
        from lorekit.character import set_attr
        from lorekit.db import require_db
        from lorekit.narrative.session import meta_set

        db = require_db()
        try:
            sid = make_session()
            meta_set(db, sid, "rules_system", MM3E_SYSTEM)

            npc = _make_character(db, sid, make_character, "Blinker")
            hero = _make_character(db, sid, make_character, "Hero", char_type="pc")
            set_attr(db, npc, "movement_mode", "teleport", json.dumps({"mode": "teleport", "skip_adjacency": True}))

            _start_encounter(
                db,
                sid,
                [npc, hero],
                [{"name": "Arena", "tags": []}],
                [(npc, "Arena"), (hero, "Arena")],
            )

            from lorekit.npc.combat import build_combat_context

            cfg = _combat_cfg()
            context = build_combat_context(db, npc, sid, cfg)
            assert "teleport (skip adjacency)" in context
        finally:
            db.close()
