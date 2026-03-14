#!/usr/bin/env python3
"""recall.py -- Semantic search across timeline entries and journal notes."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _args import parse_args
from _db import LoreKitError, require_db


def usage():
    print("Usage: python core/recall.py <action> [args]")
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


def search(db, session_id: int, query_text: str, source: str = "", n_results: int = 0) -> str:
    from _vectordb import hybrid_search, is_available

    if not is_available():
        raise LoreKitError("sqlite-vec is not installed")

    collection_name = source if source else None
    results = hybrid_search(query_text, session_id, db, collection_name=collection_name, n_results=n_results)

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


def cmd_search(db, args):
    sid, p = parse_args(
        args,
        {
            "--query": ("query_text", True, ""),
            "--source": ("source", False, ""),
            "--n": ("n_results", False, "0"),
        },
        positional="session_id",
    )
    return search(db, int(sid), p["query_text"], p["source"], int(p["n_results"]))


def reindex(db, session_id: int) -> str:
    from _vectordb import index_journal, index_timeline, is_available

    if not is_available():
        raise LoreKitError("sqlite-vec is not installed")

    # Delete existing embeddings for this session
    emb_ids = [row[0] for row in db.execute("SELECT id FROM embeddings WHERE session_id = ?", (session_id,)).fetchall()]
    if emb_ids:
        placeholders = ",".join("?" * len(emb_ids))
        try:
            db.execute(f"DELETE FROM vec_embeddings WHERE rowid IN ({placeholders})", emb_ids)
        except Exception:
            pass
        db.execute(f"DELETE FROM embeddings WHERE id IN ({placeholders})", emb_ids)
        db.commit()

    timeline_count = 0
    skipped_count = 0
    journal_count = 0

    cur = db.execute(
        "SELECT id, entry_type, summary, created_at FROM timeline WHERE session_id = ?",
        (session_id,),
    )
    for row in cur.fetchall():
        sql_id, entry_type, summary, created_at = row
        if entry_type != "narration" or not summary:
            if entry_type == "narration" and not summary:
                skipped_count += 1
            continue
        index_timeline(db, session_id, sql_id, entry_type, summary, created_at=created_at)
        timeline_count += 1

    cur = db.execute(
        "SELECT id, entry_type, content, created_at FROM journal WHERE session_id = ?",
        (session_id,),
    )
    for row in cur.fetchall():
        sql_id, entry_type, content, created_at = row
        index_journal(db, session_id, sql_id, entry_type, content, created_at)
        journal_count += 1

    msg = f"REINDEX_COMPLETE: {timeline_count} timeline entries, {journal_count} journal entries"
    if skipped_count:
        msg += f" ({skipped_count} narrations skipped -- no summary)"
    return msg


def cmd_reindex(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")
    return reindex(db, int(sid))


if __name__ == "__main__":
    main()
