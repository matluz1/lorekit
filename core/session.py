#!/usr/bin/env python3
"""session.py -- Manage adventure sessions."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _args import parse_args
from _db import LoreKitError, error, format_table, require_db


def usage():
    print("Usage: python core/session.py <action> [args]")
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


def create(db, name: str, setting: str, system: str) -> str:
    cur = db.execute(
        "INSERT INTO sessions (name, setting, system_type) VALUES (?, ?, ?)",
        (name, setting, system),
    )
    db.commit()
    return f"SESSION_CREATED: {cur.lastrowid}"


def cmd_create(db, args):
    _, p = parse_args(
        args,
        {
            "--name": ("name", True, ""),
            "--setting": ("setting", True, ""),
            "--system": ("system", True, ""),
        },
    )
    return create(db, p["name"], p["setting"], p["system"])


def view(db, session_id: int) -> str:
    row = db.execute(
        "SELECT id, name, setting, system_type, status, created_at, updated_at FROM sessions WHERE id = ?",
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


def cmd_view(db, args):
    sid, _ = parse_args(args, {}, positional="session_id")
    return view(db, int(sid))


def list_sessions(db, status: str = "") -> str:
    if status:
        cur = db.execute(
            "SELECT id, name, setting, system_type, status, created_at FROM sessions WHERE status = ? ORDER BY id",
            (status,),
        )
    else:
        cur = db.execute("SELECT id, name, setting, system_type, status, created_at FROM sessions ORDER BY id")
    return format_table(cur)


def cmd_list(db, args):
    _, p = parse_args(
        args,
        {
            "--status": ("status", False, ""),
        },
    )
    return list_sessions(db, p["status"])


def update(db, session_id: int, status: str) -> str:
    db.execute(
        "UPDATE sessions SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (status, session_id),
    )
    db.commit()
    return f"SESSION_UPDATED: {session_id}"


def cmd_update(db, args):
    sid, p = parse_args(
        args,
        {
            "--status": ("status", True, ""),
        },
        positional="session_id",
    )
    return update(db, int(sid), p["status"])


def meta_set(db, session_id: int, key: str, value: str) -> str:
    db.execute(
        "INSERT INTO session_meta (session_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(session_id, key) DO UPDATE SET value = excluded.value",
        (session_id, key, value),
    )
    db.commit()
    return f"META_SET: {key}"


def cmd_meta_set(db, args):
    sid, p = parse_args(
        args,
        {
            "--key": ("key", True, ""),
            "--value": ("value", True, ""),
        },
        positional="session_id",
    )
    return meta_set(db, int(sid), p["key"], p["value"])


def meta_get(db, session_id: int, key: str = "") -> str:
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


def cmd_meta_get(db, args):
    sid, p = parse_args(
        args,
        {
            "--key": ("key", False, ""),
        },
        positional="session_id",
    )
    return meta_get(db, int(sid), p["key"])


if __name__ == "__main__":
    main()
