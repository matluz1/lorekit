"""npc_memory.py -- NPC memory CRUD, scoring, and core identity management."""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import LoreKitError

VALID_MEMORY_TYPES = ("experience", "observation", "relationship", "reflection")
CORE_FIELD_CAP = 2000


def add_memory(db, session_id, npc_id, content, importance, memory_type, entities, narrative_time, source_ids=None):
    """Insert an NPC memory and embed it. Returns the memory ID."""
    if memory_type not in VALID_MEMORY_TYPES:
        raise LoreKitError(f"Invalid memory_type '{memory_type}'. Must be one of: {', '.join(VALID_MEMORY_TYPES)}")

    entities_json = entities if isinstance(entities, str) else json.dumps(entities)
    source_json = json.dumps(source_ids) if source_ids else None

    cur = db.execute(
        "INSERT INTO npc_memories (session_id, npc_id, content, importance, memory_type, "
        "entities, narrative_time, source_ids) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, npc_id, content, float(importance), memory_type, entities_json, narrative_time, source_json),
    )
    db.commit()
    memory_id = cur.lastrowid

    # Embed the memory
    try:
        from _vectordb import index_npc_memory

        index_npc_memory(db, session_id, npc_id, memory_id, content)
    except Exception:
        pass

    return memory_id


def get_memories(db, npc_id, session_id, limit=10, min_importance=0.0):
    """Retrieve NPC memories ordered by importance DESC."""
    rows = db.execute(
        "SELECT id, content, importance, memory_type, entities, narrative_time, "
        "access_count, last_accessed, source_ids, created_at "
        "FROM npc_memories WHERE npc_id = ? AND session_id = ? AND importance >= ? "
        "ORDER BY importance DESC LIMIT ?",
        (npc_id, session_id, min_importance, limit),
    ).fetchall()

    return [
        {
            "id": r[0],
            "content": r[1],
            "importance": r[2],
            "memory_type": r[3],
            "entities": r[4],
            "narrative_time": r[5],
            "access_count": r[6],
            "last_accessed": r[7],
            "source_ids": r[8],
            "created_at": r[9],
        }
        for r in rows
    ]


def get_core(db, session_id, npc_id):
    """Return npc_core row as dict, or None."""
    row = db.execute(
        "SELECT self_concept, current_goals, emotional_state, relationships, "
        "behavioral_patterns, updated_at FROM npc_core WHERE session_id = ? AND npc_id = ?",
        (session_id, npc_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "self_concept": row[0],
        "current_goals": row[1],
        "emotional_state": row[2],
        "relationships": row[3],
        "behavioral_patterns": row[4],
        "updated_at": row[5],
    }


def set_core(db, session_id, npc_id, **fields):
    """Upsert npc_core with 2,000-char cap per field."""
    allowed = {"self_concept", "current_goals", "emotional_state", "relationships", "behavioral_patterns"}
    filtered = {}
    for k, v in fields.items():
        if k in allowed and v is not None:
            filtered[k] = str(v)[:CORE_FIELD_CAP]

    if not filtered:
        return

    # Check if row exists
    existing = db.execute(
        "SELECT id FROM npc_core WHERE session_id = ? AND npc_id = ?",
        (session_id, npc_id),
    ).fetchone()

    if existing:
        sets = []
        params = []
        for k, v in filtered.items():
            sets.append(f"{k} = ?")
            params.append(v)
        sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
        params.extend([session_id, npc_id])
        db.execute(f"UPDATE npc_core SET {', '.join(sets)} WHERE session_id = ? AND npc_id = ?", params)
    else:
        cols = ["session_id", "npc_id"]
        vals = [session_id, npc_id]
        for k, v in filtered.items():
            cols.append(k)
            vals.append(v)
        cols.append("updated_at")
        vals.append(None)  # will use SQL default via trigger or explicit set
        ph = ", ".join("?" * len(vals))
        db.execute(f"INSERT INTO npc_core ({', '.join(cols)}) VALUES ({ph})", vals)

    db.commit()


def score_memories(memories, query_embedding, narrative_now, noise=0.0):
    """Score memories using Park+ACT-R formula.

    Each memory dict must have: importance, last_accessed (ISO timestamp or None), created_at.
    query_embedding: list of floats (the query vector).
    narrative_now: unused placeholder for future narrative-time scoring;
        currently uses created_at/last_accessed wall-clock times.
    noise: scale parameter for logistic noise (0 = deterministic).

    Returns list of (memory, score) tuples sorted by score DESC.
    """
    import random
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    raw_scores = []
    for m in memories:
        # Recency: 0.995 ^ hours since last access
        last = m.get("last_accessed") or m.get("created_at") or ""
        if last:
            try:
                ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
                hours = max((now - ts).total_seconds() / 3600.0, 0.0)
            except (ValueError, TypeError):
                hours = 0.0
        else:
            hours = 0.0
        recency = 0.995**hours

        importance = float(m.get("importance", 0.5))

        # Relevance via cosine similarity with query_embedding
        # (embedding stored externally; for scoring we expect it passed in m["embedding"])
        emb = m.get("embedding")
        if emb and query_embedding:
            relevance = _cosine_similarity(emb, query_embedding)
        else:
            relevance = 0.0

        raw_scores.append({"memory": m, "recency": recency, "importance": importance, "relevance": relevance})

    if not raw_scores:
        return []

    # Min-max normalize each dimension
    for dim in ("recency", "importance", "relevance"):
        values = [s[dim] for s in raw_scores]
        lo, hi = min(values), max(values)
        rng = hi - lo
        for s in raw_scores:
            s[f"{dim}_norm"] = (s[dim] - lo) / rng if rng > 0 else 0.5

    # Sum with equal weights + optional noise
    results = []
    for s in raw_scores:
        score = s["recency_norm"] + s["importance_norm"] + s["relevance_norm"]
        if noise > 0:
            score += random.random() * noise  # simple uniform noise
        results.append((s["memory"], score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
