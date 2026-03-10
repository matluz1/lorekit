#!/usr/bin/env python3
"""region.py -- Manage regions (locations, areas) within a session."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, format_table, LoreKitError
from _args import parse_args


def usage():
    print("Usage: python core/region.py <action> [args]")
    print()
    print("Actions:")
    print("  create <session_id> --name <name> [--desc <description>] [--parent <region_id>]")
    print("  list <session_id>")
    print("  view <region_id>")
    print("  update <region_id> [--name <name>] [--desc <description>] [--parent <region_id>]")
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


def create(db, session_id: int, name: str, desc: str = "", parent_id: int = 0) -> str:
    parent_val = parent_id if parent_id else None
    cur = db.execute(
        "INSERT INTO regions (session_id, name, description, parent_id) VALUES (?, ?, ?, ?)",
        (session_id, name, desc, parent_val),
    )
    db.commit()
    return f"REGION_CREATED: {cur.lastrowid}"


def cmd_create(db, args):
    sid, p = parse_args(args, {
        "--name": ("name", True, ""),
        "--desc": ("desc", False, ""),
        "--parent": ("parent_id", False, ""),
    }, positional="session_id")
    return create(db, int(sid), p["name"], p["desc"], int(p["parent_id"]) if p["parent_id"] else 0)


def list_regions(db, session_id: int) -> str:
    cur = db.execute(
        "SELECT r.id, r.name, r.description, p.name AS parent, r.created_at "
        "FROM regions r LEFT JOIN regions p ON r.parent_id = p.id "
        "WHERE r.session_id = ? ORDER BY r.id",
        (session_id,),
    )
    return format_table(cur)


def cmd_list(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")
    return list_regions(db, int(sid))


def view(db, region_id: int) -> str:
    row = db.execute(
        "SELECT r.id, r.session_id, r.name, r.description, r.parent_id, r.created_at "
        "FROM regions r WHERE r.id = ?",
        (region_id,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"Region {region_id} not found")
    rid, session_id, name, description, parent_id, created_at = row
    lines = [
        f"ID: {rid}",
        f"SESSION: {session_id}",
        f"NAME: {name}",
        f"DESCRIPTION: {description}",
    ]
    if parent_id:
        parent = db.execute("SELECT name FROM regions WHERE id = ?", (parent_id,)).fetchone()
        lines.append(f"PARENT: {parent[0]} (id={parent_id})" if parent else f"PARENT: id={parent_id}")
    lines.append(f"CREATED: {created_at}")

    # Sub-regions
    sub = db.execute(
        "SELECT id, name FROM regions WHERE parent_id = ? ORDER BY id",
        (rid,),
    ).fetchall()
    if sub:
        lines.append("")
        lines.append("--- SUB-REGIONS ---")
        for sr in sub:
            lines.append(f"  [{sr[0]}] {sr[1]}")

    lines.append("")
    lines.append("--- NPCs IN THIS REGION ---")
    cur = db.execute(
        "SELECT id, name, level, status FROM characters WHERE region_id = ? AND type = 'npc' ORDER BY id",
        (region_id,),
    )
    lines.append(format_table(cur))
    return "\n".join(lines)


def cmd_view(db, args):
    rid, _ = parse_args(args, {}, positional="region_id")
    return view(db, int(rid))


def update(db, region_id: int, name: str = "", desc: str = "", parent_id: int = 0) -> str:
    _COLUMN_MAP = {"name": "name", "desc": "description"}
    values = {"name": name, "desc": desc}
    sets = []
    params = []
    for key, col in _COLUMN_MAP.items():
        if values[key]:
            sets.append(f"{col} = ?")
            params.append(values[key])
    if parent_id:
        sets.append("parent_id = ?")
        params.append(parent_id)
    if not sets:
        raise LoreKitError("Provide name, desc, and/or parent")
    params.append(region_id)
    db.execute(f"UPDATE regions SET {','.join(sets)} WHERE id = ?", params)
    db.commit()
    return f"REGION_UPDATED: {region_id}"


def cmd_update(db, args):
    rid, p = parse_args(args, {
        "--name": ("name", False, ""),
        "--desc": ("desc", False, ""),
        "--parent": ("parent_id", False, ""),
    }, positional="region_id")
    return update(db, int(rid), p["name"], p["desc"], int(p["parent_id"]) if p["parent_id"] else 0)


if __name__ == "__main__":
    main()
