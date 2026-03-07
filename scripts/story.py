#!/usr/bin/env python3
"""story.py -- Manage story arcs and act-based pacing within a session."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, format_table, LoreKitError
from _args import parse_args


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
        raise LoreKitError(f"Unknown action: {action}")
    print(fn(db, args))


def cmd_set(db, args):
    sid, p = parse_args(args, {
        "--size": ("size", True, ""),
        "--premise": ("premise", True, ""),
    }, positional="session_id")
    db.execute(
        "INSERT INTO stories (session_id, adventure_size, premise) VALUES (?, ?, ?)"
        " ON CONFLICT(session_id) DO UPDATE SET adventure_size = excluded.adventure_size,"
        " premise = excluded.premise",
        (sid, p["size"], p["premise"]),
    )
    db.commit()
    return f"STORY_SET: {sid}"


def cmd_view(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")
    row = db.execute(
        "SELECT id, session_id, adventure_size, premise, created_at FROM stories WHERE session_id = ?",
        (sid,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"No story found for session {sid}")
    lines = [
        f"ID: {row[0]}",
        f"SESSION: {row[1]}",
        f"SIZE: {row[2]}",
        f"PREMISE: {row[3]}",
        f"CREATED: {row[4]}",
        "",
        "--- ACTS ---",
    ]
    cur = db.execute(
        "SELECT act_order, title, status FROM story_acts WHERE session_id = ? ORDER BY act_order",
        (sid,),
    )
    lines.append(format_table(cur))
    return "\n".join(lines)


def cmd_add_act(db, args):
    sid, p = parse_args(args, {
        "--title": ("title", True, ""),
        "--desc": ("desc", False, ""),
        "--goal": ("goal", False, ""),
        "--event": ("event", False, ""),
    }, positional="session_id")
    row = db.execute(
        "SELECT COALESCE(MAX(act_order), 0) FROM story_acts WHERE session_id = ?",
        (sid,),
    ).fetchone()
    next_order = row[0] + 1
    cur = db.execute(
        "INSERT INTO story_acts (session_id, act_order, title, description, goal, event)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (sid, next_order, p["title"], p["desc"], p["goal"], p["event"]),
    )
    db.commit()
    return f"ACT_ADDED: {cur.lastrowid}"


def cmd_view_act(db, args):
    aid, _ = parse_args(args, {}, positional="act_id")
    row = db.execute(
        "SELECT id, session_id, act_order, title, description, goal, event, status, created_at"
        " FROM story_acts WHERE id = ?",
        (aid,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"Act {aid} not found")
    lines = [
        f"ID: {row[0]}",
        f"SESSION: {row[1]}",
        f"ORDER: {row[2]}",
        f"TITLE: {row[3]}",
        f"DESCRIPTION: {row[4]}",
        f"GOAL: {row[5]}",
        f"EVENT: {row[6]}",
        f"STATUS: {row[7]}",
        f"CREATED: {row[8]}",
    ]
    return "\n".join(lines)


def cmd_update_act(db, args):
    aid, p = parse_args(args, {
        "--title": ("title", False, ""),
        "--desc": ("desc", False, ""),
        "--goal": ("goal", False, ""),
        "--event": ("event", False, ""),
        "--status": ("status", False, ""),
    }, positional="act_id")
    _COLUMN_MAP = {"title": "title", "desc": "description", "goal": "goal", "event": "event", "status": "status"}
    sets = []
    params = []
    for key, col in _COLUMN_MAP.items():
        if p[key]:
            sets.append(f"{col} = ?")
            params.append(p[key])
    if not sets:
        raise LoreKitError("Provide at least one option to update")
    params.append(aid)
    db.execute(f"UPDATE story_acts SET {','.join(sets)} WHERE id = ?", params)
    db.commit()
    return f"ACT_UPDATED: {aid}"


def cmd_advance(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")
    active = db.execute(
        "SELECT id, act_order FROM story_acts WHERE session_id = ? AND status = 'active'"
        " ORDER BY act_order LIMIT 1",
        (sid,),
    ).fetchone()
    if active is None:
        raise LoreKitError("No active act to advance")
    active_id, active_order = active
    db.execute("UPDATE story_acts SET status = 'completed' WHERE id = ?", (active_id,))
    next_act = db.execute(
        "SELECT id, act_order FROM story_acts WHERE session_id = ? AND act_order > ? AND status = 'pending'"
        " ORDER BY act_order LIMIT 1",
        (sid, active_order),
    ).fetchone()
    if next_act is None:
        db.commit()
        return f"ACT_ADVANCED: completed act {active_order}, no remaining acts"
    db.execute("UPDATE story_acts SET status = 'active' WHERE id = ?", (next_act[0],))
    db.commit()
    return f"ACT_ADVANCED: completed act {active_order}, activated act {next_act[1]}"


if __name__ == "__main__":
    main()
