"""Integration tests: NPC prefetch context accumulation.

Verify that assemble_context respects token budgets, boosts entity-matched
memories, and includes core identity in the assembled context.
"""

import os

import pytest

pytest.importorskip("sqlite_vec")

from lorekit.npc.prefetch import assemble_context  # noqa: E402
from lorekit.tools.npc import npc_memory_add  # noqa: E402


def _get_db():
    from lorekit.db import get_db

    return get_db(os.environ["LOREKIT_DB"])


class TestPrefetchIncludesHighImportanceMemories:
    def test_prefetch_includes_high_importance_memories(self, make_session, make_character):
        sid = make_session()
        npc_id = make_character(sid, name="Guard", char_type="npc")

        for i in range(10):
            importance = round((i + 1) / 10, 1)
            npc_memory_add(
                session_id=sid,
                npc_id=npc_id,
                content=f"Memory number {i + 1} with importance {importance}",
                importance=importance,
                memory_type="experience",
                entities="[]",
                narrative_time="1347-03-15T14:00",
            )

        db = _get_db()
        try:
            result = assemble_context(db, sid, npc_id, "Tell me about yourself", narrative_time="1347-03-15T14:00")
        finally:
            db.close()

        high_importance_contents = [
            f"Memory number {i + 1} with importance {round((i + 1) / 10, 1)}"
            for i in range(10)
            if round((i + 1) / 10, 1) >= 0.7
        ]

        found_high = any(c in result.context for c in high_importance_contents)
        assert found_high, "Expected at least one high-importance memory (>= 0.7) in context"

        assert result.debug["memories_included"] > 0


class TestPrefetchRespectsTokenBudget:
    def test_prefetch_respects_token_budget(self, make_session, make_character):
        sid = make_session()
        npc_id = make_character(sid, name="Guard", char_type="npc")

        long_content = "A" * 200
        for i in range(20):
            npc_memory_add(
                session_id=sid,
                npc_id=npc_id,
                content=f"Memory {i + 1}: {long_content}",
                importance=0.5,
                memory_type="experience",
                entities="[]",
                narrative_time="1347-03-15T14:00",
            )

        db = _get_db()
        try:
            result = assemble_context(
                db,
                sid,
                npc_id,
                "Tell me about yourself",
                narrative_time="1347-03-15T14:00",
                token_budget=500,
            )
        finally:
            db.close()

        assert result.debug["total_tokens"] <= 500
        assert result.debug["memories_included"] < 20


class TestPrefetchEntityMatchBoostsRelevance:
    def test_prefetch_entity_match_boosts_relevance(self, make_session, make_character):
        sid = make_session()
        npc_id = make_character(sid, name="Guard", char_type="npc")
        make_character(sid, name="Valeros", char_type="pc")

        valeros_contents = [
            "Valeros helped defend the gate last winter",
            "Valeros repaid a debt he owed to the guard",
            "Valeros has always been respectful at checkpoints",
        ]
        for content in valeros_contents:
            npc_memory_add(
                session_id=sid,
                npc_id=npc_id,
                content=content,
                importance=0.3,
                memory_type="experience",
                entities='["Valeros"]',
                narrative_time="1347-03-15T14:00",
            )

        random_contents = [
            "The eastern wall needs repair after the storm",
            "Grain shipments were delayed by bandits on the road",
            "The captain issued new patrol schedules this week",
        ]
        for content in random_contents:
            npc_memory_add(
                session_id=sid,
                npc_id=npc_id,
                content=content,
                importance=0.9,
                memory_type="experience",
                entities="[]",
                narrative_time="1347-03-15T14:00",
            )

        db = _get_db()
        try:
            result = assemble_context(
                db,
                sid,
                npc_id,
                "What do you think of Valeros?",
                narrative_time="1347-03-15T14:00",
            )
        finally:
            db.close()

        found_valeros = any(c in result.context for c in valeros_contents)
        assert found_valeros, "Expected at least one Valeros-related memory in context despite low importance"


class TestPrefetchWithCoreIdentity:
    def test_prefetch_with_core_identity(self, make_session, make_character):
        sid = make_session()
        npc_id = make_character(sid, name="Guard", char_type="npc")

        db = _get_db()
        db.execute(
            "INSERT INTO npc_core (session_id, npc_id, self_concept, emotional_state, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (sid, npc_id, "I am a veteran city guard", "vigilant"),
        )
        db.commit()
        db.close()

        db = _get_db()
        try:
            result = assemble_context(db, sid, npc_id, "Who are you?", narrative_time="1347-03-15T14:00")
        finally:
            db.close()

        assert "veteran city guard" in result.context
