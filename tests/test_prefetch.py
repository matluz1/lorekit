"""Tests for Deterministic Pre-fetch Pipeline."""

import json
import re

import pytest


def _extract_id(result):
    m = re.search(r":\s*(\d+)", result)
    assert m, f"Could not extract ID from: {result}"
    return int(m.group(1))


@pytest.fixture
def make_npc(make_session, npc_model):
    """Factory that creates an NPC and returns (session_id, npc_id)."""

    def _make(name="Test NPC", session_id=None, core=None, aliases=None, model=None):
        if session_id is None:
            session_id = make_session()
        from lorekit.server import character_build

        kwargs = dict(session=session_id, name=name, level=1, type="npc")
        if core:
            kwargs["core"] = json.dumps(core)
        if aliases:
            kwargs["aliases"] = json.dumps(aliases)
        result = character_build(**kwargs)
        npc_id = _extract_id(result)
        effective_model = model or npc_model
        if effective_model:
            from lorekit.character import set_attr
            from lorekit.db import require_db

            _db = require_db()
            set_attr(_db, npc_id, "system", "model", effective_model)
            _db.commit()
            _db.close()
        return session_id, npc_id

    return _make


@pytest.fixture
def seed_memories(make_npc):
    """Create an NPC with core identity and several memories, return (session_id, npc_id)."""

    def _seed():
        session_id, npc_id = make_npc(
            name="Roderick",
            core={
                "self_concept": "A distrustful merchant who values honesty above all",
                "current_goals": "Find the stolen artifact before the guild does",
                "emotional_state": "Anxious but determined",
                "relationships": json.dumps({"Mira": "A trusted ally", "Guild": "Enemies"}),
                "behavioral_patterns": json.dumps(
                    ["When the guild is mentioned, become defensive", "When trading, always verify the goods first"]
                ),
            },
            aliases=["Rod", "the merchant"],
        )

        from lorekit.server import npc_memory_add

        memories = [
            ("The hero saved my village from bandits", 0.9, "experience", '["Hero", "Village"]'),
            ("Mira warned me about the guild's plans", 0.8, "relationship", '["Mira", "Guild"]'),
            ("I overheard soldiers talking about war", 0.6, "observation", '["soldiers"]'),
            ("Traded spices for a good price", 0.2, "experience", '["market"]'),
            ("The artifact is hidden in the old temple", 0.95, "experience", '["artifact", "temple"]'),
            ("A stranger asked too many questions", 0.4, "observation", '["stranger"]'),
        ]
        for content, importance, mem_type, entities in memories:
            npc_memory_add(
                session_id=session_id,
                npc_id=npc_id,
                content=content,
                importance=importance,
                memory_type=mem_type,
                entities=entities,
                narrative_time="1347-03-15T14:00",
            )

        return session_id, npc_id

    return _seed


# ---------------------------------------------------------------------------
# Character aliases
# ---------------------------------------------------------------------------


class TestCharacterAliases:
    def test_build_with_aliases(self, make_session):
        """character_build with aliases creates alias rows."""
        sid = make_session()
        from lorekit.server import character_build

        result = character_build(
            session=sid,
            name="Bartender Bob",
            level=1,
            type="npc",
            aliases='["Bob", "the bartender"]',
        )
        assert "aliases=2" in result
        npc_id = _extract_id(result)

        from lorekit.db import require_db

        db = require_db()
        aliases = db.execute(
            "SELECT alias FROM character_aliases WHERE character_id = ? ORDER BY alias",
            (npc_id,),
        ).fetchall()
        db.close()
        assert [r[0] for r in aliases] == ["Bob", "the bartender"]

    def test_sheet_update_aliases(self, make_npc):
        """character_sheet_update replaces aliases."""
        session_id, npc_id = make_npc(name="Merchant", aliases=["Merch"])

        from lorekit.server import character_sheet_update

        result = character_sheet_update(
            character_id=npc_id,
            aliases='["Trader", "Shop Guy"]',
        )
        assert "ALIASES_SET: 2" in result

        from lorekit.db import require_db

        db = require_db()
        aliases = db.execute(
            "SELECT alias FROM character_aliases WHERE character_id = ? ORDER BY alias",
            (npc_id,),
        ).fetchall()
        db.close()
        # Old alias "Merch" should be replaced
        assert sorted(r[0] for r in aliases) == ["Shop Guy", "Trader"]

    def test_resolve_by_alias(self, make_npc):
        """_resolve_character finds character by alias."""
        session_id, npc_id = make_npc(name="Bartender Bob", aliases=["Bob"])

        from lorekit.db import require_db

        db = require_db()
        from lorekit.server import _resolve_character

        resolved = _resolve_character(db, "Bob", session_id)
        db.close()
        assert resolved == npc_id


# ---------------------------------------------------------------------------
# Entity tagging
# ---------------------------------------------------------------------------


class TestEntityTagging:
    def test_turn_save_auto_tags(self, make_session, make_character):
        """turn_save auto-tags characters mentioned in narration."""
        sid = make_session()
        pc_id = make_character(sid, name="Valeria")

        from lorekit.server import turn_save

        result = turn_save(
            session_id=sid,
            narration="Valeria enters the tavern and looks around cautiously.",
            summary="Valeria enters tavern",
        )
        assert "TIMELINE_ADDED" in result
        tl_id = int(result.split("TIMELINE_ADDED: ")[1].split("\n")[0])

        from lorekit.db import require_db

        db = require_db()
        tags = db.execute(
            "SELECT entity_type, entity_id FROM entry_entities WHERE source = 'timeline' AND source_id = ?",
            (tl_id,),
        ).fetchall()
        db.close()
        assert ("character", pc_id) in tags

    def test_entry_untag(self, make_session, make_character):
        """entry_untag removes a tag."""
        sid = make_session()
        pc_id = make_character(sid, name="Valeria")

        from lorekit.server import entry_untag, turn_save

        turn_save(
            session_id=sid,
            narration="Valeria fights the dragon",
            summary="Dragon fight",
        )

        from lorekit.db import require_db

        db = require_db()
        tl_id = db.execute("SELECT MAX(id) FROM timeline WHERE session_id = ?", (sid,)).fetchone()[0]
        tags_before = db.execute(
            "SELECT COUNT(*) FROM entry_entities WHERE source = 'timeline' AND source_id = ?",
            (tl_id,),
        ).fetchone()[0]
        db.close()
        assert tags_before > 0

        result = entry_untag(source="timeline", source_id=tl_id, entity_type="character", entity_id=pc_id)
        assert result == "ENTRY_UNTAGGED"

        db = require_db()
        tags_after = db.execute(
            "SELECT COUNT(*) FROM entry_entities WHERE source = 'timeline' AND source_id = ? "
            "AND entity_type = 'character' AND entity_id = ?",
            (tl_id, pc_id),
        ).fetchone()[0]
        db.close()
        assert tags_after == 0


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------


class TestEntityExtraction:
    def test_extracts_character_names(self, make_session, make_character):
        """extract_entities finds character names in text (case-insensitive)."""
        sid = make_session()
        pc_id = make_character(sid, name="Valeria")
        npc_id = make_character(sid, name="Roderick", char_type="npc")

        from lorekit.db import require_db
        from lorekit.npc.prefetch import extract_entities

        db = require_db()
        result = extract_entities(db, sid, "Valeria talks to roderick about the war")
        db.close()

        assert pc_id in result["character_ids"]
        assert npc_id in result["character_ids"]

    def test_extracts_aliases(self, make_npc):
        """extract_entities finds characters by alias."""
        session_id, npc_id = make_npc(name="Bartender Bob", aliases=["Bob", "the bartender"])

        from lorekit.db import require_db
        from lorekit.npc.prefetch import extract_entities

        db = require_db()
        result = extract_entities(db, session_id, "I want to talk to Bob")
        db.close()

        assert npc_id in result["character_ids"]

    def test_extracts_regions(self, make_session, make_region):
        """extract_entities finds region names."""
        sid = make_session()
        region_id = make_region(sid, name="Dragon's Peak")

        from lorekit.db import require_db
        from lorekit.npc.prefetch import extract_entities

        db = require_db()
        result = extract_entities(db, sid, "We should head to Dragon's Peak")
        db.close()

        assert region_id in result["region_ids"]

    def test_no_entities(self, make_session):
        """Returns empty when no entities match."""
        sid = make_session()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import extract_entities

        db = require_db()
        result = extract_entities(db, sid, "Hello there")
        db.close()

        assert result["character_ids"] == []
        assert result["region_ids"] == []
        assert result["matched_names"] == []


# ---------------------------------------------------------------------------
# Pre-fetch pipeline
# ---------------------------------------------------------------------------


class TestPreFetch:
    def test_returns_prefetch_result(self, seed_memories):
        """assemble_context returns PreFetchResult with context and debug."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import PreFetchResult, assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "Tell me about the artifact")
        db.close()

        assert isinstance(result, PreFetchResult)
        assert isinstance(result.context, str)
        assert isinstance(result.debug, dict)
        assert len(result.context) > 0

    def test_core_identity_in_context(self, seed_memories):
        """Pre-fetched context includes NPC core identity."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "Hello")
        db.close()

        assert "distrustful merchant" in result.context
        assert "Find the stolen artifact" in result.context
        assert "Anxious but determined" in result.context

    def test_hot_memories_always_included(self, seed_memories):
        """Memories with importance > 0.7 appear in context."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "What's new?")
        db.close()

        # High-importance memories should be present
        assert "artifact is hidden in the old temple" in result.context
        assert "hero saved my village" in result.context

    def test_entity_matched_memories(self, seed_memories):
        """Mentioning an entity surfaces related memories."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "What do you know about Mira?")
        db.close()

        assert "Mira warned me" in result.context

    def test_fallback_recent_memories(self, seed_memories):
        """When no entities match, recent memories are included as fallback."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "How are you today?")
        db.close()

        assert result.debug["fallback_used"] is True
        # Should still have memories in context (from hot + fallback)
        assert "Your Memories" in result.context

    def test_debug_has_required_fields(self, seed_memories):
        """Debug dict contains all expected diagnostic fields."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "Tell me about the artifact")
        db.close()

        d = result.debug
        assert "npc_id" in d
        assert "session_id" in d
        assert "token_budget" in d
        assert "core_tokens" in d
        assert "hot_count" in d
        assert "entities" in d
        assert "candidate_count" in d
        assert "scored_count" in d
        assert "memory_tokens" in d
        assert "timeline_tokens" in d
        assert "total_tokens" in d
        assert "memories_included" in d

    def test_token_budget_respected(self, seed_memories):
        """Total tokens should not exceed budget."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "Tell me everything", token_budget=500)
        db.close()

        assert result.debug["total_tokens"] <= 500

    def test_deduplication(self, seed_memories):
        """Memories appearing in multiple retrieval paths are not duplicated."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        # "artifact" appears in hot memories AND entity-matched (entities contain "artifact")
        result = assemble_context(db, session_id, npc_id, "Tell me about the artifact")
        db.close()

        # Count occurrences of the artifact memory
        count = result.context.count("artifact is hidden in the old temple")
        assert count == 1

    def test_access_count_updated(self, seed_memories):
        """Retrieved memories get their access_count incremented."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        # Check initial access count
        initial = db.execute(
            "SELECT access_count FROM npc_memories WHERE npc_id = ? AND session_id = ? LIMIT 1",
            (npc_id, session_id),
        ).fetchone()[0]

        assemble_context(db, session_id, npc_id, "Hello")

        after = db.execute(
            "SELECT access_count FROM npc_memories WHERE npc_id = ? AND session_id = ? LIMIT 1",
            (npc_id, session_id),
        ).fetchone()[0]
        db.close()

        assert after > initial

    def test_empty_npc_no_crash(self, make_npc):
        """NPC with no memories or core identity returns valid result."""
        session_id, npc_id = make_npc()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "Hello stranger")
        db.close()

        assert isinstance(result.context, str)
        assert result.debug["hot_count"] == 0
        assert result.debug["candidate_count"] == 0

    def test_behavioral_patterns_in_context(self, seed_memories):
        """Behavioral patterns from npc_core appear in context."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "Let's trade")
        db.close()

        assert "When the guild is mentioned" in result.context
        assert "When trading" in result.context

    def test_relationships_in_context(self, seed_memories):
        """Relationships from npc_core appear in context."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "Hello")
        db.close()

        assert "Mira" in result.context
        assert "trusted ally" in result.context

    def test_timeline_in_context(self, seed_memories):
        """Recent timeline entries appear in context."""
        session_id, npc_id = seed_memories()

        from lorekit.server import turn_save

        turn_save(
            session_id=session_id,
            narration="The party arrived at the village gate.",
            summary="Party arrives at village",
            scope="all",
        )

        from lorekit.db import require_db
        from lorekit.npc.prefetch import assemble_context

        db = require_db()
        result = assemble_context(db, session_id, npc_id, "What's happening?")
        db.close()

        assert "Recent Events" in result.context
        assert "Party arrives at village" in result.context


# ---------------------------------------------------------------------------
# NPC prompt integration
# ---------------------------------------------------------------------------


class TestNpcPromptIntegration:
    def test_build_npc_prompt_includes_prefetch(self, seed_memories):
        """_build_npc_prompt includes pre-fetched context in system prompt."""
        session_id, npc_id = seed_memories()

        from lorekit.db import require_db
        from lorekit.server import _build_npc_prompt

        db = require_db()
        import sqlite3

        db.row_factory = sqlite3.Row
        result = _build_npc_prompt(db, npc_id, session_id, gm_message="Tell me about the artifact")
        db.close()

        assert result is not None
        system_prompt, model, npc_name = result
        assert "distrustful merchant" in system_prompt
        assert "artifact is hidden" in system_prompt
        assert npc_name == "Roderick"

    def test_npc_allowed_tools_empty(self):
        """NPCs should have no allowed tools."""
        from lorekit.server import _NPC_ALLOWED_TOOLS

        assert _NPC_ALLOWED_TOOLS == []
