"""prefetch.py -- Deterministic NPC context pre-fetch pipeline.

Assembles a rich context for NPC activation in pure Python (no LLM calls).
The goal: NPC acts in one think cycle with all relevant context pre-loaded.

Pipeline steps:
  1. Load core identity (npc_core)
  2. Load hot memories (importance > 0.7)
  3. Parse invocation context (entity extraction, compute embedding)
  4. Warm retrieval (entity-matched, vector, timeline, journal)
  5. Score and rank (Park+ACT-R formula), deduplicate, update access_count
  6. Token-budget assembly (greedy fill by score rank)
"""

import json
import logging

import lorekit.npc.memory as npc_memory

logger = logging.getLogger("lorekit.prefetch")

# Approximate tokens per character (conservative estimate for mixed content)
_CHARS_PER_TOKEN = 4
# Default context budget in tokens
DEFAULT_TOKEN_BUDGET = 6000
# Reserve for identity + overhead sections
_IDENTITY_RESERVE = 1500
# Minimum memories to always include (even if budget is tight)
_MIN_MEMORIES = 3
# Hot memory threshold
_HOT_IMPORTANCE = 0.7
# Recent memory fallback count (when zero entities extracted)
_FALLBACK_RECENT = 10


class PreFetchResult:
    """Result of the pre-fetch pipeline."""

    __slots__ = ("context", "debug")

    def __init__(self, context: str, debug: dict):
        self.context = context
        self.debug = debug


def _estimate_tokens(text: str) -> int:
    """Estimate token count from character length."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# Step 3: Entity extraction
# ---------------------------------------------------------------------------


def extract_entities(db, session_id: int, text: str) -> dict:
    """Extract known entity names from text via case-insensitive substring match.

    Returns dict with keys:
      - character_ids: list of matched character IDs
      - region_ids: list of matched region IDs
      - matched_names: list of (name, entity_type, entity_id) tuples
    """
    text_lower = text.lower()
    character_ids = []
    region_ids = []
    matched_names = []

    # Load all character names + aliases for this session
    chars = db.execute(
        "SELECT id, name FROM characters WHERE session_id = ?",
        (session_id,),
    ).fetchall()

    for char_id, name in chars:
        if name.lower() in text_lower:
            character_ids.append(char_id)
            matched_names.append((name, "character", char_id))

    # Check aliases
    alias_rows = db.execute(
        """SELECT ca.character_id, ca.alias
           FROM character_aliases ca
           JOIN characters c ON c.id = ca.character_id
           WHERE c.session_id = ?""",
        (session_id,),
    ).fetchall()

    for char_id, alias in alias_rows:
        if alias.lower() in text_lower and char_id not in character_ids:
            character_ids.append(char_id)
            matched_names.append((alias, "character", char_id))

    # Load region names
    regions = db.execute(
        "SELECT id, name FROM regions WHERE session_id = ?",
        (session_id,),
    ).fetchall()

    for region_id, name in regions:
        if name.lower() in text_lower:
            region_ids.append(region_id)
            matched_names.append((name, "region", region_id))

    return {
        "character_ids": character_ids,
        "region_ids": region_ids,
        "matched_names": matched_names,
    }


# ---------------------------------------------------------------------------
# Step 4: Warm retrieval
# ---------------------------------------------------------------------------


def _get_entity_memories(db, npc_id: int, session_id: int, entity_names: list[str]) -> list[dict]:
    """Retrieve memories whose entities JSON contains any of the given names."""
    if not entity_names:
        return []

    rows = db.execute(
        "SELECT id, content, importance, memory_type, entities, narrative_time, "
        "access_count, last_accessed, source_ids, created_at "
        "FROM npc_memories WHERE npc_id = ? AND session_id = ?",
        (npc_id, session_id),
    ).fetchall()

    entity_names_lower = {n.lower() for n in entity_names}
    results = []
    for r in rows:
        entities_json = r[4]
        if entities_json:
            try:
                entities = json.loads(entities_json)
                if any(e.lower() in entity_names_lower for e in entities if isinstance(e, str)):
                    results.append(_row_to_memory(r))
            except (json.JSONDecodeError, TypeError):
                pass
    return results


def _get_vector_memories(db, npc_id: int, session_id: int, query_embedding, limit: int = 20) -> list[dict]:
    """Retrieve memories by vector similarity to query embedding."""
    if query_embedding is None:
        return []

    try:
        from lorekit.support.vectordb import _has_vec_table, _serialize

        if not _has_vec_table(db):
            return []

        blob = _serialize(query_embedding)
        fetch_k = limit * 5

        rows = db.execute(
            """
            SELECT e.source_id, v.distance
            FROM (
                SELECT rowid, distance
                FROM vec_embeddings
                WHERE embedding MATCH ? AND k = ?
            ) v
            JOIN embeddings e ON e.id = v.rowid
            WHERE e.source = 'npc_memory'
              AND e.session_id = ?
              AND e.npc_id = ?
            """,
            (blob, fetch_k, session_id, npc_id),
        ).fetchall()

        if not rows:
            return []

        memory_ids = [r[0] for r in rows[:limit]]
        distances = {r[0]: r[1] for r in rows[:limit]}

        if not memory_ids:
            return []

        placeholders = ",".join("?" * len(memory_ids))
        mem_rows = db.execute(
            f"SELECT id, content, importance, memory_type, entities, narrative_time, "
            f"access_count, last_accessed, source_ids, created_at "
            f"FROM npc_memories WHERE id IN ({placeholders})",
            memory_ids,
        ).fetchall()

        results = []
        for r in mem_rows:
            m = _row_to_memory(r)
            m["_distance"] = distances.get(r[0], 1.0)
            results.append(m)
        return results
    except Exception:
        return []


def _get_recent_memories(db, npc_id: int, session_id: int, limit: int = _FALLBACK_RECENT) -> list[dict]:
    """Retrieve most recent memories by narrative_time (fallback when no entities found)."""
    rows = db.execute(
        "SELECT id, content, importance, memory_type, entities, narrative_time, "
        "access_count, last_accessed, source_ids, created_at "
        "FROM npc_memories WHERE npc_id = ? AND session_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (npc_id, session_id, limit),
    ).fetchall()
    return [_row_to_memory(r) for r in rows]


def _get_recent_timeline(db, session_id: int, limit: int = 10) -> list[str]:
    """Get recent timeline entries as formatted strings."""
    rows = db.execute(
        "SELECT entry_type, content, summary FROM timeline WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    entries = []
    for entry_type, content, summary in reversed(rows):
        text = summary or content[:200]
        entries.append(f"- {text}")
    return entries


def _row_to_memory(row) -> dict:
    """Convert a DB row tuple to a memory dict."""
    return {
        "id": row[0],
        "content": row[1],
        "importance": row[2],
        "memory_type": row[3],
        "entities": row[4],
        "narrative_time": row[5],
        "access_count": row[6],
        "last_accessed": row[7],
        "source_ids": row[8],
        "created_at": row[9],
    }


# ---------------------------------------------------------------------------
# Step 5: Score and deduplicate
# ---------------------------------------------------------------------------


def _attach_embeddings(db, memories: list[dict]) -> list[dict]:
    """Load embedding vectors for memories from the embeddings table."""
    if not memories:
        return memories

    try:
        from lorekit.support.vectordb import _has_vec_table

        if not _has_vec_table(db):
            return memories

        import struct

        memory_ids = [m["id"] for m in memories]
        placeholders = ",".join("?" * len(memory_ids))

        rows = db.execute(
            f"""SELECT e.source_id, v.embedding
                FROM embeddings e
                JOIN vec_embeddings v ON v.rowid = e.id
                WHERE e.source = 'npc_memory' AND e.source_id IN ({placeholders})""",
            memory_ids,
        ).fetchall()

        emb_map = {}
        for source_id, blob in rows:
            if blob:
                n_floats = len(blob) // 4
                vec = list(struct.unpack(f"{n_floats}f", blob))
                emb_map[source_id] = vec

        for m in memories:
            m["embedding"] = emb_map.get(m["id"])

        return memories
    except Exception:
        return memories


def _deduplicate(memories: list[dict]) -> list[dict]:
    """Remove duplicate memories by ID."""
    seen = set()
    result = []
    for m in memories:
        mid = m["id"]
        if mid not in seen:
            seen.add(mid)
            result.append(m)
    return result


def _update_access_counts(db, memory_ids: list[int], narrative_time: str):
    """Increment access_count and update last_accessed for retrieved memories."""
    if not memory_ids:
        return
    for mid in memory_ids:
        db.execute(
            "UPDATE npc_memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
            (narrative_time or "", mid),
        )
    db.commit()


# ---------------------------------------------------------------------------
# Step 6: Token-budget assembly
# ---------------------------------------------------------------------------


def _format_core_identity(core: dict | None) -> str:
    """Format npc_core as a prompt section."""
    if not core:
        return ""

    lines = ["## Your Identity"]
    if core.get("self_concept"):
        lines.append(f"Self-concept: {core['self_concept']}")
    if core.get("current_goals"):
        lines.append(f"Current goals: {core['current_goals']}")
    if core.get("emotional_state"):
        lines.append(f"Emotional state: {core['emotional_state']}")
    if core.get("relationships"):
        try:
            rels = (
                json.loads(core["relationships"]) if isinstance(core["relationships"], str) else core["relationships"]
            )
            if isinstance(rels, dict) and rels:
                lines.append("Relationships:")
                for name, desc in rels.items():
                    lines.append(f"  - {name}: {desc}")
        except (json.JSONDecodeError, TypeError):
            pass
    if core.get("behavioral_patterns"):
        try:
            patterns = (
                json.loads(core["behavioral_patterns"])
                if isinstance(core["behavioral_patterns"], str)
                else core["behavioral_patterns"]
            )
            if isinstance(patterns, list) and patterns:
                lines.append("Behavioral rules:")
                for p in patterns:
                    lines.append(f"  - {p}")
        except (json.JSONDecodeError, TypeError):
            pass

    return "\n".join(lines)


def _format_memories(scored_memories: list[tuple[dict, float]], token_budget: int) -> tuple[str, int]:
    """Format scored memories into a prompt section within token budget.

    Returns (formatted_text, tokens_used).
    """
    if not scored_memories:
        return "", 0

    lines = ["## Your Memories"]
    tokens_used = _estimate_tokens(lines[0])

    for i, (m, score) in enumerate(scored_memories):
        line = f"- [{m['memory_type']}] {m['content']}"
        line_tokens = _estimate_tokens(line)

        if tokens_used + line_tokens > token_budget and i >= _MIN_MEMORIES:
            break

        lines.append(line)
        tokens_used += line_tokens

    return "\n".join(lines), tokens_used


def _format_timeline(entries: list[str], token_budget: int) -> tuple[str, int]:
    """Format timeline entries within token budget."""
    if not entries:
        return "", 0

    lines = ["## Recent Events"]
    tokens_used = _estimate_tokens(lines[0])

    for entry in entries:
        entry_tokens = _estimate_tokens(entry)
        if tokens_used + entry_tokens > token_budget:
            break
        lines.append(entry)
        tokens_used += entry_tokens

    return "\n".join(lines), tokens_used


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def assemble_context(
    db,
    session_id: int,
    npc_id: int,
    gm_message: str,
    narrative_time: str = "",
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    noise: float = 0.0,
) -> PreFetchResult:
    """Run the full pre-fetch pipeline and return assembled NPC context.

    Args:
        db: database connection
        session_id: current session ID
        npc_id: NPC character ID
        gm_message: the GM's invocation message (used for entity extraction + embedding)
        narrative_time: current in-game time
        token_budget: max tokens for the assembled context
        noise: scoring noise parameter (0 = deterministic)

    Returns:
        PreFetchResult with .context (prompt string) and .debug (diagnostics)
    """
    debug = {
        "npc_id": npc_id,
        "session_id": session_id,
        "token_budget": token_budget,
    }

    # Step 1: Load core identity
    core = npc_memory.get_core(db, session_id, npc_id)
    core_text = _format_core_identity(core)
    core_tokens = _estimate_tokens(core_text) if core_text else 0
    debug["core_tokens"] = core_tokens

    # Step 2: Load hot memories (importance > threshold)
    hot_memories = npc_memory.get_memories(db, npc_id, session_id, limit=20, min_importance=_HOT_IMPORTANCE)
    debug["hot_count"] = len(hot_memories)

    # Step 3: Parse invocation context
    entities = extract_entities(db, session_id, gm_message)
    debug["entities"] = entities["matched_names"]

    # Compute query embedding
    query_embedding = None
    try:
        from lorekit.support.vectordb import _embed_query

        query_embedding = _embed_query(gm_message)
    except Exception:
        pass
    debug["has_query_embedding"] = query_embedding is not None

    # Step 4: Warm retrieval
    entity_names = [name for name, _, _ in entities["matched_names"]]
    entity_memories = _get_entity_memories(db, npc_id, session_id, entity_names)
    vector_memories = _get_vector_memories(db, npc_id, session_id, query_embedding)

    # Fallback: if no entities found, include recent memories
    fallback_memories = []
    if not entities["matched_names"]:
        fallback_memories = _get_recent_memories(db, npc_id, session_id)
        debug["fallback_used"] = True
    else:
        debug["fallback_used"] = False

    # Combine all candidate memories
    all_candidates = hot_memories + entity_memories + vector_memories + fallback_memories
    all_candidates = _deduplicate(all_candidates)
    debug["candidate_count"] = len(all_candidates)

    # Step 5: Score and rank
    all_candidates = _attach_embeddings(db, all_candidates)
    scored = npc_memory.score_memories(all_candidates, query_embedding, narrative_time, noise=noise)
    debug["scored_count"] = len(scored)

    # Timeline context
    timeline_entries = _get_recent_timeline(db, session_id)

    # Step 6: Token-budget assembly
    remaining_budget = token_budget - core_tokens

    # Allocate: 70% memories, 30% timeline
    memory_budget = int(remaining_budget * 0.7)
    timeline_budget = remaining_budget - memory_budget

    memories_text, mem_tokens = _format_memories(scored, memory_budget)
    timeline_text, tl_tokens = _format_timeline(timeline_entries, timeline_budget)

    debug["memory_tokens"] = mem_tokens
    debug["timeline_tokens"] = tl_tokens
    debug["total_tokens"] = core_tokens + mem_tokens + tl_tokens

    # Update access counts for retrieved memories
    retrieved_ids = [m["id"] for m, _ in scored[:50]]  # cap update to top 50
    _update_access_counts(db, retrieved_ids, narrative_time)

    # Assemble final context
    sections = [s for s in (core_text, memories_text, timeline_text) if s]
    context = "\n\n".join(sections)

    debug["memories_included"] = len([1 for line in memories_text.split("\n") if line.startswith("- ")])

    return PreFetchResult(context=context, debug=debug)
