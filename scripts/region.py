#!/usr/bin/env python3
"""region.py -- Manage regions (locations, areas) within a session."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, print_table, error


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
        error(f"Unknown action: {action}")
    fn(db, args)


def cmd_create(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    name = desc = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--name":
            name = rest[i + 1]; i += 2
        elif rest[i] == "--desc":
            desc = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not name:
        error("--name is required")
    cur = db.execute(
        "INSERT INTO regions (session_id, name, description) VALUES (?, ?, ?)",
        (session_id, name, desc),
    )
    db.commit()
    print(f"REGION_CREATED: {cur.lastrowid}")


def cmd_list(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    cur = db.execute(
        "SELECT id, name, description, created_at FROM regions WHERE session_id = ? ORDER BY id",
        (session_id,),
    )
    print_table(cur)


def cmd_view(db, args):
    if not args:
        error("region_id required")
    region_id = args[0]
    row = db.execute(
        "SELECT id, session_id, name, description, created_at FROM regions WHERE id = ?",
        (region_id,),
    ).fetchone()
    if row is None:
        error(f"Region {region_id} not found")
    print(f"ID: {row[0]}")
    print(f"SESSION: {row[1]}")
    print(f"NAME: {row[2]}")
    print(f"DESCRIPTION: {row[3]}")
    print(f"CREATED: {row[4]}")
    print()
    print("--- NPCs IN THIS REGION ---")
    cur = db.execute(
        "SELECT id, name, level, status FROM characters WHERE region_id = ? AND type = 'npc' ORDER BY id",
        (region_id,),
    )
    print_table(cur)


def cmd_update(db, args):
    if not args:
        error("region_id required")
    region_id = args[0]
    rest = args[1:]
    sets = []
    params = []
    i = 0
    while i < len(rest):
        if rest[i] == "--name":
            sets.append("name = ?")
            params.append(rest[i + 1]); i += 2
        elif rest[i] == "--desc":
            sets.append("description = ?")
            params.append(rest[i + 1]); i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not sets:
        error("Provide --name and/or --desc")
    params.append(region_id)
    db.execute(f"UPDATE regions SET {','.join(sets)} WHERE id = ?", params)
    db.commit()
    print(f"REGION_UPDATED: {region_id}")


if __name__ == "__main__":
    main()
