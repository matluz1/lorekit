#!/usr/bin/env python3
"""session.py -- Manage adventure sessions."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, print_table, error


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
        error(f"Unknown action: {action}")
    fn(db, args)


def cmd_create(db, args):
    name = setting = system = ""
    i = 0
    while i < len(args):
        if args[i] == "--name":
            name = args[i + 1]; i += 2
        elif args[i] == "--setting":
            setting = args[i + 1]; i += 2
        elif args[i] == "--system":
            system = args[i + 1]; i += 2
        else:
            error(f"Unknown option: {args[i]}")
    if not name or not setting or not system:
        error("--name, --setting, and --system are required")
    cur = db.execute(
        "INSERT INTO sessions (name, setting, system_type) VALUES (?, ?, ?)",
        (name, setting, system),
    )
    db.commit()
    print(f"SESSION_CREATED: {cur.lastrowid}")


def cmd_view(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    row = db.execute(
        "SELECT id, name, setting, system_type, status, created_at, updated_at "
        "FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        error(f"Session {session_id} not found")
    print(f"ID: {row[0]}")
    print(f"NAME: {row[1]}")
    print(f"SETTING: {row[2]}")
    print(f"SYSTEM: {row[3]}")
    print(f"STATUS: {row[4]}")
    print(f"CREATED: {row[5]}")
    print(f"UPDATED: {row[6]}")


def cmd_list(db, args):
    status = None
    i = 0
    while i < len(args):
        if args[i] == "--status":
            status = args[i + 1]; i += 2
        else:
            error(f"Unknown option: {args[i]}")
    if status:
        cur = db.execute(
            "SELECT id, name, setting, system_type, status, created_at "
            "FROM sessions WHERE status = ? ORDER BY id",
            (status,),
        )
    else:
        cur = db.execute(
            "SELECT id, name, setting, system_type, status, created_at "
            "FROM sessions ORDER BY id"
        )
    print_table(cur)


def cmd_update(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    status = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--status":
            status = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not status:
        error("--status is required")
    db.execute(
        "UPDATE sessions SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (status, session_id),
    )
    db.commit()
    print(f"SESSION_UPDATED: {session_id}")


def cmd_meta_set(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    key = value = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--key":
            key = rest[i + 1]; i += 2
        elif rest[i] == "--value":
            value = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not key or not value:
        error("--key and --value are required")
    db.execute(
        "INSERT INTO session_meta (session_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(session_id, key) DO UPDATE SET value = excluded.value",
        (session_id, key, value),
    )
    db.commit()
    print(f"META_SET: {key}")


def cmd_meta_get(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]
    rest = args[1:]
    key = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--key":
            key = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if key:
        row = db.execute(
            "SELECT value FROM session_meta WHERE session_id = ? AND key = ?",
            (session_id, key),
        ).fetchone()
        value = row[0] if row else ""
        print(f"{key}: {value}")
    else:
        cur = db.execute(
            "SELECT key, value FROM session_meta WHERE session_id = ? ORDER BY key",
            (session_id,),
        )
        print_table(cur)


if __name__ == "__main__":
    main()
