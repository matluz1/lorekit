"""Vector database utilities for LoreKit semantic search."""

import os


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
    collection.upsert(
        ids=[f"journal_{sql_id}"],
        documents=[content],
        metadatas=[metadata],
    )


def index_timeline(session_id, sql_id, entry_type, content, speaker=None, npc_id=None, created_at=None):
    """Upsert a timeline entry into the timeline collection."""
    client = get_chroma_client()
    collection = client.get_or_create_collection("timeline")
    metadata = {
        "session_id": str(session_id),
        "entry_type": entry_type,
        "sql_id": int(sql_id),
    }
    if speaker:
        metadata["speaker"] = speaker
    if npc_id is not None:
        metadata["npc_id"] = str(npc_id)
    if created_at:
        metadata["created_at"] = created_at
    collection.upsert(
        ids=[f"timeline_{sql_id}"],
        documents=[content],
        metadatas=[metadata],
    )


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

    for name in collections:
        try:
            col = client.get_collection(name)
        except Exception:
            continue
        if col.count() == 0:
            continue
        actual_n = min(n_results, col.count())
        res = col.query(
            query_texts=[query],
            n_results=actual_n,
            where={"session_id": str(session_id)},
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
    return results[:n_results]
