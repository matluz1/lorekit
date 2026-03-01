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
    entry_type = content = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--type":
            entry_type = rest[i + 1]; i += 2
        elif rest[i] == "--content":
            content = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not entry_type or not content:
        error("--type and --content are required")
    if entry_type not in ("narration", "player_choice"):
        error("--type must be narration or player_choice")
    cur = db.execute(
        "INSERT INTO timeline (session_id, entry_type, content) VALUES (?, ?, ?)",
        (session_id, entry_type, content),
    )
    db.commit()
    sql_id = cur.lastrowid
    try:
        from _vectordb import index_timeline
        index_timeline(session_id, sql_id, entry_type, content)
    except Exception:
        pass
    print(f"TIMELINE_ADDED: {sql_id}")


def cmd_list(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    entry_type = last = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--type":
            entry_type = rest[i + 1]; i += 2
        elif rest[i] == "--last":
            last = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
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
