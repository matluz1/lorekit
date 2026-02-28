#!/usr/bin/env python3
"""story.py -- Manage story arcs and act-based pacing within a session."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, print_table, error


def usage():
    print("Usage: python scripts/story.py <action> [args]")
    print()
    print("Actions:")
    print("  set <session_id> --size <size> --premise <text>")
    print("  view <session_id>")
    print("  add-act <session_id> --title <t> [--desc <d>] [--goal <g>] [--event <e>]")
    print("  view-act <act_id>")
    print("  update-act <act_id> [--title <t>] [--desc <d>] [--goal <g>] [--event <e>] [--status <s>]")
    print("  advance <session_id>")
    sys.exit(1)


def main():
    argv = sys.argv[1:]
    if not argv:
        usage()

    action = argv[0]
    args = argv[1:]

    db = require_db()

    actions = {
        "set": cmd_set,
        "view": cmd_view,
        "add-act": cmd_add_act,
        "view-act": cmd_view_act,
        "update-act": cmd_update_act,
        "advance": cmd_advance,
    }

    fn = actions.get(action)
    if fn is None:
        error(f"Unknown action: {action}")
    fn(db, args)


def cmd_set(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    size = premise = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--size":
            size = rest[i + 1]; i += 2
        elif rest[i] == "--premise":
            premise = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not size:
        error("--size is required")
    if not premise:
        error("--premise is required")
    db.execute(
        "INSERT INTO stories (session_id, adventure_size, premise) VALUES (?, ?, ?)"
        " ON CONFLICT(session_id) DO UPDATE SET adventure_size = excluded.adventure_size,"
        " premise = excluded.premise",
        (session_id, size, premise),
    )
    db.commit()
    print(f"STORY_SET: {session_id}")


def cmd_view(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    row = db.execute(
        "SELECT id, session_id, adventure_size, premise, created_at FROM stories WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        error(f"No story found for session {session_id}")
    print(f"ID: {row[0]}")
    print(f"SESSION: {row[1]}")
    print(f"SIZE: {row[2]}")
    print(f"PREMISE: {row[3]}")
    print(f"CREATED: {row[4]}")
    print()
    print("--- ACTS ---")
    cur = db.execute(
        "SELECT act_order, title, status FROM story_acts WHERE session_id = ? ORDER BY act_order",
        (session_id,),
    )
    print_table(cur)


def cmd_add_act(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    title = desc = goal = event = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--title":
            title = rest[i + 1]; i += 2
        elif rest[i] == "--desc":
            desc = rest[i + 1]; i += 2
        elif rest[i] == "--goal":
            goal = rest[i + 1]; i += 2
        elif rest[i] == "--event":
            event = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not title:
        error("--title is required")
    # Auto-assign order: max existing + 1
    row = db.execute(
        "SELECT COALESCE(MAX(act_order), 0) FROM story_acts WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    next_order = row[0] + 1
    cur = db.execute(
        "INSERT INTO story_acts (session_id, act_order, title, description, goal, event)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, next_order, title, desc, goal, event),
    )
    db.commit()
    print(f"ACT_ADDED: {cur.lastrowid}")


def cmd_view_act(db, args):
    if not args:
        error("act_id required")
    act_id = args[0]
    row = db.execute(
        "SELECT id, session_id, act_order, title, description, goal, event, status, created_at"
        " FROM story_acts WHERE id = ?",
        (act_id,),
    ).fetchone()
    if row is None:
        error(f"Act {act_id} not found")
    print(f"ID: {row[0]}")
    print(f"SESSION: {row[1]}")
    print(f"ORDER: {row[2]}")
    print(f"TITLE: {row[3]}")
    print(f"DESCRIPTION: {row[4]}")
    print(f"GOAL: {row[5]}")
    print(f"EVENT: {row[6]}")
    print(f"STATUS: {row[7]}")
    print(f"CREATED: {row[8]}")


def cmd_update_act(db, args):
    if not args:
        error("act_id required")
    act_id = args[0]
    rest = args[1:]
    sets = []
    params = []
    i = 0
    while i < len(rest):
        if rest[i] == "--title":
            sets.append("title = ?")
            params.append(rest[i + 1]); i += 2
        elif rest[i] == "--desc":
            sets.append("description = ?")
            params.append(rest[i + 1]); i += 2
        elif rest[i] == "--goal":
            sets.append("goal = ?")
            params.append(rest[i + 1]); i += 2
        elif rest[i] == "--event":
            sets.append("event = ?")
            params.append(rest[i + 1]); i += 2
        elif rest[i] == "--status":
            sets.append("status = ?")
            params.append(rest[i + 1]); i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not sets:
        error("Provide at least one option to update")
    params.append(act_id)
    db.execute(f"UPDATE story_acts SET {','.join(sets)} WHERE id = ?", params)
    db.commit()
    print(f"ACT_UPDATED: {act_id}")


def cmd_advance(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    # Find the current active act
    active = db.execute(
        "SELECT id, act_order FROM story_acts WHERE session_id = ? AND status = 'active'"
        " ORDER BY act_order LIMIT 1",
        (session_id,),
    ).fetchone()
    if active is None:
        error("No active act to advance")
    active_id, active_order = active
    # Complete the active act
    db.execute("UPDATE story_acts SET status = 'completed' WHERE id = ?", (active_id,))
    # Activate the next pending act
    next_act = db.execute(
        "SELECT id, act_order FROM story_acts WHERE session_id = ? AND act_order > ? AND status = 'pending'"
        " ORDER BY act_order LIMIT 1",
        (session_id, active_order),
    ).fetchone()
    if next_act is None:
        db.commit()
        print(f"ACT_ADVANCED: completed act {active_order}, no remaining acts")
        return
    db.execute("UPDATE story_acts SET status = 'active' WHERE id = ?", (next_act[0],))
    db.commit()
    print(f"ACT_ADVANCED: completed act {active_order}, activated act {next_act[1]}")


if __name__ == "__main__":
    main()
