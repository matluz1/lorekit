#!/usr/bin/env python3
"""recall.py -- Semantic search across timeline entries and journal notes."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, LoreKitError
from _args import parse_args


def usage():
    print("Usage: python scripts/recall.py <action> [args]")
    print()
    print("Actions:")
    print('  search <session_id> --query "<text>" [--source timeline|journal] [--n <N>]')
    print("  reindex <session_id>")
    sys.exit(1)


def main():
    argv = sys.argv[1:]
    if not argv:
        usage()

    action = argv[0]
    args = argv[1:]

    db = require_db()

    actions = {
        "search": cmd_search,
        "reindex": cmd_reindex,
    }

    fn = actions.get(action)
    if fn is None:
        raise LoreKitError(f"Unknown action: {action}")
    print(fn(db, args))


def cmd_search(db, args):
    sid, p = parse_args(args, {
        "--query": ("query_text", True, ""),
        "--source": ("source", False, ""),
        "--n": ("n_results", False, "0"),
    }, positional="session_id")

    from _vectordb import is_available, hybrid_search

    if not is_available():
        raise LoreKitError("chromadb is not installed")

    collection_name = p["source"] if p["source"] else None
    results = hybrid_search(p["query_text"], sid, db, collection_name=collection_name, n_results=int(p["n_results"]))

    if not results:
        return "No results found."

    # Format results as table
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
    lines = []
    lines.append(sep.join(h.ljust(w) for h, w in zip(headers, widths)))
    lines.append(sep.join("-" * w for w in widths))
    for row in str_rows:
        lines.append(sep.join(val.ljust(w) for val, w in zip(row, widths)))
    return "\n".join(lines)


def cmd_reindex(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")

    from _vectordb import is_available, get_chroma_client, index_journal, index_timeline

    if not is_available():
        raise LoreKitError("chromadb is not installed")

    client = get_chroma_client()

    # Delete and recreate collections to ensure clean embeddings
    for col_name in ("timeline", "journal"):
        try:
            client.delete_collection(col_name)
        except Exception:
            pass
        client.get_or_create_collection(col_name)

    # Reindex all sessions (not just the requested one) since we wiped collections
    all_session_ids = [
        row[0] for row in db.execute("SELECT id FROM sessions").fetchall()
    ]

    timeline_count = 0
    skipped_count = 0
    journal_count = 0

    for s in all_session_ids:
        cur = db.execute(
            "SELECT id, entry_type, summary, created_at FROM timeline WHERE session_id = ?",
            (s,),
        )
        for row in cur.fetchall():
            sql_id, entry_type, summary, created_at = row
            if entry_type != "narration" or not summary:
                if str(s) == str(sid) and entry_type == "narration" and not summary:
                    skipped_count += 1
                continue
            index_timeline(s, sql_id, entry_type, summary, created_at=created_at)
            if str(s) == str(sid):
                timeline_count += 1

        cur = db.execute(
            "SELECT id, entry_type, content, created_at FROM journal WHERE session_id = ?",
            (s,),
        )
        for row in cur.fetchall():
            sql_id, entry_type, content, created_at = row
            index_journal(s, sql_id, entry_type, content, created_at)
            if str(s) == str(sid):
                journal_count += 1

    msg = f"REINDEX_COMPLETE: {timeline_count} timeline entries, {journal_count} journal entries"
    if skipped_count:
        msg += f" ({skipped_count} narrations skipped -- no summary)"
    if len(all_session_ids) > 1:
        msg += f" (rebuilt all {len(all_session_ids)} sessions)"
    return msg


if __name__ == "__main__":
    main()
