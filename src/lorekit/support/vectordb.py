"""Vector database utilities for LoreKit semantic search.

Uses sqlite-vec for vector storage inside the same SQLite database as
structured data.  The sentence-transformers embedding model is optional;
if unavailable, indexing is silently skipped.
"""

import io
import struct
import sys

_model = None
_model_resolved = False


def _get_model():
    """Return SentenceTransformer with multilingual-e5-small, or None."""
    global _model, _model_resolved
    if _model_resolved:
        return _model
    old_stderr = sys.stderr
    try:
        import os

        from sentence_transformers import SentenceTransformer

        cache_dir = os.path.join(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface")), "hub")
        model_dir = os.path.join(cache_dir, "models--intfloat--multilingual-e5-small")
        if not os.path.isdir(model_dir):
            print("Downloading embedding model (intfloat/multilingual-e5-small, ~488MB)... this only happens once.")

        sys.stderr = io.StringIO()
        _model = SentenceTransformer("intfloat/multilingual-e5-small")
    except (ImportError, Exception):
        _model = None
    finally:
        sys.stderr = old_stderr
    _model_resolved = True
    return _model


def _embed_passages(texts):
    """Embed document texts with 'passage: ' prefix. Returns list of lists, or None."""
    model = _get_model()
    if model is None:
        return None
    prefixed = [f"passage: {t}" for t in texts]
    return model.encode(prefixed, normalize_embeddings=True).tolist()


def _embed_query(text):
    """Embed a query with 'query: ' prefix. Returns list of floats, or None."""
    model = _get_model()
    if model is None:
        return None
    return model.encode(f"query: {text}", normalize_embeddings=True).tolist()


def _serialize(vec):
    """Serialize a float list to bytes for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


def is_available():
    """Return True if sqlite_vec is importable."""
    try:
        import sqlite_vec  # noqa: F401

        return True
    except ImportError:
        return False


def _has_vec_table(db):
    """Check whether the vec_embeddings virtual table exists."""
    row = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vec_embeddings'").fetchone()
    return row is not None


def _upsert_embedding(db, source, source_id, session_id, content, created_at=None, npc_id=None):
    """Insert or update an embedding row and its vec0 entry."""
    embeddings = _embed_passages([content])

    # Upsert metadata row
    db.execute(
        "INSERT INTO embeddings (source, source_id, session_id, npc_id, content, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(source, source_id) DO UPDATE SET content = excluded.content, npc_id = excluded.npc_id",
        (source, source_id, session_id, npc_id, content, created_at or ""),
    )

    row = db.execute(
        "SELECT id FROM embeddings WHERE source = ? AND source_id = ?",
        (source, source_id),
    ).fetchone()
    emb_id = row[0]

    # Update vec0 entry if we have embeddings and the virtual table exists
    if embeddings is not None and _has_vec_table(db):
        blob = _serialize(embeddings[0])
        db.execute("DELETE FROM vec_embeddings WHERE rowid = ?", (emb_id,))
        db.execute(
            "INSERT INTO vec_embeddings (rowid, embedding) VALUES (?, ?)",
            (emb_id, blob),
        )

    db.commit()


def index_journal(db, session_id, sql_id, entry_type, content, created_at=None):
    """Upsert a journal entry into the embeddings table."""
    _upsert_embedding(db, "journal", sql_id, session_id, content, created_at)


def index_timeline(db, session_id, sql_id, entry_type, summary, created_at=None):
    """Upsert a timeline entry into the embeddings table (indexes the summary)."""
    _upsert_embedding(db, "timeline", sql_id, session_id, summary, created_at)


def index_npc_memory(db, session_id, npc_id, memory_id, content):
    """Upsert an NPC memory into the embeddings table."""
    _upsert_embedding(db, "npc_memory", memory_id, session_id, content, npc_id=npc_id)


def delete_npc_memories(db, memory_ids):
    """Delete NPC memory embeddings."""
    delete_embeddings(db, "npc_memory", memory_ids)


def delete_embeddings(db, source, sql_ids):
    """Delete embeddings for the given source and source_ids."""
    if not sql_ids:
        return
    for sql_id in sql_ids:
        row = db.execute(
            "SELECT id FROM embeddings WHERE source = ? AND source_id = ?",
            (source, sql_id),
        ).fetchone()
        if row:
            emb_id = row[0]
            if _has_vec_table(db):
                db.execute("DELETE FROM vec_embeddings WHERE rowid = ?", (emb_id,))
            db.execute("DELETE FROM embeddings WHERE id = ?", (emb_id,))
    db.commit()


def delete_timeline(db, sql_ids):
    """Delete timeline embeddings. Thin wrapper around delete_embeddings."""
    delete_embeddings(db, "timeline", sql_ids)


def search(query, session_id, db, collection_name=None, n_results=5):
    """Semantic search across timeline and/or journal via sqlite-vec.

    Returns a list of dicts with keys: source, id, content, distance, metadata.
    """
    query_embedding = _embed_query(query)
    if query_embedding is None or not _has_vec_table(db):
        return []

    blob = _serialize(query_embedding)
    sources = [collection_name] if collection_name else ["timeline", "journal"]

    # Over-fetch to account for session/source filtering
    fetch_k = n_results * 10

    rows = db.execute(
        """
        SELECT e.source, e.source_id, e.content, e.session_id, v.distance
        FROM (
            SELECT rowid, distance
            FROM vec_embeddings
            WHERE embedding MATCH ? AND k = ?
        ) v
        JOIN embeddings e ON e.id = v.rowid
        WHERE e.session_id = ?
          AND e.source IN ({})
        """.format(",".join("?" * len(sources))),
        (blob, fetch_k, session_id, *sources),
    ).fetchall()

    results = []
    for source, source_id, content, sid, distance in rows:
        if len(results) >= n_results:
            break
        results.append(
            {
                "source": source,
                "id": f"{source}_{source_id}",
                "content": content,
                "distance": distance,
                "metadata": {
                    "session_id": str(sid),
                    "sql_id": source_id,
                },
            }
        )

    return results


def keyword_search(query, session_id, db, collection_name=None, n_results=5):
    """Keyword search across timeline and/or journal via SQL LIKE.

    Returns a list of dicts with keys: source, id, content, distance, metadata.
    """
    results = []
    tables = []
    if collection_name:
        tables.append(collection_name)
    else:
        tables = ["timeline", "journal"]

    for table in tables:
        cur = db.execute(
            f"SELECT id, entry_type, content, created_at FROM {table} "
            "WHERE session_id = ? AND content LIKE ? ORDER BY id",
            (session_id, f"%{query}%"),
        )
        for row in cur.fetchall():
            sql_id, entry_type, content, created_at = row
            results.append(
                {
                    "source": table,
                    "id": f"{table}_{sql_id}",
                    "content": content,
                    "distance": 0.0,
                    "metadata": {
                        "session_id": str(session_id),
                        "entry_type": entry_type,
                        "sql_id": sql_id,
                    },
                }
            )

    return results


def _rrf_merge(semantic_results, kw_results, n_results):
    """Merge semantic and keyword results using Reciprocal Rank Fusion."""
    k = 60  # standard RRF constant
    scores = {}
    doc_map = {}

    for rank, r in enumerate(semantic_results):
        key = (r["source"], r["metadata"]["sql_id"])
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        if key not in doc_map:
            doc_map[key] = r

    for rank, r in enumerate(kw_results):
        key = (r["source"], r["metadata"]["sql_id"])
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        if key not in doc_map:
            doc_map[key] = r

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    results = []
    for key, _rrf_score in ranked[:n_results]:
        results.append(doc_map[key])

    return results


_DEFAULT_LIMITS = {"timeline": 10, "journal": 5}


def hybrid_search(query, session_id, db, collection_name=None, n_results=0):
    """Hybrid search combining keyword (SQL LIKE) and semantic (sqlite-vec) results.

    Uses Reciprocal Rank Fusion to merge rankings per collection.
    Each collection has a default result limit (timeline: 10, journal: 5).
    Pass n_results > 0 to override the default for the requested collection(s).
    Returns a list of dicts with keys: source, id, content, distance, metadata.
    """
    collections = [collection_name] if collection_name else ["timeline", "journal"]
    if n_results > 0:
        limits = {c: n_results for c in collections}
    else:
        limits = {c: _DEFAULT_LIMITS.get(c, 5) for c in collections}

    results = []
    for col_name, limit in limits.items():
        fetch_n = limit * 3
        sem = search(query, session_id, db, collection_name=col_name, n_results=fetch_n)
        kw = keyword_search(query, session_id, db, collection_name=col_name, n_results=fetch_n)
        results.extend(_rrf_merge(sem, kw, limit))

    return results
