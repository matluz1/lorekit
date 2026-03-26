#!/usr/bin/env python3
"""journal.py -- Append-only adventure log."""

import sqlite3
import sys

from lorekit.args import parse_args
from lorekit.db import LoreKitError, format_table, require_db


def usage():
    print("Usage: python core/journal.py <action> [args]")
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


def add(
    db, session_id: int, entry_type: str, content: str, narrative_time: str = "", scope: str = "participants"
) -> str:
    if scope not in ("gm", "participants", "region", "all"):
        raise LoreKitError(f"scope must be gm, participants, region, or all — got '{scope}'")
    nt = _resolve_narrative_time(db, session_id, narrative_time)
    cur = db.execute(
        "INSERT INTO journal (session_id, entry_type, content, narrative_time, scope) VALUES (?, ?, ?, ?, ?)",
        (session_id, entry_type, content, nt, scope),
    )
    db.commit()
    sql_id = cur.lastrowid
    try:
        from lorekit.support.vectordb import index_journal

        index_journal(db, session_id, sql_id, entry_type, content)
    except (ImportError, RuntimeError, OSError, sqlite3.Error):
        pass
    return f"JOURNAL_ADDED: {sql_id}"


def cmd_add(db, args):
    sid, p = parse_args(
        args,
        {
            "--type": ("entry_type", True, ""),
            "--content": ("content", True, ""),
            "--time": ("narrative_time", False, ""),
        },
        positional="session_id",
    )
    return add(db, int(sid), p["entry_type"], p["content"], p["narrative_time"])


def list_entries(db, session_id: int, entry_type: str = "", last: int = 0) -> str:
    query = "SELECT id, entry_type, content, created_at FROM journal WHERE session_id = ?"
    params: list = [session_id]
    if entry_type:
        query += " AND entry_type = ?"
        params.append(entry_type)
    query += " ORDER BY id DESC"
    if last:
        query += " LIMIT ?"
        params.append(last)
    cur = db.execute(query, params)
    return format_table(cur)


def cmd_list(db, args):
    sid, p = parse_args(
        args,
        {
            "--type": ("entry_type", False, ""),
            "--last": ("last", False, ""),
        },
        positional="session_id",
    )
    return list_entries(db, int(sid), p["entry_type"], int(p["last"]) if p["last"] else 0)


def search(db, session_id: int, query_text: str) -> str:
    cur = db.execute(
        "SELECT id, entry_type, content, created_at FROM journal WHERE session_id = ? AND content LIKE ? ORDER BY id",
        (session_id, f"%{query_text}%"),
    )
    return format_table(cur)


def cmd_search(db, args):
    sid, p = parse_args(
        args,
        {
            "--query": ("query_text", True, ""),
        },
        positional="session_id",
    )
    return search(db, int(sid), p["query_text"])


if __name__ == "__main__":
    main()
