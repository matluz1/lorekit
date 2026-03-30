"""Tests for core/npc_reflect.py -- NPC async reflection system."""

import json
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from lorekit.npc.reflect import (
    check_trigger,
    generate_reflection,
    get_unprocessed_memories,
    parse_reflection_output,
    prune_memories,
    reflect_all,
)


def _extract_id(result):
    m = re.search(r":\s*(\d+)", result)
    assert m, f"Could not extract ID from: {result}"
    return int(m.group(1))


@pytest.fixture
def make_npc(make_session):
    """Factory that creates an NPC and returns (session_id, npc_id)."""

    def _make(name="Test NPC", session_id=None):
        if session_id is None:
            session_id = make_session()
        from lorekit.tools.character import character_build

        result = character_build(session=session_id, name=name, level=1, type="npc")
        npc_id = _extract_id(result)
        return session_id, npc_id

    return _make


def _add_memory(db, session_id, npc_id, content, importance=0.5, memory_type="experience"):
    """Helper to add a memory directly via the module."""
    import lorekit.npc.memory as npc_memory

    return npc_memory.add_memory(
        db, session_id, npc_id, content, importance, memory_type, entities=[], narrative_time=""
    )


# ---------------------------------------------------------------------------
# Trigger tests
# ---------------------------------------------------------------------------


class TestCheckTrigger:
    def test_trigger_below_threshold(self, make_npc):
        """NPC with low-importance memories should not trigger."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            # Add memories totaling 4.0 importance (below default 5.0)
            for i in range(10):
                _add_memory(db, session_id, npc_id, f"Low importance event {i}", importance=0.4)
            assert check_trigger(db, session_id, npc_id) is False
        finally:
            db.close()

    def test_trigger_above_threshold(self, make_npc):
        """NPC with high-importance memories summing > 5.0 should trigger."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            for i in range(20):
                _add_memory(db, session_id, npc_id, f"Important event {i}", importance=0.9)
            assert check_trigger(db, session_id, npc_id) is True
        finally:
            db.close()

    def test_trigger_excludes_reflections(self, make_npc):
        """Existing reflection memories shouldn't count toward threshold."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            # Add a high-importance reflection
            _add_memory(db, session_id, npc_id, "A deep insight", importance=1.0, memory_type="reflection")
            # Add low-importance experience memories
            for i in range(5):
                _add_memory(db, session_id, npc_id, f"Minor event {i}", importance=0.5)
            # Total non-reflection importance = 2.5, well below 15.0
            assert check_trigger(db, session_id, npc_id) is False
        finally:
            db.close()

    def test_trigger_only_counts_since_last_reflection(self, make_npc):
        """Memories before the last reflection should be excluded."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            # Add old memories
            for i in range(20):
                _add_memory(db, session_id, npc_id, f"Old event {i}", importance=0.9)

            # Add a reflection (marks a boundary)
            _add_memory(db, session_id, npc_id, "Reflection insight", importance=0.9, memory_type="reflection")

            # Add just a few new memories after reflection
            for i in range(3):
                _add_memory(db, session_id, npc_id, f"New event {i}", importance=0.5)

            # Only new memories (1.5 total) should count
            assert check_trigger(db, session_id, npc_id) is False
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParseReflections:
    def test_parse_reflections(self):
        """Well-formed [REFLECTIONS] block parsed correctly."""
        text = (
            "[REFLECTIONS]\n"
            '- content: "The guild is manipulating events" | importance: 0.9 | sources: [1, 3]\n'
            '- content: "The party might be trustworthy" | importance: 0.8 | sources: [2]\n'
        )
        memory_id_map = {1: 101, 2: 102, 3: 103}
        result = parse_reflection_output(text, memory_id_map)
        assert len(result["reflections"]) == 2
        assert result["reflections"][0]["content"] == "The guild is manipulating events"
        assert result["reflections"][0]["importance"] == 0.9
        assert result["reflections"][0]["source_ids"] == [101, 103]
        assert result["reflections"][1]["source_ids"] == [102]

    def test_parse_behavioral_rules(self):
        """[BEHAVIORAL_RULES] block parsed correctly."""
        text = (
            "[BEHAVIORAL_RULES]\n"
            '- "When someone mentions the guild, become defensive"\n'
            '- "When the party asks for help, give them the benefit of the doubt"\n'
        )
        result = parse_reflection_output(text, {})
        assert len(result["behavioral_rules"]) == 2
        assert "guild" in result["behavioral_rules"][0]
        assert "benefit of the doubt" in result["behavioral_rules"][1]

    def test_parse_identity_updates(self):
        """[IDENTITY_UPDATES] block parsed correctly."""
        text = (
            "[IDENTITY_UPDATES]\n"
            '- self_concept: "A disillusioned former guard"\n'
            '- emotional_state: "wary and suspicious"\n'
        )
        result = parse_reflection_output(text, {})
        assert result["identity_updates"]["self_concept"] == "A disillusioned former guard"
        assert result["identity_updates"]["emotional_state"] == "wary and suspicious"

    def test_parse_missing_blocks(self):
        """Missing blocks → empty results, no crash."""
        text = "Some random text with no blocks."
        result = parse_reflection_output(text, {})
        assert result["reflections"] == []
        assert result["behavioral_rules"] == []
        assert result["identity_updates"] == {}

    def test_parse_malformed_lines(self):
        """Malformed lines are gracefully skipped."""
        text = (
            "[REFLECTIONS]\n"
            "- this is not valid\n"
            '- content: "Valid insight" | importance: 0.9 | sources: [1]\n'
            "- also broken | no content key\n"
        )
        memory_id_map = {1: 101}
        result = parse_reflection_output(text, memory_id_map)
        assert len(result["reflections"]) == 1
        assert result["reflections"][0]["content"] == "Valid insight"


# ---------------------------------------------------------------------------
# Integration tests (mock LLM)
# ---------------------------------------------------------------------------

CANNED_REFLECTION_OUTPUT = """[REFLECTIONS]
- content: "The party seems genuinely interested in helping" | importance: 0.9 | sources: [1, 2]
- content: "The guild's influence is waning in this region" | importance: 0.85 | sources: [3]

[BEHAVIORAL_RULES]
- "When the party asks about the guild, share information cautiously"

[IDENTITY_UPDATES]
- emotional_state: "cautiously hopeful"
"""


class TestGenerateReflection:
    @patch("lorekit.npc.reflect._call_llm", return_value=CANNED_REFLECTION_OUTPUT)
    def test_stores_memories(self, mock_llm, make_npc):
        """Reflections stored as memories with memory_type='reflection'."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            # Add some memories to reflect on
            for i in range(5):
                _add_memory(db, session_id, npc_id, f"Event {i}", importance=0.8)

            result = generate_reflection(db, session_id, npc_id)

            assert result["reflections_stored"] == 2
            assert result["rules_added"] == 1
            assert result["npc_name"] == "Test NPC"

            # Verify reflection memories in DB
            rows = db.execute(
                "SELECT content, memory_type, importance, source_ids FROM npc_memories "
                "WHERE npc_id = ? AND session_id = ? AND memory_type = 'reflection'",
                (npc_id, session_id),
            ).fetchall()
            assert len(rows) == 2
            assert rows[0][1] == "reflection"
            assert rows[0][2] >= 0.8
        finally:
            db.close()

    @patch("lorekit.npc.reflect._call_llm", return_value=CANNED_REFLECTION_OUTPUT)
    def test_updates_core(self, mock_llm, make_npc):
        """Behavioral rules merged into core; identity updates applied."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            for i in range(3):
                _add_memory(db, session_id, npc_id, f"Event {i}", importance=0.8)

            # Set existing behavioral patterns
            import lorekit.npc.memory as npc_memory

            npc_memory.set_core(db, session_id, npc_id, behavioral_patterns="- Be cautious with strangers")

            generate_reflection(db, session_id, npc_id)

            core = npc_memory.get_core(db, session_id, npc_id)
            assert "Be cautious with strangers" in core["behavioral_patterns"]
            assert "share information cautiously" in core["behavioral_patterns"]
            assert core["emotional_state"] == "cautiously hopeful"
        finally:
            db.close()

    @patch("lorekit.npc.reflect._call_llm")
    def test_no_memories_early_return(self, mock_llm, make_npc):
        """NPC with zero unprocessed memories → no LLM call."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            result = generate_reflection(db, session_id, npc_id)
            assert result["reflections_stored"] == 0
            mock_llm.assert_not_called()
        finally:
            db.close()


class TestReflectAll:
    @patch("lorekit.npc.reflect._call_llm", return_value=CANNED_REFLECTION_OUTPUT)
    def test_skips_below_threshold(self, mock_llm, make_session):
        """reflect_all with mixed NPCs only triggers for those above threshold."""
        sid = make_session()
        from lorekit.db import require_db
        from lorekit.tools.character import character_build

        # Create two NPCs
        npc1_id = _extract_id(character_build(session=sid, name="Active NPC", level=1, type="npc"))
        npc2_id = _extract_id(character_build(session=sid, name="Quiet NPC", level=1, type="npc"))

        db = require_db()
        try:
            # Active NPC: lots of important memories
            for i in range(20):
                _add_memory(db, sid, npc1_id, f"Important event {i}", importance=0.9)
            # Quiet NPC: just one low memory
            _add_memory(db, sid, npc2_id, "Minor thing", importance=0.3)

            result = reflect_all(db, sid)
            assert "Active NPC" in result
            assert "Quiet NPC" not in result or "Skipped 1" in result
            assert "Reflected on 1 NPC" in result
        finally:
            db.close()

    @patch("lorekit.npc.reflect._call_llm", return_value=CANNED_REFLECTION_OUTPUT)
    def test_session_end_threshold_zero(self, mock_llm, make_session):
        """threshold=0.0 reflects on all NPCs with any memories."""
        sid = make_session()
        from lorekit.db import require_db
        from lorekit.tools.character import character_build

        npc1_id = _extract_id(character_build(session=sid, name="NPC1", level=1, type="npc"))
        npc2_id = _extract_id(character_build(session=sid, name="NPC2", level=1, type="npc"))

        db = require_db()
        try:
            _add_memory(db, sid, npc1_id, "Small event", importance=0.3)
            _add_memory(db, sid, npc2_id, "Another event", importance=0.2)

            result = reflect_all(db, sid, threshold=0.0, context_hint="Session ended")
            assert "Reflected on 2 NPCs" in result
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Pruning tests
# ---------------------------------------------------------------------------


class TestPruneMemories:
    def test_prune_old_unimportant_unaccessed(self, make_npc):
        """Memories matching all 3 criteria are pruned."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            # Insert a memory with narrative_time > 38 in-game days before "now"
            db.execute(
                "INSERT INTO npc_memories (session_id, npc_id, content, importance, memory_type, "
                "entities, narrative_time, access_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, npc_id, "Forgettable thing", 0.1, "observation", "[]", "1347-01-01T10:00", 0),
            )
            db.commit()

            # Prune with narrative_now 45 days later
            count = prune_memories(db, session_id, npc_id, narrative_now="1347-02-15T10:00")
            assert count == 1

            # Verify it's gone
            rows = db.execute(
                "SELECT id FROM npc_memories WHERE npc_id = ? AND content = 'Forgettable thing'",
                (npc_id,),
            ).fetchall()
            assert len(rows) == 0
        finally:
            db.close()

    def test_prune_spares_important(self, make_npc):
        """Old + unaccessed but high importance → kept."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            db.execute(
                "INSERT INTO npc_memories (session_id, npc_id, content, importance, memory_type, "
                "entities, narrative_time, access_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, npc_id, "Important old memory", 0.8, "experience", "[]", "1347-01-01T10:00", 0),
            )
            db.commit()

            count = prune_memories(db, session_id, npc_id, narrative_now="1347-02-15T10:00")
            assert count == 0
        finally:
            db.close()

    def test_prune_spares_accessed(self, make_npc):
        """Old + low importance but accessed → kept."""
        session_id, npc_id = make_npc()
        from lorekit.db import require_db

        db = require_db()
        try:
            db.execute(
                "INSERT INTO npc_memories (session_id, npc_id, content, importance, memory_type, "
                "entities, narrative_time, access_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, npc_id, "Accessed memory", 0.1, "observation", "[]", "1347-01-01T10:00", 3),
            )
            db.commit()

            count = prune_memories(db, session_id, npc_id, narrative_now="1347-02-15T10:00")
            assert count == 0
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Auto-trigger tests (via MCP tools)
# ---------------------------------------------------------------------------


class TestAutoTriggers:
    @patch("lorekit.npc.reflect.reflect_all", return_value="REFLECTIONS: Reflected on 1 NPCs (NPC: 2 insights).")
    def test_time_advance_triggers_reflection(self, mock_reflect, make_session):
        """Advancing > 7 days triggers reflect_all."""
        sid = make_session()
        from lorekit.tools.narrative import time_advance
        from lorekit.tools.session import session_meta_set

        # Need narrative time set first
        session_meta_set(session_id=sid, key="narrative_time", value="1347-03-15T14:00")

        result = time_advance(session_id=sid, amount=10, unit="days")
        assert "REFLECTIONS:" in result
        mock_reflect.assert_called_once()
        # Verify context_hint was passed
        call_kwargs = mock_reflect.call_args
        assert "10 days have passed" in call_kwargs.kwargs.get("context_hint", call_kwargs[1].get("context_hint", ""))

    @patch("lorekit.npc.reflect.reflect_all")
    def test_time_advance_small_skip_checks_threshold(self, mock_reflect, make_session):
        """Any time advance calls reflect_all (threshold gates actual reflection)."""
        sid = make_session()
        from lorekit.tools.narrative import time_advance
        from lorekit.tools.session import session_meta_set

        session_meta_set(session_id=sid, key="narrative_time", value="1347-03-15T14:00")

        result = time_advance(session_id=sid, amount=2, unit="hours")
        mock_reflect.assert_called_once()

    @patch("lorekit.npc.reflect.reflect_all", return_value="REFLECTIONS: Reflected on 1 NPCs.")
    def test_session_update_finished_triggers(self, mock_reflect, make_session):
        """Status='finished' triggers reflect_all with threshold=0.0."""
        sid = make_session()
        from lorekit.tools.session import session_update

        result = session_update(session_id=sid, status="finished")
        mock_reflect.assert_called_once()
        call_args = mock_reflect.call_args
        # threshold should be 0.0
        assert call_args.kwargs.get("threshold", call_args[1].get("threshold")) == 0.0

    @patch("lorekit.npc.reflect.reflect_all")
    def test_session_update_active_no_trigger(self, mock_reflect, make_session):
        """Status='active' should not trigger reflection."""
        sid = make_session()
        from lorekit.tools.session import session_update

        session_update(session_id=sid, status="active")
        mock_reflect.assert_not_called()
