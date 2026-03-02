#!/usr/bin/env python3
"""timeline.py -- Unified timeline of narration and player choices."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, print_table, error


def usage():
    print("Usage: python scripts/timeline.py <action> [args]")
    print()
    print("Actions:")
    print('  add <session_id> --type narration --content "<text>"')
    print('  add <session_id> --type player_choice --content "<text>"')
    print("  list <session_id> [--type narration|player_choice] [--last <N>]")
    print('  search <session_id> --query "<text>"')
    sys.exit(1)


def main():
    argv = sys.argv[1:]
    if not argv:
        usage()

    action = argv[0]
    args = argv[1:]

    db = require_db()

    actions = {
        "add": cmd_add,
        "list": cmd_list,
        "search": cmd_search,
        "revert": cmd_revert,
    }

    fn = actions.get(action)
    if fn is None:
        error(f"Unknown action: {action}")
    fn(db, args)


def cmd_add(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    entry_type = content = summary = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--type":
            entry_type = rest[i + 1]; i += 2
        elif rest[i] == "--content":
            content = rest[i + 1]; i += 2
        elif rest[i] == "--summary":
            summary = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not entry_type or not content:
        error("--type and --content are required")
    if entry_type not in ("narration", "player_choice"):
        error("--type must be narration or player_choice")
    cur = db.execute(
        "INSERT INTO timeline (session_id, entry_type, content, summary) VALUES (?, ?, ?, ?)",
        (session_id, entry_type, content, summary),
    )
    db.commit()
    sql_id = cur.lastrowid
    if entry_type == "narration" and summary:
        try:
            from _vectordb import index_timeline
            index_timeline(session_id, sql_id, entry_type, summary)
        except Exception:
            pass
    print(f"TIMELINE_ADDED: {sql_id}")


def cmd_set_summary(db, args):
    if not args:
        error("timeline_id required")
    timeline_id = args[0]
    rest = args[1:]
    summary = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--summary":
            summary = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not summary:
        error("--summary is required")
    row = db.execute(
        "SELECT session_id, entry_type FROM timeline WHERE id = ?",
        (timeline_id,),
    ).fetchone()
    if not row:
        error(f"Timeline entry {timeline_id} not found")
    session_id, entry_type = row
    db.execute(
        "UPDATE timeline SET summary = ? WHERE id = ?",
        (summary, timeline_id),
    )
    db.commit()
    if entry_type == "narration":
        try:
            from _vectordb import index_timeline
            index_timeline(session_id, timeline_id, entry_type, summary)
        except Exception:
            pass
    print(f"SUMMARY_SET: {timeline_id}")


def cmd_revert(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]

    # Find the last narration
    row = db.execute(
        "SELECT id FROM timeline WHERE session_id = ? AND entry_type = 'narration' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
        error("No narrations to revert")
    last_narration_id = row[0]

    # Find all entries at or after the last narration
    rows = db.execute(
        "SELECT id, entry_type, summary FROM timeline WHERE session_id = ? AND id >= ? ORDER BY id",
        (session_id, last_narration_id),
    ).fetchall()
    ids_to_delete = [r[0] for r in rows]
    narration_ids_with_summary = [r[0] for r in rows if r[1] == "narration" and r[2]]

    # Count by type for the output message
    type_counts = {}
    for r in rows:
        type_counts[r[1]] = type_counts.get(r[1], 0) + 1

    # Delete from SQLite
    placeholders = ",".join("?" * len(ids_to_delete))
    db.execute(f"DELETE FROM timeline WHERE id IN ({placeholders})", ids_to_delete)

    # Restore last_gm_message to the previous narration (if any remain)
    prev = db.execute(
        "SELECT content FROM timeline WHERE session_id = ? AND entry_type = 'narration' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if prev:
        db.execute(
            "INSERT OR REPLACE INTO session_meta (session_id, key, value) VALUES (?, 'last_gm_message', ?)",
            (session_id, prev[0]),
        )
    else:
        db.execute(
            "DELETE FROM session_meta WHERE session_id = ? AND key = 'last_gm_message'",
            (session_id,),
        )
    db.commit()

    # Best-effort ChromaDB cleanup for deleted narrations with summaries
    if narration_ids_with_summary:
        try:
            from _vectordb import delete_timeline
            delete_timeline(narration_ids_with_summary)
        except Exception:
            pass

    breakdown = ", ".join(f"{count} {etype}" for etype, count in sorted(type_counts.items()))
    print(f"TIMELINE_REVERTED: {len(ids_to_delete)} entries removed ({breakdown})")


def cmd_list(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    entry_type = last = entry_id = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--type":
            entry_type = rest[i + 1]; i += 2
        elif rest[i] == "--last":
            last = rest[i + 1]; i += 2
        elif rest[i] == "--id":
            entry_id = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if entry_id:
        if "-" in entry_id:
            id_from, id_to = entry_id.split("-", 1)
            cur = db.execute(
                "SELECT id, entry_type, content, created_at FROM timeline WHERE session_id = ? AND id BETWEEN ? AND ? ORDER BY id",
                (session_id, int(id_from), int(id_to)),
            )
        else:
            cur = db.execute(
                "SELECT id, entry_type, content, created_at FROM timeline WHERE session_id = ? AND id = ?",
                (session_id, int(entry_id)),
            )
        print_table(cur)
        return
    query = "SELECT id, entry_type, content, created_at FROM timeline WHERE session_id = ?"
    params = [session_id]
    if entry_type:
        query += " AND entry_type = ?"
        params.append(entry_type)
    if last:
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(last))
        # Wrap to re-order ascending
        query = f"SELECT * FROM ({query}) ORDER BY id"
    else:
        query += " ORDER BY id"
    cur = db.execute(query, params)
    print_table(cur)


def cmd_search(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    query_text = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--query":
            query_text = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not query_text:
        error("--query is required")
    cur = db.execute(
        "SELECT id, entry_type, content, created_at FROM timeline "
        "WHERE session_id = ? AND content LIKE ? ORDER BY id",
        (session_id, f"%{query_text}%"),
    )
    print_table(cur)


if __name__ == "__main__":
    main()
