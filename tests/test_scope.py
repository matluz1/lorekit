"""Tests for timeline/journal scope filtering in NPC prefetch."""

from unittest.mock import patch

import pytest


def _make_session_and_npc(make_session, make_character):
    """Create a session with one NPC for scope testing."""
    from lorekit.db import require_db

    db = require_db()
    try:
        sid = make_session()
        npc_id = make_character(sid, name="TestNPC", char_type="npc")
        return sid, npc_id, db
    except Exception:
        db.close()
        raise


class TestTimelineScope:
    def test_all_scope_visible(self, make_session, make_character):
        """Timeline entries with scope='all' are visible to any NPC."""
        from lorekit.db import require_db
        from lorekit.narrative.timeline import add as tl_add
        from lorekit.npc.prefetch import _get_recent_timeline

        db = require_db()
        try:
            sid = make_session()
            npc = make_character(sid, name="Observer", char_type="npc")

            tl_add(db, sid, "narration", "Public announcement!", scope="all")

            entries = _get_recent_timeline(db, sid, npc_id=npc)
            assert any("Public announcement" in e for e in entries)
        finally:
            db.close()

    def test_gm_scope_hidden(self, make_session, make_character):
        """Timeline entries with scope='gm' are never visible to NPCs."""
        from lorekit.db import require_db
        from lorekit.narrative.timeline import add as tl_add
        from lorekit.npc.prefetch import _get_recent_timeline

        db = require_db()
        try:
            sid = make_session()
            npc = make_character(sid, name="Observer", char_type="npc")

            tl_add(db, sid, "narration", "Secret GM note", scope="gm")

            entries = _get_recent_timeline(db, sid, npc_id=npc)
            assert not any("Secret GM note" in e for e in entries)
        finally:
            db.close()

    def test_participants_scope_requires_tagging(self, make_session, make_character):
        """Timeline entries with scope='participants' only visible to tagged NPCs."""
        from lorekit.db import require_db
        from lorekit.narrative.timeline import add as tl_add
        from lorekit.npc.prefetch import _get_recent_timeline

        db = require_db()
        try:
            sid = make_session()
            tagged_npc = make_character(sid, name="Present", char_type="npc")
            absent_npc = make_character(sid, name="Absent", char_type="npc")

            result = tl_add(db, sid, "narration", "Private scene", scope="participants")
            tl_id = int(result.split(": ")[1])

            # Tag only the first NPC as participant
            db.execute(
                "INSERT INTO entry_entities (source, source_id, entity_type, entity_id) "
                "VALUES ('timeline', ?, 'character', ?)",
                (tl_id, tagged_npc),
            )
            db.commit()

            # Tagged NPC sees it
            entries = _get_recent_timeline(db, sid, npc_id=tagged_npc)
            assert any("Private scene" in e for e in entries)

            # Absent NPC doesn't
            entries = _get_recent_timeline(db, sid, npc_id=absent_npc)
            assert not any("Private scene" in e for e in entries)
        finally:
            db.close()


class TestJournalScope:
    def test_journal_in_prefetch(self, make_session, make_character):
        """Journal entries with scope='all' appear in NPC prefetch context."""
        from lorekit.db import require_db
        from lorekit.narrative.journal import add as jn_add
        from lorekit.npc.prefetch import _get_recent_journal

        db = require_db()
        try:
            sid = make_session()
            npc = make_character(sid, name="Observer", char_type="npc")

            jn_add(db, sid, "event", "A meteor struck the desert", scope="all")

            entries = _get_recent_journal(db, sid, npc_id=npc)
            assert any("meteor" in e for e in entries)
        finally:
            db.close()

    def test_journal_gm_scope_hidden(self, make_session, make_character):
        """Journal entries with scope='gm' are hidden from NPCs."""
        from lorekit.db import require_db
        from lorekit.narrative.journal import add as jn_add
        from lorekit.npc.prefetch import _get_recent_journal

        db = require_db()
        try:
            sid = make_session()
            npc = make_character(sid, name="Observer", char_type="npc")

            jn_add(db, sid, "note", "Plot twist: villain is actually...", scope="gm")

            entries = _get_recent_journal(db, sid, npc_id=npc)
            assert not any("Plot twist" in e for e in entries)
        finally:
            db.close()

    def test_combat_journal_scoped_to_participants(self, make_session, make_character):
        """Combat journal with scope='participants' only visible to tagged fighters."""
        from lorekit.db import require_db
        from lorekit.narrative.journal import add as jn_add
        from lorekit.npc.prefetch import _get_recent_journal

        db = require_db()
        try:
            sid = make_session()
            fighter = make_character(sid, name="Fighter", char_type="npc")
            bystander = make_character(sid, name="Bystander", char_type="npc")

            result = jn_add(db, sid, "combat", "Fighter defeated the dragon", scope="participants")
            jn_id = int(result.split(": ")[1])

            # Tag only the fighter
            db.execute(
                "INSERT INTO entry_entities (source, source_id, entity_type, entity_id) "
                "VALUES ('journal', ?, 'character', ?)",
                (jn_id, fighter),
            )
            db.commit()

            # Fighter sees it
            entries = _get_recent_journal(db, sid, npc_id=fighter)
            assert any("dragon" in e for e in entries)

            # Bystander doesn't
            entries = _get_recent_journal(db, sid, npc_id=bystander)
            assert not any("dragon" in e for e in entries)
        finally:
            db.close()
