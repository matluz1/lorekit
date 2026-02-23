#!/usr/bin/env python3
"""recall.py -- Semantic search across journal entries and dialogues."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, error


def usage():
    print("Usage: python scripts/recall.py <action> [args]")
    print()
    print("Actions:")
    print('  search <session_id> --query "<text>" [--source journal|dialogues] [--n <N>]')
    print("  reindex <session_id>")
    sys.exit(1)


def main():
    argv = sys.argv[1:]
    if not argv:
        usage()

    action = argv[0]
    args = argv[1:]

    actions = {
        "search": cmd_search,
        "reindex": cmd_reindex,
    }

    fn = actions.get(action)
    if fn is None:
        error(f"Unknown action: {action}")
    fn(args)


def cmd_search(args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    query_text = ""
    source = ""
    n_results = 5
    i = 0
    while i < len(rest):
        if rest[i] == "--query":
            query_text = rest[i + 1]; i += 2
        elif rest[i] == "--source":
            source = rest[i + 1]; i += 2
        elif rest[i] == "--n":
            n_results = int(rest[i + 1]); i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not query_text:
        error("--query is required")

    from _vectordb import is_available, search

    if not is_available():
        error("chromadb is not installed")

    collection_name = source if source else None
    results = search(query_text, session_id, collection_name=collection_name, n_results=n_results)

    if not results:
        print("No results found.")
        return

    # Print results in table format
    headers = ["source", "id", "distance", "content"]
    widths = [len(h) for h in headers]
    str_rows = []
    for r in results:
        row = [
            r["source"],
            r["id"],
            f"{r['distance']:.4f}",
            r["content"],
        ]
        str_rows.append(row)
        for j, val in enumerate(row):
            widths[j] = max(widths[j], len(val))
    widths = [max(w, 1) for w in widths]
    sep = "  "
    print(sep.join(h.ljust(w) for h, w in zip(headers, widths)))
    print(sep.join("-" * w for w in widths))
    for row in str_rows:
        print(sep.join(val.ljust(w) for val, w in zip(row, widths)))


def cmd_reindex(args):
    if not args:
        error("session_id required")
    session_id = args[0]

    from _vectordb import is_available, get_chroma_client, index_journal, index_dialogue

    if not is_available():
        error("chromadb is not installed")

    db = require_db()

    # Clear existing vectors for this session
    client = get_chroma_client()
    for col_name in ("journal", "dialogues"):
        try:
            col = client.get_collection(col_name)
            existing = col.get(where={"session_id": str(session_id)})
            if existing["ids"]:
                col.delete(ids=existing["ids"])
        except Exception:
            pass

    # Reindex journal entries
    journal_count = 0
    cur = db.execute(
        "SELECT id, entry_type, content, created_at FROM journal WHERE session_id = ?",
        (session_id,),
    )
    for row in cur.fetchall():
        sql_id, entry_type, content, created_at = row
        index_journal(session_id, sql_id, entry_type, content, created_at)
        journal_count += 1

    # Reindex dialogues
    dialogue_count = 0
    cur = db.execute(
        "SELECT id, npc_id, speaker, content, created_at FROM dialogues WHERE session_id = ?",
        (session_id,),
    )
    for row in cur.fetchall():
        sql_id, npc_id, speaker, content, created_at = row
        index_dialogue(session_id, sql_id, npc_id, speaker, content, created_at)
        dialogue_count += 1

    print(f"REINDEX_COMPLETE: {journal_count} journal entries, {dialogue_count} dialogues")


if __name__ == "__main__":
    main()
