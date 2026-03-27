"""Tests for on_hit resistance checks and reaction policies."""

import json
import os
from unittest.mock import patch

import pytest

from cruncher.system_pack import load_system_pack
from lorekit.combat.effects import _check_on_hit_resist
from lorekit.combat.reactions import _get_reaction_policy
from lorekit.combat.resolve import resolve_action
from lorekit.rules import load_character_data

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


def _db():
    from lorekit.db import require_db

    return require_db()


def _setup_fighter(db, make_session, make_character, name, **stat_overrides):
    """Create a character with stats for the test system."""
    from lorekit.character import set_attr

    sid = make_session()
    cid = make_character(sid, name=name, level=5)
    defaults = {
        "str": "18",
        "dex": "14",
        "con": "12",
        "base_attack": "5",
        "hit_die_avg": "6",
    }
    defaults.update(stat_overrides)

    for key, val in defaults.items():
        set_attr(db, cid, "stat", key, val)
    set_attr(db, cid, "combat", "base_attack", defaults["base_attack"])
    set_attr(db, cid, "combat", "hit_die_avg", defaults["hit_die_avg"])

    from lorekit.rules import rules_calc

    rules_calc(db, cid, TEST_SYSTEM)

    set_attr(db, cid, "build", "weapon_damage_die", "1d8")
    return sid, cid


class TestOnHitResist:
    def test_resist_success_skips_effects(self, make_session, make_character):
        """When defender passes resist check, on_hit effects are skipped."""
        db = _db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, "Defender")

            pack = load_system_pack(TEST_SYSTEM)
            attacker = load_character_data(db, atk_id)
            defender = load_character_data(db, def_id)

            resist = {
                "defender_stat": ["melee_attack"],
                "dc_stat": "melee_attack",
                "dc_offset": 10,
            }
            lines = []

            # Roll high enough to resist (d20=19 + bonus vs DC)
            with patch("secrets.randbelow", return_value=18):  # 18+1=19
                resisted = _check_on_hit_resist(db, pack, attacker, defender, resist, lines)

            assert resisted is True
            assert any("RESISTED" in l for l in lines)
        finally:
            db.close()

    def test_resist_failure_allows_effects(self, make_session, make_character):
        """When defender fails resist check, on_hit effects proceed."""
        db = _db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, "Defender")

            pack = load_system_pack(TEST_SYSTEM)
            attacker = load_character_data(db, atk_id)
            defender = load_character_data(db, def_id)

            resist = {
                "defender_stat": "melee_attack",  # also works as string
                "dc_stat": "melee_attack",
                "dc_offset": 10,
            }
            lines = []

            # Roll very low (d20=1)
            with patch("secrets.randbelow", return_value=0):  # 0+1=1
                resisted = _check_on_hit_resist(db, pack, attacker, defender, resist, lines)

            assert resisted is False
            assert any("FAILED" in l for l in lines)
        finally:
            db.close()

    def test_resist_no_valid_stat_skips(self, make_session, make_character):
        """If defender has no valid resist stat, check is skipped (not resisted)."""
        db = _db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, "Defender")

            pack = load_system_pack(TEST_SYSTEM)
            attacker = load_character_data(db, atk_id)
            defender = load_character_data(db, def_id)

            resist = {
                "defender_stat": ["nonexistent_stat"],
                "dc_stat": "melee_attack",
            }
            lines = []

            resisted = _check_on_hit_resist(db, pack, attacker, defender, resist, lines)

            assert resisted is False
            assert any("no valid defender stat" in l for l in lines)
        finally:
            db.close()

    def test_resist_best_of_multiple_stats(self, make_session, make_character):
        """When multiple defender stats are given, uses the best one."""
        db = _db()
        try:
            sid, atk_id = _setup_fighter(db, make_session, make_character, "Attacker")
            _, def_id = _setup_fighter(db, make_session, make_character, "Defender")

            pack = load_system_pack(TEST_SYSTEM)
            attacker = load_character_data(db, atk_id)
            defender = load_character_data(db, def_id)

            resist = {
                "defender_stat": ["melee_attack", "ranged_attack"],
                "dc_stat": "melee_attack",
                "dc_offset": 10,
            }
            lines = []

            with patch("secrets.randbelow", return_value=18):
                _check_on_hit_resist(db, pack, attacker, defender, resist, lines)

            # Should mention "best of"
            assert any("best of" in l for l in lines)
        finally:
            db.close()


class TestReactionPolicy:
    def test_default_policy_is_active(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Fighter")
            policy = _get_reaction_policy(db, cid, "Deflect")
            assert policy == "active"
        finally:
            db.close()

    def test_set_inactive_policy(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Fighter")

            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'reaction_policy', 'Deflect', 'inactive')",
                (cid,),
            )
            db.commit()

            policy = _get_reaction_policy(db, cid, "Deflect")
            assert policy == "inactive"
        finally:
            db.close()

    def test_ask_policy_read(self, make_session, make_character):
        db = _db()
        try:
            sid = make_session()
            cid = make_character(sid, name="Fighter")

            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'reaction_policy', 'Interpose', 'ask')",
                (cid,),
            )
            db.commit()

            policy = _get_reaction_policy(db, cid, "Interpose")
            assert policy == "ask"
        finally:
            db.close()
