#!/usr/bin/env python3
"""character.py -- Manage characters and their attributes, inventory, abilities."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, format_table, LoreKitError
from _args import parse_args


def usage():
    print("Usage: python scripts/character.py <action> [args]")
    print()
    print("Actions:")
    print("  create --session <id> --name <name> --level <level> [--type pc|npc] [--region <region_id>]")
    print("  view <character_id>")
    print("  list --session <session_id> [--type pc|npc] [--region <region_id>]")
    print("  update <character_id> [--name <name>] [--level <level>] [--status <status>] [--region <region_id>]")
    print("  set-attr <character_id> --category <cat> --key <key> --value <value>")
    print("  get-attr <character_id> [--category <cat>]")
    print("  set-item <character_id> --name <name> [--desc <desc>] [--qty <n>] [--equipped 0|1]")
    print("  get-items <character_id>")
    print("  remove-item <item_id>")
    print("  set-ability <character_id> --name <name> --desc <desc> --category <cat> [--uses <uses>]")
    print("  get-abilities <character_id>")
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
        "view": cmd_view,
        "list": cmd_list,
        "update": cmd_update,
        "set-attr": cmd_set_attr,
        "get-attr": cmd_get_attr,
        "set-item": cmd_set_item,
        "get-items": cmd_get_items,
        "remove-item": cmd_remove_item,
        "set-ability": cmd_set_ability,
        "get-abilities": cmd_get_abilities,
    }

    fn = actions.get(action)
    if fn is None:
        raise LoreKitError(f"Unknown action: {action}")
    print(fn(db, args))


def cmd_create(db, args):
    _, p = parse_args(args, {
        "--session": ("session", True, ""),
        "--name": ("name", True, ""),
        "--level": ("level", True, ""),
        "--type": ("char_type", False, "pc"),
        "--region": ("region", False, ""),
    })
    if p["char_type"] not in ("pc", "npc"):
        raise LoreKitError("--type must be pc or npc")
    region_val = int(p["region"]) if p["region"] else None
    cur = db.execute(
        "INSERT INTO characters (session_id, name, level, type, region_id) VALUES (?, ?, ?, ?, ?)",
        (int(p["session"]), p["name"], int(p["level"]), p["char_type"], region_val),
    )
    db.commit()
    return f"CHARACTER_CREATED: {cur.lastrowid}"


def cmd_view(db, args):
    cid, _ = parse_args(args, {}, positional="character_id")
    row = db.execute(
        "SELECT c.id, c.session_id, c.name, c.level, c.status, c.type, "
        "COALESCE(r.name, ''), c.created_at "
        "FROM characters c LEFT JOIN regions r ON c.region_id = r.id "
        "WHERE c.id = ?",
        (cid,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"Character {cid} not found")
    lines = [
        f"ID: {row[0]}",
        f"SESSION: {row[1]}",
        f"NAME: {row[2]}",
        f"TYPE: {row[5]}",
        f"LEVEL: {row[3]}",
        f"STATUS: {row[4]}",
        f"REGION: {row[6]}",
        f"CREATED: {row[7]}",
        "",
        "--- ATTRIBUTES ---",
    ]
    cur = db.execute(
        "SELECT category, key, value FROM character_attributes "
        "WHERE character_id = ? ORDER BY category, key",
        (cid,),
    )
    lines.append(format_table(cur))
    lines.append("")
    lines.append("--- INVENTORY ---")
    cur = db.execute(
        "SELECT id, name, description, quantity, equipped FROM character_inventory "
        "WHERE character_id = ? ORDER BY name",
        (cid,),
    )
    lines.append(format_table(cur))
    lines.append("")
    lines.append("--- ABILITIES ---")
    cur = db.execute(
        "SELECT id, name, category, uses, description FROM character_abilities "
        "WHERE character_id = ? ORDER BY category, name",
        (cid,),
    )
    lines.append(format_table(cur))
    return "\n".join(lines)


def cmd_list(db, args):
    _, p = parse_args(args, {
        "--session": ("session", True, ""),
        "--type": ("char_type", False, ""),
        "--region": ("region", False, ""),
    })
    query = "SELECT id, name, type, level, status FROM characters WHERE session_id = ?"
    params = [p["session"]]
    if p["char_type"]:
        query += " AND type = ?"
        params.append(p["char_type"])
    if p["region"]:
        query += " AND region_id = ?"
        params.append(p["region"])
    query += " ORDER BY id"
    cur = db.execute(query, params)
    return format_table(cur)


def cmd_update(db, args):
    cid, p = parse_args(args, {
        "--name": ("name", False, ""),
        "--level": ("level", False, ""),
        "--status": ("status", False, ""),
        "--region": ("region", False, ""),
    }, positional="character_id")
    _COLUMN_MAP = {"name": ("name", str), "level": ("level", int), "status": ("status", str), "region": ("region_id", int)}
    sets = []
    params = []
    for key, (col, typ) in _COLUMN_MAP.items():
        if p[key]:
            sets.append(f"{col} = ?")
            params.append(typ(p[key]))
    if not sets:
        raise LoreKitError("Provide --name, --level, --status, and/or --region")
    params.append(cid)
    db.execute(f"UPDATE characters SET {','.join(sets)} WHERE id = ?", params)
    db.commit()
    return f"CHARACTER_UPDATED: {cid}"


def cmd_set_attr(db, args):
    cid, p = parse_args(args, {
        "--category": ("category", True, ""),
        "--key": ("key", True, ""),
        "--value": ("value", True, ""),
    }, positional="character_id")
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
        (cid, p["category"], p["key"], p["value"]),
    )
    db.commit()
    return f"ATTR_SET: {p['key']} = {p['value']}"


def cmd_get_attr(db, args):
    cid, p = parse_args(args, {
        "--category": ("category", False, ""),
    }, positional="character_id")
    if p["category"]:
        cur = db.execute(
            "SELECT key, value FROM character_attributes "
            "WHERE character_id = ? AND category = ? ORDER BY key",
            (cid, p["category"]),
        )
    else:
        cur = db.execute(
            "SELECT category, key, value FROM character_attributes "
            "WHERE character_id = ? ORDER BY category, key",
            (cid,),
        )
    return format_table(cur)


def cmd_set_item(db, args):
    cid, p = parse_args(args, {
        "--name": ("name", True, ""),
        "--desc": ("desc", False, ""),
        "--qty": ("qty", False, "1"),
        "--equipped": ("equipped", False, "0"),
    }, positional="character_id")
    cur = db.execute(
        "INSERT INTO character_inventory (character_id, name, description, quantity, equipped) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(character_id, name) DO UPDATE SET "
        "description = excluded.description, quantity = excluded.quantity, equipped = excluded.equipped",
        (cid, p["name"], p["desc"], int(p["qty"]), int(p["equipped"])),
    )
    db.commit()
    return f"ITEM_SET: {cur.lastrowid}"


def cmd_get_items(db, args):
    cid, _ = parse_args(args, {}, positional="character_id")
    cur = db.execute(
        "SELECT id, name, description, quantity, equipped FROM character_inventory "
        "WHERE character_id = ? ORDER BY name",
        (cid,),
    )
    return format_table(cur)


def cmd_remove_item(db, args):
    iid, _ = parse_args(args, {}, positional="item_id")
    db.execute("DELETE FROM character_inventory WHERE id = ?", (iid,))
    db.commit()
    return f"ITEM_REMOVED: {iid}"


def cmd_set_ability(db, args):
    cid, p = parse_args(args, {
        "--name": ("name", True, ""),
        "--desc": ("desc", True, ""),
        "--category": ("category", True, ""),
        "--uses": ("uses", False, "at_will"),
    }, positional="character_id")
    cur = db.execute(
        "INSERT INTO character_abilities (character_id, name, description, category, uses) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(character_id, name) DO UPDATE SET "
        "description = excluded.description, category = excluded.category, uses = excluded.uses",
        (cid, p["name"], p["desc"], p["category"], p["uses"]),
    )
    db.commit()
    return f"ABILITY_SET: {cur.lastrowid}"


def cmd_get_abilities(db, args):
    cid, _ = parse_args(args, {}, positional="character_id")
    cur = db.execute(
        "SELECT id, name, category, uses, description FROM character_abilities "
        "WHERE character_id = ? ORDER BY category, name",
        (cid,),
    )
    return format_table(cur)


if __name__ == "__main__":
    main()
