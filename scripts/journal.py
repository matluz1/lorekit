#!/usr/bin/env python3
"""journal.py -- Append-only adventure log."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, format_table, LoreKitError
from _args import parse_args


def usage():
    print("Usage: python scripts/journal.py <action> [args]")
    print()
    print("Actions:")
    print("  add <session_id> --type <type> --content <content>")
    print("  list <session_id> [--type <type>] [--last <N>]")
    print("  search <session_id> --query <text>")
    print()
    print("Types: event, combat, discovery, npc, decision, note")
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
        raise LoreKitError(f"Unknown action: {action}")
    print(fn(db, args))


def _resolve_narrative_time(db, session_id, explicit_time):
    """Return explicit time if given, else current narrative clock, else empty."""
    if explicit_time:
        return explicit_time
    row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
        (session_id,),
    ).fetchone()
    return row[0] if row else ""


def cmd_add(db, args):
    sid, p = parse_args(args, {
        "--type": ("entry_type", True, ""),
        "--content": ("content", True, ""),
        "--time": ("narrative_time", False, ""),
    }, positional="session_id")
    nt = _resolve_narrative_time(db, int(sid), p["narrative_time"])
    cur = db.execute(
        "INSERT INTO journal (session_id, entry_type, content, narrative_time) VALUES (?, ?, ?, ?)",
        (sid, p["entry_type"], p["content"], nt),
    )
    db.commit()
    sql_id = cur.lastrowid
    try:
        from _vectordb import index_journal
        index_journal(sid, sql_id, p["entry_type"], p["content"])
    except Exception:
        pass
    return f"JOURNAL_ADDED: {sql_id}"


def cmd_list(db, args):
    sid, p = parse_args(args, {
        "--type": ("entry_type", False, ""),
        "--last": ("last", False, ""),
    }, positional="session_id")
    query = "SELECT id, entry_type, content, created_at FROM journal WHERE session_id = ?"
    params = [sid]
    if p["entry_type"]:
        query += " AND entry_type = ?"
        params.append(p["entry_type"])
    query += " ORDER BY id DESC"
    if p["last"]:
        query += " LIMIT ?"
        params.append(int(p["last"]))
    cur = db.execute(query, params)
    return format_table(cur)


def cmd_search(db, args):
    sid, p = parse_args(args, {
        "--query": ("query_text", True, ""),
    }, positional="session_id")
    cur = db.execute(
        "SELECT id, entry_type, content, created_at FROM journal "
        "WHERE session_id = ? AND content LIKE ? ORDER BY id",
        (sid, f"%{p['query_text']}%"),
    )
    return format_table(cur)


if __name__ == "__main__":
    main()
