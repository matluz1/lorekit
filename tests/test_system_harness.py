"""System pack test harness — parametrized integration tests.

Discovers all system packs with a test_config.json and runs one
integration test across all of them. Tests the *engine*, not pack content.
"""

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _discover_packs():
    """Find all directories with a test_config.json.

    Searches:
      - systems/*/test_config.json   (real packs)
      - tests/fixtures/*/test_config.json  (test-only packs)

    Returns list of (pack_id, system_path, config_dict) tuples.
    """
    packs = []
    for search_root in [os.path.join(ROOT, "systems"), FIXTURES]:
        if not os.path.isdir(search_root):
            continue
        for name in sorted(os.listdir(search_root)):
            pack_dir = os.path.join(search_root, name)
            # Check flat layout: systems/<name>/test_config.json
            cfg_path = os.path.join(pack_dir, "test_config.json")
            if os.path.isfile(cfg_path):
                with open(cfg_path) as f:
                    config = json.load(f)
                packs.append((name, pack_dir, config))
                continue
            # Check package layout: systems/<name>/src/cruncher_<name>/data/test_config.json
            pkg_data = os.path.join(pack_dir, "src", f"cruncher_{name}", "data")
            cfg_path = os.path.join(pkg_data, "test_config.json")
            if os.path.isfile(cfg_path):
                with open(cfg_path) as f:
                    config = json.load(f)
                packs.append((name, pkg_data, config))
    return packs


PACKS = _discover_packs()
PACK_IDS = [p[0] for p in PACKS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_attrs(db, cid, attrs):
    for key, val in attrs.items():
        db.execute(
            "INSERT INTO character_attributes (character_id, category, key, value) "
            "VALUES (?, 'stat', ?, ?) "
            "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
            (cid, key, str(val)),
        )
    db.commit()


def _get_derived(db, cid, stat):
    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'derived' AND key = ?",
        (cid, stat),
    ).fetchone()
    return int(row[0]) if row else None


def _setup_from_config(db, cid, config, system_path):
    """Set base stats + weapon attrs from test_config, then rules_calc."""
    attrs = dict(config["base_stats"])
    attrs.update(config.get("weapon_attrs", {}))
    _set_attrs(db, cid, attrs)
    from lorekit.rules import rules_calc

    rules_calc(db, cid, system_path)


def _make_rules_session(make_session, pack_name, system_path):
    """Create a session with rules_system pointing at the pack.

    For packs under tests/fixtures/, creates a symlink so the engine
    can resolve systems/<pack_name>.
    """
    sid = make_session()
    from lorekit.db import require_db

    db = require_db()

    # Determine if we need a symlink (fixture packs live outside systems/)
    link_path = None
    systems_dir = os.path.join(ROOT, "systems")
    if not system_path.startswith(systems_dir):
        link_path = os.path.join(systems_dir, pack_name)
        if not os.path.exists(link_path):
            os.symlink(system_path, link_path)

    db.execute(
        "INSERT INTO session_meta (session_id, key, value) VALUES (?, 'rules_system', ?)",
        (sid, pack_name),
    )
    db.commit()
    db.close()
    return sid, link_path


# ---------------------------------------------------------------------------
# Full combat integration (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack_name,system_path,config", PACKS, ids=PACK_IDS)
class TestFullCombatHarness:
    """Full GM combat flow parametrized across all system packs."""

    def test_full_combat_flow(self, pack_name, system_path, config, make_session, make_character):
        from lorekit.db import require_db
        from lorekit.tools.encounter import encounter_advance_turn, encounter_end, encounter_start
        from lorekit.tools.rules import combat_modifier, rules_resolve

        sid, link_path = _make_rules_session(make_session, pack_name, system_path)
        try:
            db = require_db()
            pc = make_character(sid, name="Hero", char_type="pc")
            npc = make_character(sid, name="Foe", char_type="npc")
            _setup_from_config(db, pc, config, system_path)
            _setup_from_config(db, npc, config, system_path)
            # Set vitals (HP for threshold systems, damage_condition for degree)
            if config.get("vital_current"):
                vital_val = config.get("vital_start_value", 20)
                _set_attrs(db, pc, {config["vital_current"]: vital_val})
                _set_attrs(db, npc, {config["vital_current"]: vital_val})
            from lorekit.rules import rules_calc

            rules_calc(db, pc, system_path)
            rules_calc(db, npc, system_path)

            defense_stat = config["defense_stat"]
            pc_defense_base = _get_derived(db, pc, defense_stat)
            db.close()

            # 1. encounter_start — placement in cover zone auto-recalcs
            cover_tag = config["cover_zone_tag"]
            zones = json.dumps(
                [
                    {"name": "Zone_A", "tags": [cover_tag]},
                    {"name": "Zone_B"},
                ]
            )
            initiative = json.dumps(
                [
                    {"character_id": pc, "roll": 20},
                    {"character_id": npc, "roll": 10},
                ]
            )
            placements = json.dumps(
                [
                    {"character_id": pc, "zone": "Zone_A"},
                    {"character_id": npc, "zone": "Zone_A"},
                ]
            )
            result = encounter_start(
                session_id=sid,
                zones=zones,
                initiative=initiative,
                placements=placements,
            )
            assert "ENCOUNTER STARTED" in result

            db2 = require_db()
            assert _get_derived(db2, pc, defense_stat) == pc_defense_base + 2
            db2.close()

            # 2. combat_modifier — buff NPC attack, auto-recalc
            attack_bonus = config["attack_bonus_key"]
            result = combat_modifier(
                character_id=npc,
                action="add",
                source="test_buff",
                target_stat=attack_bonus,
                value=2,
                duration_type="rounds",
                duration=3,
            )
            assert "MODIFIER ADDED" in result
            assert "RULES_CALC" in result

            # 3. rules_resolve — attack
            melee_action = config["melee_action"]
            result = rules_resolve(
                attacker_id=pc,
                defender_id=npc,
                action=melee_action,
            )
            assert "ACTION" in result
            if config["resolution_type"] == "degree":
                assert "RESIST" in result or "MISS" in result
            # threshold always has ACTION line — no extra assertion needed

            # 4. advance turn — end PC's turn
            result = encounter_advance_turn(session_id=sid)
            assert "END TURN" in result
            assert "Foe" in result

            # 5. advance again — end NPC's turn (test_buff ticks)
            result = encounter_advance_turn(session_id=sid)
            assert "TICKED: test_buff" in result
            assert "Hero" in result

            # 6. encounter_end — cleanup + recalc
            result = encounter_end(session_id=sid)
            assert "COMBAT ENDED" in result

            # Cover modifier should be gone
            db3 = require_db()
            assert _get_derived(db3, pc, defense_stat) == pc_defense_base
            db3.close()

        finally:
            if link_path and os.path.islink(link_path):
                os.unlink(link_path)


# ---------------------------------------------------------------------------
# Helpers — load system.json sections
# ---------------------------------------------------------------------------


def _load_system_json(system_path):
    with open(os.path.join(system_path, "system.json")) as f:
        return json.load(f)


def _get_stat(db, cid, key):
    """Read a stat-category attribute."""
    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'stat' AND key = ?",
        (cid, key),
    ).fetchone()
    return int(row[0]) if row else None


# ---------------------------------------------------------------------------
# Extended parametrized coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack_name,system_path,config", PACKS, ids=PACK_IDS)
class TestRestHarness:
    """Rest flow parametrized across all system packs."""

    def test_long_rest(self, pack_name, system_path, config, make_session, make_character):
        from lorekit.db import require_db
        from lorekit.rest import rest

        system_data = _load_system_json(system_path)
        rest_cfg = system_data.get("rest", {})
        if "long" not in rest_cfg:
            pytest.skip(f"{pack_name} has no long rest config")

        sid, link_path = _make_rules_session(make_session, pack_name, system_path)
        try:
            db = require_db()
            pc = make_character(sid, name="Hero", char_type="pc")
            _setup_from_config(db, pc, config, system_path)
            # Set low vital to test restoration
            vital = config.get("vital_current")
            if vital:
                _set_attrs(db, pc, {vital: 1})
            from lorekit.rules import rules_calc

            rules_calc(db, pc, system_path)

            result = rest(db, sid, "long", system_path)
            assert "REST (LONG)" in result
            assert "Hero" in result
            db.close()
        finally:
            if link_path and os.path.islink(link_path):
                os.unlink(link_path)

    def test_short_rest(self, pack_name, system_path, config, make_session, make_character):
        from lorekit.db import require_db
        from lorekit.rest import rest

        system_data = _load_system_json(system_path)
        rest_cfg = system_data.get("rest", {})
        if "short" not in rest_cfg:
            pytest.skip(f"{pack_name} has no short rest config")

        sid, link_path = _make_rules_session(make_session, pack_name, system_path)
        try:
            db = require_db()
            pc = make_character(sid, name="Hero", char_type="pc")
            _setup_from_config(db, pc, config, system_path)
            vital = config.get("vital_current")
            if vital:
                _set_attrs(db, pc, {vital: 1})
            from lorekit.rules import rules_calc

            rules_calc(db, pc, system_path)

            result = rest(db, sid, "short", system_path)
            assert "REST (SHORT)" in result
            db.close()
        finally:
            if link_path and os.path.islink(link_path):
                os.unlink(link_path)

    def test_rest_only_affects_pcs(self, pack_name, system_path, config, make_session, make_character):
        from lorekit.db import require_db
        from lorekit.rest import rest

        system_data = _load_system_json(system_path)
        if "rest" not in system_data:
            pytest.skip(f"{pack_name} has no rest config")

        rest_type = next(iter(system_data["rest"]))
        sid, link_path = _make_rules_session(make_session, pack_name, system_path)
        try:
            db = require_db()
            pc = make_character(sid, name="Hero", char_type="pc")
            npc = make_character(sid, name="Foe", char_type="npc")
            _setup_from_config(db, pc, config, system_path)
            _setup_from_config(db, npc, config, system_path)

            result = rest(db, sid, rest_type, system_path)
            assert "Hero" in result
            assert "Foe" not in result
            db.close()
        finally:
            if link_path and os.path.islink(link_path):
                os.unlink(link_path)


@pytest.mark.parametrize("pack_name,system_path,config", PACKS, ids=PACK_IDS)
class TestInitiativeAutoRollHarness:
    """Initiative auto-roll using pack's initiative_stat."""

    def test_auto_initiative(self, pack_name, system_path, config, make_session, make_character):
        from lorekit.tools.encounter import encounter_start

        system_data = _load_system_json(system_path)
        combat_cfg = system_data.get("combat", {})
        if "initiative_stat" not in combat_cfg:
            pytest.skip(f"{pack_name} has no initiative_stat")

        sid, link_path = _make_rules_session(make_session, pack_name, system_path)
        try:
            from lorekit.db import require_db

            db = require_db()
            pc = make_character(sid, name="Hero", char_type="pc")
            npc = make_character(sid, name="Foe", char_type="npc")
            _setup_from_config(db, pc, config, system_path)
            _setup_from_config(db, npc, config, system_path)
            db.close()

            zones = json.dumps([{"name": "Arena"}])
            placements = json.dumps(
                [
                    {"character_id": pc, "zone": "Arena"},
                    {"character_id": npc, "zone": "Arena"},
                ]
            )
            # initiative="auto" — engine rolls d20 + initiative_stat
            result = encounter_start(
                session_id=sid,
                zones=zones,
                initiative="auto",
                placements=placements,
            )
            assert "ENCOUNTER STARTED" in result
            # Auto-roll shows roll details
            assert "d20(" in result
        finally:
            if link_path and os.path.islink(link_path):
                os.unlink(link_path)


@pytest.mark.parametrize("pack_name,system_path,config", PACKS, ids=PACK_IDS)
class TestHudVitalHarness:
    """HUD vital stats using pack's hud config."""

    def test_encounter_status_shows_vitals(self, pack_name, system_path, config, make_session, make_character):
        from lorekit.tools.encounter import encounter_start, encounter_status

        system_data = _load_system_json(system_path)
        hud_cfg = system_data.get("combat", {}).get("hud", {})
        vital_cfg = hud_cfg.get("vital_stat", {})
        if not vital_cfg.get("current"):
            pytest.skip(f"{pack_name} has no hud vital_stat")

        sid, link_path = _make_rules_session(make_session, pack_name, system_path)
        try:
            from lorekit.db import require_db

            db = require_db()
            pc = make_character(sid, name="Hero", char_type="pc")
            _setup_from_config(db, pc, config, system_path)
            vital = config.get("vital_current")
            if vital:
                _set_attrs(db, pc, {vital: 10})
            from lorekit.rules import rules_calc

            rules_calc(db, pc, system_path)
            db.close()

            zones = json.dumps([{"name": "Arena"}])
            initiative = json.dumps([{"character_id": pc, "roll": 15}])
            placements = json.dumps([{"character_id": pc, "zone": "Arena"}])
            encounter_start(
                session_id=sid,
                zones=zones,
                initiative=initiative,
                placements=placements,
            )

            result = encounter_status(session_id=sid)
            assert "Hero" in result
            # Should show vital label if configured
            label = vital_cfg.get("label", "")
            if label:
                assert label in result
        finally:
            if link_path and os.path.islink(link_path):
                os.unlink(link_path)


@pytest.mark.parametrize("pack_name,system_path,config", PACKS, ids=PACK_IDS)
class TestEncounterTemplateHarness:
    """Encounter template using first template in pack's encounter_templates."""

    def test_template_start(self, pack_name, system_path, config, make_session, make_character):
        from lorekit.tools.encounter import encounter_start

        system_data = _load_system_json(system_path)
        templates = system_data.get("encounter_templates", {})
        if not templates:
            pytest.skip(f"{pack_name} has no encounter_templates")

        template_name = next(iter(templates))
        sid, link_path = _make_rules_session(make_session, pack_name, system_path)
        try:
            from lorekit.db import require_db

            db = require_db()
            pc = make_character(sid, name="Hero", char_type="pc")
            _setup_from_config(db, pc, config, system_path)
            db.close()

            # Use template to define zones, provide initiative + placement
            first_zone = templates[template_name]["zones"][0]["name"]
            initiative = json.dumps([{"character_id": pc, "roll": 15}])
            placements = json.dumps([{"character_id": pc, "zone": first_zone}])
            result = encounter_start(
                session_id=sid,
                template=template_name,
                initiative=initiative,
                placements=placements,
            )
            assert "ENCOUNTER STARTED" in result
        finally:
            if link_path and os.path.islink(link_path):
                os.unlink(link_path)
