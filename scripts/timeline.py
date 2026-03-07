#!/usr/bin/env python3
"""timeline.py -- Unified timeline of narration and player choices."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, format_table, LoreKitError
from _args import parse_args


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
        raise LoreKitError(f"Unknown action: {action}")
    print(fn(db, args))


def cmd_add(db, args):
    sid, p = parse_args(args, {
        "--type": ("entry_type", True, ""),
        "--content": ("content", True, ""),
        "--summary": ("summary", False, ""),
    }, positional="session_id")
    if p["entry_type"] not in ("narration", "player_choice"):
        raise LoreKitError("--type must be narration or player_choice")
    cur = db.execute(
        "INSERT INTO timeline (session_id, entry_type, content, summary) VALUES (?, ?, ?, ?)",
        (sid, p["entry_type"], p["content"], p["summary"]),
    )
    db.commit()
    sql_id = cur.lastrowid
    if p["entry_type"] == "narration" and p["summary"]:
        try:
            from _vectordb import index_timeline
            index_timeline(sid, sql_id, p["entry_type"], p["summary"])
        except Exception:
            pass
    return f"TIMELINE_ADDED: {sql_id}"


def cmd_set_summary(db, args):
    tid, p = parse_args(args, {
        "--summary": ("summary", True, ""),
    }, positional="timeline_id")
    row = db.execute(
        "SELECT session_id, entry_type FROM timeline WHERE id = ?",
        (tid,),
    ).fetchone()
    if not row:
        raise LoreKitError(f"Timeline entry {tid} not found")
    session_id, entry_type = row
    db.execute(
        "UPDATE timeline SET summary = ? WHERE id = ?",
        (p["summary"], tid),
    )
    db.commit()
    if entry_type == "narration":
        try:
            from _vectordb import index_timeline
            index_timeline(session_id, tid, entry_type, p["summary"])
        except Exception:
            pass
    return f"SUMMARY_SET: {tid}"


def cmd_revert(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")

    # Find the last narration
    row = db.execute(
        "SELECT id FROM timeline WHERE session_id = ? AND entry_type = 'narration' ORDER BY id DESC LIMIT 1",
        (sid,),
    ).fetchone()
    if not row:
        raise LoreKitError("No narrations to revert")
    last_narration_id = row[0]

    # Find all entries at or after the last narration
    rows = db.execute(
        "SELECT id, entry_type, summary FROM timeline WHERE session_id = ? AND id >= ? ORDER BY id",
        (sid, last_narration_id),
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
        (sid,),
    ).fetchone()
    if prev:
        db.execute(
            "INSERT OR REPLACE INTO session_meta (session_id, key, value) VALUES (?, 'last_gm_message', ?)",
            (sid, prev[0]),
        )
    else:
        db.execute(
            "DELETE FROM session_meta WHERE session_id = ? AND key = 'last_gm_message'",
            (sid,),
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
    return f"TIMELINE_REVERTED: {len(ids_to_delete)} entries removed ({breakdown})"


def cmd_list(db, args):
    sid, p = parse_args(args, {
        "--type": ("entry_type", False, ""),
        "--last": ("last", False, ""),
        "--id": ("entry_id", False, ""),
    }, positional="session_id")
    if p["entry_id"]:
        entry_id = p["entry_id"]
        if "-" in entry_id:
            id_from, id_to = entry_id.split("-", 1)
            cur = db.execute(
                "SELECT id, entry_type, content, created_at FROM timeline WHERE session_id = ? AND id BETWEEN ? AND ? ORDER BY id",
                (sid, int(id_from), int(id_to)),
            )
        else:
            cur = db.execute(
                "SELECT id, entry_type, content, created_at FROM timeline WHERE session_id = ? AND id = ?",
                (sid, int(entry_id)),
            )
        return format_table(cur)
    query = "SELECT id, entry_type, content, created_at FROM timeline WHERE session_id = ?"
    params = [sid]
    if p["entry_type"]:
        query += " AND entry_type = ?"
        params.append(p["entry_type"])
    if p["last"]:
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(p["last"]))
        # Wrap to re-order ascending
        query = f"SELECT * FROM ({query}) ORDER BY id"
    else:
        query += " ORDER BY id"
    cur = db.execute(query, params)
    return format_table(cur)


def cmd_search(db, args):
    sid, p = parse_args(args, {
        "--query": ("query_text", True, ""),
    }, positional="session_id")
    cur = db.execute(
        "SELECT id, entry_type, content, created_at FROM timeline "
        "WHERE session_id = ? AND content LIKE ? ORDER BY id",
        (sid, f"%{p['query_text']}%"),
    )
    return format_table(cur)


if __name__ == "__main__":
    main()
