#!/usr/bin/env python3
"""session.py -- Manage adventure sessions."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, format_table, error, LoreKitError


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
            raise LoreKitError(f"Unknown option: {args[i]}")
    if not name or not setting or not system:
        raise LoreKitError("--name, --setting, and --system are required")
    cur = db.execute(
        "INSERT INTO sessions (name, setting, system_type) VALUES (?, ?, ?)",
        (name, setting, system),
    )
    db.commit()
    return f"SESSION_CREATED: {cur.lastrowid}"


def cmd_view(db, args):
    if not args:
        raise LoreKitError("session_id required")
    session_id = args[0]
    row = db.execute(
        "SELECT id, name, setting, system_type, status, created_at, updated_at "
        "FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"Session {session_id} not found")
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
    status = None
    i = 0
    while i < len(args):
        if args[i] == "--status":
            status = args[i + 1]; i += 2
        else:
            raise LoreKitError(f"Unknown option: {args[i]}")
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
    return format_table(cur)


def cmd_update(db, args):
    if not args:
        raise LoreKitError("session_id required")
    session_id = args[0]
    rest = args[1:]
    status = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--status":
            status = rest[i + 1]; i += 2
        else:
            raise LoreKitError(f"Unknown option: {rest[i]}")
    if not status:
        raise LoreKitError("--status is required")
    db.execute(
        "UPDATE sessions SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (status, session_id),
    )
    db.commit()
    return f"SESSION_UPDATED: {session_id}"


def cmd_meta_set(db, args):
    if not args:
        raise LoreKitError("session_id required")
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
            raise LoreKitError(f"Unknown option: {rest[i]}")
    if not key or not value:
        raise LoreKitError("--key and --value are required")
    db.execute(
        "INSERT INTO session_meta (session_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(session_id, key) DO UPDATE SET value = excluded.value",
        (session_id, key, value),
    )
    db.commit()
    return f"META_SET: {key}"


def cmd_meta_get(db, args):
    if not args:
        raise LoreKitError("session_id required")
    session_id = args[0]
    rest = args[1:]
    key = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--key":
            key = rest[i + 1]; i += 2
        else:
            raise LoreKitError(f"Unknown option: {rest[i]}")
    if key:
        row = db.execute(
            "SELECT value FROM session_meta WHERE session_id = ? AND key = ?",
            (session_id, key),
        ).fetchone()
        value = row[0] if row else ""
        return f"{key}: {value}"
    else:
        cur = db.execute(
            "SELECT key, value FROM session_meta WHERE session_id = ? ORDER BY key",
            (session_id,),
        )
        return format_table(cur)


if __name__ == "__main__":
    main()
