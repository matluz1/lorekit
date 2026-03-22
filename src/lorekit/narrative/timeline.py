#!/usr/bin/env python3
"""timeline.py -- Unified timeline of narration and player choices."""

import sys

from lorekit.args import parse_args
from lorekit.db import LoreKitError, format_table, require_db


def usage():
    print("Usage: python core/timeline.py <action> [args]")
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


def _resolve_narrative_time(db, session_id, explicit_time):
    """Return explicit time if given, else current narrative clock, else empty."""
    if explicit_time:
        return explicit_time
    row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
        (session_id,),
    ).fetchone()
    return row[0] if row else ""


def add(db, session_id: int, entry_type: str, content: str, summary: str = "", narrative_time: str = "") -> str:
    if entry_type not in ("narration", "player_choice"):
        raise LoreKitError("type must be narration or player_choice")
    nt = _resolve_narrative_time(db, session_id, narrative_time)
    cur = db.execute(
        "INSERT INTO timeline (session_id, entry_type, content, summary, narrative_time) VALUES (?, ?, ?, ?, ?)",
        (session_id, entry_type, content, summary, nt),
    )
    db.commit()
    sql_id = cur.lastrowid
    if entry_type == "narration" and summary:
        try:
            from lorekit.support.vectordb import index_timeline

            index_timeline(db, session_id, sql_id, entry_type, summary)
        except Exception:
            pass
    return f"TIMELINE_ADDED: {sql_id}"


def cmd_add(db, args):
    sid, p = parse_args(
        args,
        {
            "--type": ("entry_type", True, ""),
            "--content": ("content", True, ""),
            "--summary": ("summary", False, ""),
            "--time": ("narrative_time", False, ""),
        },
        positional="session_id",
    )
    return add(db, int(sid), p["entry_type"], p["content"], p["summary"], p["narrative_time"])


def set_summary(db, timeline_id: int, summary: str) -> str:
    row = db.execute(
        "SELECT session_id, entry_type FROM timeline WHERE id = ?",
        (timeline_id,),
    ).fetchone()
    if not row:
        raise LoreKitError(f"Timeline entry {timeline_id} not found")
    session_id, entry_type = row
    db.execute(
        "UPDATE timeline SET summary = ? WHERE id = ?",
        (summary, timeline_id),
    )
    db.commit()
    if entry_type == "narration":
        try:
            from lorekit.support.vectordb import index_timeline

            index_timeline(db, session_id, timeline_id, entry_type, summary)
        except Exception:
            pass
    return f"SUMMARY_SET: {timeline_id}"


def cmd_set_summary(db, args):
    tid, p = parse_args(
        args,
        {
            "--summary": ("summary", True, ""),
        },
        positional="timeline_id",
    )
    return set_summary(db, int(tid), p["summary"])


def revert(db, session_id: int) -> str:
    # Find the last narration
    row = db.execute(
        "SELECT id FROM timeline WHERE session_id = ? AND entry_type = 'narration' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
        raise LoreKitError("No narrations to revert")
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

    # Best-effort vector cleanup for deleted narrations with summaries
    if narration_ids_with_summary:
        try:
            from lorekit.support.vectordb import delete_timeline

            delete_timeline(db, narration_ids_with_summary)
        except Exception:
            pass

    breakdown = ", ".join(f"{count} {etype}" for etype, count in sorted(type_counts.items()))
    return f"TIMELINE_REVERTED: {len(ids_to_delete)} entries removed ({breakdown})"


def cmd_revert(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")
    return revert(db, int(sid))


def list_entries(db, session_id: int, entry_type: str = "", last: int = 0, entry_id: str = "") -> str:
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
        return format_table(cur)
    query = "SELECT id, entry_type, content, created_at FROM timeline WHERE session_id = ?"
    params: list = [session_id]
    if entry_type:
        query += " AND entry_type = ?"
        params.append(entry_type)
    if last:
        query += " ORDER BY id DESC LIMIT ?"
        params.append(last)
        # Wrap to re-order ascending
        query = f"SELECT * FROM ({query}) ORDER BY id"
    else:
        query += " ORDER BY id"
    cur = db.execute(query, params)
    return format_table(cur)


def cmd_list(db, args):
    sid, p = parse_args(
        args,
        {
            "--type": ("entry_type", False, ""),
            "--last": ("last", False, ""),
            "--id": ("entry_id", False, ""),
        },
        positional="session_id",
    )
    return list_entries(db, int(sid), p["entry_type"], int(p["last"]) if p["last"] else 0, p["entry_id"])


def search(db, session_id: int, query_text: str) -> str:
    cur = db.execute(
        "SELECT id, entry_type, content, created_at FROM timeline WHERE session_id = ? AND content LIKE ? ORDER BY id",
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
