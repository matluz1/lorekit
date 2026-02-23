#!/usr/bin/env python3
"""dialogue.py -- Record and query dialogues between the player and NPCs."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, print_table, error


def usage():
    print("Usage: python scripts/dialogue.py <action> [args]")
    print()
    print("Actions:")
    print('  add <session_id> --npc <npc_id> --speaker <pc|npc_name> --content "<text>"')
    print('  list <session_id> --npc <npc_id> [--last <N>]')
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
    npc = speaker = content = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--npc":
            npc = rest[i + 1]; i += 2
        elif rest[i] == "--speaker":
            speaker = rest[i + 1]; i += 2
        elif rest[i] == "--content":
            content = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not npc or not speaker or not content:
        error("--npc, --speaker, and --content are required")
    cur = db.execute(
        "INSERT INTO dialogues (session_id, npc_id, speaker, content) VALUES (?, ?, ?, ?)",
        (session_id, npc, speaker, content),
    )
    db.commit()
    sql_id = cur.lastrowid
    try:
        from _vectordb import index_dialogue
        index_dialogue(session_id, sql_id, npc, speaker, content)
    except Exception:
        pass
    print(f"DIALOGUE_ADDED: {sql_id}")


def cmd_list(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    npc = last = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--npc":
            npc = rest[i + 1]; i += 2
        elif rest[i] == "--last":
            last = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not npc:
        error("--npc is required")
    if last:
        # Get the last N lines by ordering descending, limiting, then re-ordering
        query = (
            "SELECT * FROM ("
            "SELECT d.id, c.name AS npc, d.speaker, d.content, d.created_at "
            "FROM dialogues d JOIN characters c ON d.npc_id = c.id "
            "WHERE d.session_id = ? AND d.npc_id = ? ORDER BY d.id DESC LIMIT ?"
            ") ORDER BY id"
        )
        cur = db.execute(query, (session_id, npc, int(last)))
    else:
        query = (
            "SELECT d.id, c.name AS npc, d.speaker, d.content, d.created_at "
            "FROM dialogues d JOIN characters c ON d.npc_id = c.id "
            "WHERE d.session_id = ? AND d.npc_id = ? ORDER BY d.id"
        )
        cur = db.execute(query, (session_id, npc))
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
        "SELECT d.id, c.name AS npc, d.speaker, d.content, d.created_at "
        "FROM dialogues d JOIN characters c ON d.npc_id = c.id "
        "WHERE d.session_id = ? AND d.content LIKE ? ORDER BY d.id",
        (session_id, f"%{query_text}%"),
    )
    print_table(cur)


if __name__ == "__main__":
    main()
