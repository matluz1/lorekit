#!/usr/bin/env python3
"""session.py -- Manage adventure sessions."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, format_table, error, LoreKitError
from _args import parse_args


def usage():
    print("Usage: python scripts/session.py <action> [args]")
    print()
    print("Actions:")
    print("  create --name <name> --setting <setting> --system <system_type>")
    print("  view <session_id>")
    print("  list [--status active|finished]")
    print("  update <session_id> --status <status>")
    print("  meta-set <session_id> --key <key> --value <value>")
    print("  meta-get <session_id> [--key <key>]")
    sys.exit(1)


def main():
    args = sys.argv[1:]
    if not args:
        usage()

    action = args[0]
    args = args[1:]

    db = require_db()

    actions = {
        "create": cmd_create,
        "view": cmd_view,
        "list": cmd_list,
        "update": cmd_update,
        "meta-set": cmd_meta_set,
        "meta-get": cmd_meta_get,
    }

    fn = actions.get(action)
    if fn is None:
        raise LoreKitError(f"Unknown action: {action}")
    print(fn(db, args))


def cmd_create(db, args):
    _, p = parse_args(args, {
        "--name": ("name", True, ""),
        "--setting": ("setting", True, ""),
        "--system": ("system", True, ""),
    })
    cur = db.execute(
        "INSERT INTO sessions (name, setting, system_type) VALUES (?, ?, ?)",
        (p["name"], p["setting"], p["system"]),
    )
    db.commit()
    return f"SESSION_CREATED: {cur.lastrowid}"


def cmd_view(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")
    row = db.execute(
        "SELECT id, name, setting, system_type, status, created_at, updated_at "
        "FROM sessions WHERE id = ?",
        (sid,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"Session {sid} not found")
    lines = [
        f"ID: {row[0]}",
        f"NAME: {row[1]}",
        f"SETTING: {row[2]}",
        f"SYSTEM: {row[3]}",
        f"STATUS: {row[4]}",
        f"CREATED: {row[5]}",
        f"UPDATED: {row[6]}",
    ]
    return "\n".join(lines)


def cmd_list(db, args):
    _, p = parse_args(args, {
        "--status": ("status", False, ""),
    })
    if p["status"]:
        cur = db.execute(
            "SELECT id, name, setting, system_type, status, created_at "
            "FROM sessions WHERE status = ? ORDER BY id",
            (p["status"],),
        )
    else:
        cur = db.execute(
            "SELECT id, name, setting, system_type, status, created_at "
            "FROM sessions ORDER BY id"
        )
    return format_table(cur)


def cmd_update(db, args):
    sid, p = parse_args(args, {
        "--status": ("status", True, ""),
    }, positional="session_id")
    db.execute(
        "UPDATE sessions SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (p["status"], sid),
    )
    db.commit()
    return f"SESSION_UPDATED: {sid}"


def cmd_meta_set(db, args):
    sid, p = parse_args(args, {
        "--key": ("key", True, ""),
        "--value": ("value", True, ""),
    }, positional="session_id")
    db.execute(
        "INSERT INTO session_meta (session_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(session_id, key) DO UPDATE SET value = excluded.value",
        (sid, p["key"], p["value"]),
    )
    db.commit()
    return f"META_SET: {p['key']}"


def cmd_meta_get(db, args):
    sid, p = parse_args(args, {
        "--key": ("key", False, ""),
    }, positional="session_id")
    if p["key"]:
        row = db.execute(
            "SELECT value FROM session_meta WHERE session_id = ? AND key = ?",
            (sid, p["key"]),
        ).fetchone()
        value = row[0] if row else ""
        return f"{p['key']}: {value}"
    else:
        cur = db.execute(
            "SELECT key, value FROM session_meta WHERE session_id = ? ORDER BY key",
            (sid,),
        )
        return format_table(cur)


if __name__ == "__main__":
    main()
