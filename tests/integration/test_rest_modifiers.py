"""Integration tests: rest clears combat modifiers and restores stats.

Verify that short/long rest correctly clears duration-typed modifiers
and restores HP according to the system pack formulas.

System config (test_system):
  short: clear_duration_types=["encounter"], restore current_hp=floor(max_hp/2)
  long:  clear_duration_types=["encounter","rounds","save_ends"], restore current_hp=max_hp

Level 5, hit_die_avg=6, con=12 → con_mod=1 → max_hp = 6*5 + 1*5 = 35
  short rest: floor(35/2) = 17
  long  rest: 35
"""

import json
import os

import pytest

pytest.importorskip("sqlite_vec")

from lorekit.rules import resolve_system_path  # noqa: E402
from lorekit.tools.character import character_sheet_update, character_view  # noqa: E402
from lorekit.tools.rules import combat_modifier  # noqa: E402
from lorekit.tools.session import session_meta_set  # noqa: E402
from lorekit.tools.utility import rest  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "../fixtures")
TEST_SYSTEM = os.path.join(FIXTURES, "test_system")


@pytest.fixture(autouse=True)
def _patch_system_path(monkeypatch):
    """Make resolve_system_path find our test fixture for 'test_system'."""
    _real = resolve_system_path

    def _patched(name):
        if name == "test_system":
            return TEST_SYSTEM
        return _real(name)

    monkeypatch.setattr("lorekit.rules.resolve_system_path", _patched)
    monkeypatch.setattr("lorekit.tools._helpers.resolve_system_path", _patched)


def _setup_session(make_session):
    sid = make_session()
    session_meta_set(session_id=sid, key="rules_system", value="test_system")
    return sid


def _setup_pc(session_id, make_character, hp=10):
    """Create a level-5 PC with defined stats and reduced HP."""
    cid = make_character(session_id, name="Kyra", level=5)
    attrs = json.dumps(
        [
            {"category": "stat", "key": "str", "value": "10"},
            {"category": "stat", "key": "dex", "value": "10"},
            {"category": "stat", "key": "con", "value": "12"},
            {"category": "stat", "key": "base_attack", "value": "5"},
            {"category": "stat", "key": "hit_die_avg", "value": "6"},
            {"category": "combat", "key": "current_hp", "value": str(hp)},
        ]
    )
    character_sheet_update(character_id=cid, attrs=attrs)
    return cid


def _get_db():
    from lorekit.db import get_db

    return get_db(os.environ["LOREKIT_DB"])


def _get_modifiers(character_id: int) -> list[tuple]:
    """Return list of (source, duration_type) for all combat_state rows."""
    db = _get_db()
    rows = db.execute(
        "SELECT source, duration_type FROM combat_state WHERE character_id = ?",
        (character_id,),
    ).fetchall()
    db.close()
    return [(r[0], r[1]) for r in rows]


class TestShortRest:
    """Short rest clears 'encounter' modifiers, restores HP to floor(max_hp/2)."""

    def test_short_rest_clears_encounter_modifier_and_restores_partial_hp(self, make_session, make_character):
        sid = _setup_session(make_session)
        cid = _setup_pc(sid, make_character, hp=10)

        # Add encounter-duration modifier (Bless)
        r = combat_modifier(
            character_id=cid,
            action="add",
            source="Bless",
            target_stat="bonus_attack",
            value=1,
            modifier_type="buff",
            duration_type="encounter",
        )
        assert "MODIFIER ADDED" in r

        # Add rounds-duration modifier (Haste)
        r = combat_modifier(
            character_id=cid,
            action="add",
            source="Haste",
            target_stat="bonus_defense",
            value=2,
            modifier_type="buff",
            duration_type="rounds",
            duration=3,
        )
        assert "MODIFIER ADDED" in r

        # Verify both modifiers exist before rest
        mods_before = _get_modifiers(cid)
        sources_before = [src for src, _ in mods_before]
        assert "Bless" in sources_before
        assert "Haste" in sources_before

        # Short rest
        result = rest(session_id=sid, type="short")
        assert "REST (SHORT)" in result

        # "encounter" modifier (Bless) should be gone
        mods_after = _get_modifiers(cid)
        sources_after = [src for src, _ in mods_after]
        assert "Bless" not in sources_after, "Bless (encounter) should be cleared by short rest"

        # "rounds" modifier (Haste) should still exist
        assert "Haste" in sources_after, "Haste (rounds) should survive a short rest"

        # HP should be floor(max_hp / 2) = floor(35 / 2) = 17
        view = character_view(character_id=cid)
        assert any("current_hp" in line and "17" in line for line in view.splitlines()), (
            f"Expected current_hp=17 after short rest:\n{view}"
        )


class TestLongRest:
    """Long rest clears ALL modifier types and fully restores HP."""

    def test_long_rest_clears_all_modifiers_and_restores_full_hp(self, make_session, make_character):
        sid = _setup_session(make_session)
        cid = _setup_pc(sid, make_character, hp=10)

        # Add encounter-duration modifier (Bless)
        r = combat_modifier(
            character_id=cid,
            action="add",
            source="Bless",
            target_stat="bonus_attack",
            value=1,
            modifier_type="buff",
            duration_type="encounter",
        )
        assert "MODIFIER ADDED" in r

        # Add rounds-duration modifier (Haste)
        r = combat_modifier(
            character_id=cid,
            action="add",
            source="Haste",
            target_stat="bonus_defense",
            value=2,
            modifier_type="buff",
            duration_type="rounds",
            duration=3,
        )
        assert "MODIFIER ADDED" in r

        # Long rest
        result = rest(session_id=sid, type="long")
        assert "REST (LONG)" in result

        # Both modifiers should be gone
        mods_after = _get_modifiers(cid)
        sources_after = [src for src, _ in mods_after]
        assert "Bless" not in sources_after, "Bless (encounter) should be cleared by long rest"
        assert "Haste" not in sources_after, "Haste (rounds) should be cleared by long rest"

        # HP should be fully restored to max_hp = 35
        view = character_view(character_id=cid)
        assert any("current_hp" in line and "35" in line for line in view.splitlines()), (
            f"Expected current_hp=35 after long rest:\n{view}"
        )
