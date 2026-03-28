"""Integration tests: entity auto-tagging in turn_save.

Verify that turn_save correctly tags characters and regions in the
entry_entities table based on name mentions in the narration.
"""

import os

import pytest

pytest.importorskip("sqlite_vec")

from lorekit.tools.narrative import turn_save  # noqa: E402


def _get_db():
    from lorekit.db import get_db

    return get_db(os.environ["LOREKIT_DB"])


def _tagged_entities(timeline_id: int) -> list[tuple[str, int]]:
    """Return list of (entity_type, entity_id) tagged for a given timeline entry."""
    db = _get_db()
    rows = db.execute(
        "SELECT entity_type, entity_id FROM entry_entities WHERE source = 'timeline' AND source_id = ?",
        (timeline_id,),
    ).fetchall()
    db.close()
    return [(r[0], r[1]) for r in rows]


def _last_timeline_id(session_id: int) -> int:
    """Return the ID of the most recent timeline entry for a session."""
    db = _get_db()
    row = db.execute(
        "SELECT id FROM timeline WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    db.close()
    assert row is not None, "No timeline entries found"
    return row[0]


class TestSingleCharacterTagging:
    """Only the character mentioned in narration gets tagged."""

    def test_mentioned_character_is_tagged(self, make_session, make_character):
        sid = make_session()
        valeros_id = make_character(sid, name="Valeros")
        seelah_id = make_character(sid, name="Seelah")

        turn_save(
            session_id=sid,
            narration="Valeros draws his sword and charges at the goblin.",
            summary="V attacks",
        )

        tl_id = _last_timeline_id(sid)
        tagged = _tagged_entities(tl_id)
        entity_ids = [eid for _, eid in tagged]

        assert valeros_id in entity_ids, "Valeros should be tagged (mentioned in narration)"
        assert seelah_id not in entity_ids, "Seelah should NOT be tagged (not mentioned)"


class TestMultipleCharacterTagging:
    """Both characters mentioned in narration are tagged."""

    def test_both_characters_tagged(self, make_session, make_character):
        sid = make_session()
        valeros_id = make_character(sid, name="Valeros")
        seelah_id = make_character(sid, name="Seelah")

        turn_save(
            session_id=sid,
            narration="Valeros and Seelah explore the dungeon.",
            summary="Explore",
        )

        tl_id = _last_timeline_id(sid)
        tagged = _tagged_entities(tl_id)
        entity_ids = [eid for _, eid in tagged]

        assert valeros_id in entity_ids, "Valeros should be tagged"
        assert seelah_id in entity_ids, "Seelah should be tagged"


class TestRegionTagging:
    """Regions mentioned by name in narration are tagged."""

    def test_region_is_tagged(self, make_session, make_character, make_region):
        sid = make_session()
        make_character(sid, name="Valeros")
        forest_id = make_region(sid, name="Dark Forest", desc="A dark, forbidding forest")

        turn_save(
            session_id=sid,
            narration="The party enters the Dark Forest.",
            summary="Enter forest",
        )

        tl_id = _last_timeline_id(sid)
        tagged = _tagged_entities(tl_id)
        region_tags = [(etype, eid) for etype, eid in tagged if etype == "region"]

        assert any(eid == forest_id for _, eid in region_tags), (
            f"Dark Forest (id={forest_id}) should be tagged as a region"
        )
