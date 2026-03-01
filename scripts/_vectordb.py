"""Vector database utilities for LoreKit semantic search."""

import io
import os
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
        from sentence_transformers import SentenceTransformer

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



def is_available():
    """Return True if chromadb is importable."""
    try:
        import chromadb  # noqa: F401

        return True
    except ImportError:
        return False


def resolve_chroma_path():
    """Resolve the ChromaDB storage path (next to game.db)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_dir = os.environ.get("LOREKIT_DB_DIR", os.path.join(script_dir, "..", "data"))
    return os.environ.get("LOREKIT_CHROMA_DIR", os.path.join(db_dir, "chroma"))


def get_chroma_client():
    """Return a persistent ChromaDB client."""
    import chromadb

    path = resolve_chroma_path()
    os.makedirs(path, exist_ok=True)
    return chromadb.PersistentClient(path=path)


def index_journal(session_id, sql_id, entry_type, content, created_at=None):
    """Upsert a journal entry into the journal collection."""
    client = get_chroma_client()
    collection = client.get_or_create_collection("journal")
    metadata = {
        "session_id": str(session_id),
        "entry_type": entry_type,
        "sql_id": int(sql_id),
    }
    if created_at:
        metadata["created_at"] = created_at
    embeddings = _embed_passages([content])
    kwargs = {
        "ids": [f"journal_{sql_id}"],
        "documents": [content],
        "metadatas": [metadata],
    }
    if embeddings is not None:
        kwargs["embeddings"] = embeddings
    collection.upsert(**kwargs)


def index_timeline(session_id, sql_id, entry_type, summary, created_at=None):
    """Upsert a timeline entry into the timeline collection.

    Indexes the summary text as a single vector per entry.
    """
    client = get_chroma_client()
    collection = client.get_or_create_collection("timeline")

    doc_id = f"timeline_{sql_id}"
    metadata = {
        "session_id": str(session_id),
        "entry_type": entry_type,
        "sql_id": int(sql_id),
    }
    if created_at:
        metadata["created_at"] = created_at

    embeddings = _embed_passages([summary])
    kwargs = {
        "ids": [doc_id],
        "documents": [summary],
        "metadatas": [metadata],
    }
    if embeddings is not None:
        kwargs["embeddings"] = embeddings
    collection.upsert(**kwargs)


def search(query, session_id, collection_name=None, n_results=5):
    """Semantic search across timeline and/or journal.

    Returns a list of dicts with keys: source, id, content, distance, metadata.
    """
    client = get_chroma_client()
    results = []
    collections = []
    if collection_name:
        collections.append(collection_name)
    else:
        collections = ["timeline", "journal"]

    query_embedding = _embed_query(query)

    for name in collections:
        try:
            col = client.get_collection(name)
        except Exception:
            continue
        if col.count() == 0:
            continue
        actual_n = min(n_results, col.count())
        # For timeline, only search narration entries semantically.
        # Short player_choice texts get artificially high similarity and
        # dominate over longer, more relevant narrations. Player choices
        # are covered by keyword_search in hybrid mode.
        if name == "timeline":
            where = {"$and": [
                {"session_id": str(session_id)},
                {"entry_type": "narration"},
            ]}
        else:
            where = {"session_id": str(session_id)}
        if query_embedding is not None:
            res = col.query(
                query_embeddings=[query_embedding],
                n_results=actual_n,
                where=where,
            )
        else:
            res = col.query(
                query_texts=[query],
                n_results=actual_n,
                where=where,
            )
        if res["ids"] and res["ids"][0]:
            for i, doc_id in enumerate(res["ids"][0]):
                results.append({
                    "source": name,
                    "id": doc_id,
                    "content": res["documents"][0][i],
                    "distance": res["distances"][0][i],
                    "metadata": res["metadatas"][0][i],
                })

    results.sort(key=lambda r: r["distance"])
    return results


def keyword_search(query, session_id, collection_name=None, n_results=5):
    """Keyword search across timeline and/or journal via SQL LIKE.

    Returns a list of dicts with keys: source, id, content, distance, metadata.
    """
    from _db import require_db

    db = require_db()
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
            results.append({
                "source": table,
                "id": f"{table}_{sql_id}",
                "content": content,
                "distance": 0.0,
                "metadata": {
                    "session_id": str(session_id),
                    "entry_type": entry_type,
                    "sql_id": sql_id,
                },
            })

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


_DEFAULT_LIMITS = {"timeline": 15, "journal": 5}


def _resolve_raw_content(results):
    """Attach raw content from SQLite to each result dict."""
    from _db import require_db

    if not results:
        return results

    db = require_db()
    for r in results:
        sql_id = r["metadata"].get("sql_id")
        source = r["source"]
        if sql_id is None:
            continue
        table = source  # "timeline" or "journal"
        row = db.execute(
            f"SELECT content FROM {table} WHERE id = ?", (sql_id,)
        ).fetchone()
        if row:
            r["raw"] = row[0]

    return results


def hybrid_search(query, session_id, collection_name=None, n_results=0):
    """Hybrid search combining keyword (SQL LIKE) and semantic (ChromaDB) results.

    Uses Reciprocal Rank Fusion to merge rankings per collection.
    Each collection has a default result limit (timeline: 15, journal: 5).
    Pass n_results > 0 to override the default for the requested collection(s).
    Returns a list of dicts with keys: source, id, content, distance, metadata, raw.
    """
    collections = [collection_name] if collection_name else ["timeline", "journal"]
    if n_results > 0:
        limits = {c: n_results for c in collections}
    else:
        limits = {c: _DEFAULT_LIMITS.get(c, 5) for c in collections}

    results = []
    for col_name, limit in limits.items():
        fetch_n = limit * 3
        sem = search(query, session_id, collection_name=col_name, n_results=fetch_n)
        kw = keyword_search(query, session_id, collection_name=col_name, n_results=fetch_n)
        results.extend(_rrf_merge(sem, kw, limit))

    _resolve_raw_content(results)

    return results
