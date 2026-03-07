#!/usr/bin/env python3
"""region.py -- Manage regions (locations, areas) within a session."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, format_table, LoreKitError
from _args import parse_args


def usage():
    print("Usage: python scripts/region.py <action> [args]")
    print()
    print("Actions:")
    print("  create <session_id> --name <name> --desc <description>")
    print("  list <session_id>")
    print("  view <region_id>")
    print("  update <region_id> --name <name> --desc <description>")
    sys.exit(1)


def main():
    argv = sys.argv[1:]
    if not argv:
        usage()

    action = argv[0]
    args = argv[1:]

    db = require_db()

    actions = {
        "create": cmd_create,
        "list": cmd_list,
        "view": cmd_view,
        "update": cmd_update,
    }

    fn = actions.get(action)
    if fn is None:
        raise LoreKitError(f"Unknown action: {action}")
    print(fn(db, args))


def cmd_create(db, args):
    sid, p = parse_args(args, {
        "--name": ("name", True, ""),
        "--desc": ("desc", False, ""),
    }, positional="session_id")
    cur = db.execute(
        "INSERT INTO regions (session_id, name, description) VALUES (?, ?, ?)",
        (sid, p["name"], p["desc"]),
    )
    db.commit()
    return f"REGION_CREATED: {cur.lastrowid}"


def cmd_list(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")
    cur = db.execute(
        "SELECT id, name, description, created_at FROM regions WHERE session_id = ? ORDER BY id",
        (sid,),
    )
    return format_table(cur)


def cmd_view(db, args):
    rid, _ = parse_args(args, {}, positional="region_id")
    row = db.execute(
        "SELECT id, session_id, name, description, created_at FROM regions WHERE id = ?",
        (rid,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"Region {rid} not found")
    lines = [
        f"ID: {row[0]}",
        f"SESSION: {row[1]}",
        f"NAME: {row[2]}",
        f"DESCRIPTION: {row[3]}",
        f"CREATED: {row[4]}",
        "",
        "--- NPCs IN THIS REGION ---",
    ]
    cur = db.execute(
        "SELECT id, name, level, status FROM characters WHERE region_id = ? AND type = 'npc' ORDER BY id",
        (rid,),
    )
    lines.append(format_table(cur))
    return "\n".join(lines)


def cmd_update(db, args):
    rid, p = parse_args(args, {
        "--name": ("name", False, ""),
        "--desc": ("desc", False, ""),
    }, positional="region_id")
    _COLUMN_MAP = {"name": "name", "desc": "description"}
    sets = []
    params = []
    for key, col in _COLUMN_MAP.items():
        if p[key]:
            sets.append(f"{col} = ?")
            params.append(p[key])
    if not sets:
        raise LoreKitError("Provide --name and/or --desc")
    params.append(rid)
    db.execute(f"UPDATE regions SET {','.join(sets)} WHERE id = ?", params)
    db.commit()
    return f"REGION_UPDATED: {rid}"


if __name__ == "__main__":
    main()
