#!/usr/bin/env python3
"""character.py -- Manage characters and their attributes, inventory, abilities."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, print_table, error


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
        error(f"Unknown action: {action}")
    fn(db, args)


def cmd_create(db, args):
    session = name = ""
    level = "1"
    char_type = "pc"
    region = ""
    i = 0
    while i < len(args):
        if args[i] == "--session":
            session = args[i + 1]; i += 2
        elif args[i] == "--name":
            name = args[i + 1]; i += 2
        elif args[i] == "--level":
            level = args[i + 1]; i += 2
        elif args[i] == "--type":
            char_type = args[i + 1]; i += 2
        elif args[i] == "--region":
            region = args[i + 1]; i += 2
        else:
            error(f"Unknown option: {args[i]}")
    if not session or not name:
        error("--session and --name are required")
    if char_type not in ("pc", "npc"):
        error("--type must be pc or npc")
    region_val = int(region) if region else None
    cur = db.execute(
        "INSERT INTO characters (session_id, name, level, type, region_id) VALUES (?, ?, ?, ?, ?)",
        (int(session), name, int(level), char_type, region_val),
    )
    db.commit()
    print(f"CHARACTER_CREATED: {cur.lastrowid}")


def cmd_view(db, args):
    if not args:
        error("character_id required")
    char_id = args[0]
    row = db.execute(
        "SELECT c.id, c.session_id, c.name, c.level, c.status, c.type, "
        "COALESCE(r.name, ''), c.created_at "
        "FROM characters c LEFT JOIN regions r ON c.region_id = r.id "
        "WHERE c.id = ?",
        (char_id,),
    ).fetchone()
    if row is None:
        error(f"Character {char_id} not found")
    print(f"ID: {row[0]}")
    print(f"SESSION: {row[1]}")
    print(f"NAME: {row[2]}")
    print(f"TYPE: {row[5]}")
    print(f"LEVEL: {row[3]}")
    print(f"STATUS: {row[4]}")
    print(f"REGION: {row[6]}")
    print(f"CREATED: {row[7]}")
    print()
    print("--- ATTRIBUTES ---")
    cur = db.execute(
        "SELECT category, key, value FROM character_attributes "
        "WHERE character_id = ? ORDER BY category, key",
        (char_id,),
    )
    print_table(cur)
    print()
    print("--- INVENTORY ---")
    cur = db.execute(
        "SELECT id, name, description, quantity, equipped FROM character_inventory "
        "WHERE character_id = ? ORDER BY name",
        (char_id,),
    )
    print_table(cur)
    print()
    print("--- ABILITIES ---")
    cur = db.execute(
        "SELECT id, name, category, uses, description FROM character_abilities "
        "WHERE character_id = ? ORDER BY category, name",
        (char_id,),
    )
    print_table(cur)


def cmd_list(db, args):
    session = char_type = region = ""
    i = 0
    while i < len(args):
        if args[i] == "--session":
            session = args[i + 1]; i += 2
        elif args[i] == "--type":
            char_type = args[i + 1]; i += 2
        elif args[i] == "--region":
            region = args[i + 1]; i += 2
        else:
            error(f"Unknown option: {args[i]}")
    if not session:
        error("--session is required")
    query = "SELECT id, name, type, level, status FROM characters WHERE session_id = ?"
    params = [session]
    if char_type:
        query += " AND type = ?"
        params.append(char_type)
    if region:
        query += " AND region_id = ?"
        params.append(region)
    query += " ORDER BY id"
    cur = db.execute(query, params)
    print_table(cur)


def cmd_update(db, args):
    if not args:
        error("character_id required")
    char_id = args[0]
    rest = args[1:]
    sets = []
    params = []
    i = 0
    while i < len(rest):
        if rest[i] == "--name":
            sets.append("name = ?")
            params.append(rest[i + 1]); i += 2
        elif rest[i] == "--level":
            sets.append("level = ?")
            params.append(int(rest[i + 1])); i += 2
        elif rest[i] == "--status":
            sets.append("status = ?")
            params.append(rest[i + 1]); i += 2
        elif rest[i] == "--region":
            sets.append("region_id = ?")
            params.append(int(rest[i + 1])); i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not sets:
        error("Provide --name, --level, --status, and/or --region")
    params.append(char_id)
    db.execute(f"UPDATE characters SET {','.join(sets)} WHERE id = ?", params)
    db.commit()
    print(f"CHARACTER_UPDATED: {char_id}")


def cmd_set_attr(db, args):
    if not args:
        error("character_id required")
    char_id = args[0]
    rest = args[1:]
    category = key = value = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--category":
            category = rest[i + 1]; i += 2
        elif rest[i] == "--key":
            key = rest[i + 1]; i += 2
        elif rest[i] == "--value":
            value = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not category or not key or not value:
        error("--category, --key, and --value are required")
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
        (char_id, category, key, value),
    )
    db.commit()
    print(f"ATTR_SET: {key} = {value}")


def cmd_get_attr(db, args):
    if not args:
        error("character_id required")
    char_id = args[0]
    rest = args[1:]
    category = ""
    i = 0
    while i < len(rest):
        if rest[i] == "--category":
            category = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if category:
        cur = db.execute(
            "SELECT key, value FROM character_attributes "
            "WHERE character_id = ? AND category = ? ORDER BY key",
            (char_id, category),
        )
    else:
        cur = db.execute(
            "SELECT category, key, value FROM character_attributes "
            "WHERE character_id = ? ORDER BY category, key",
            (char_id,),
        )
    print_table(cur)


def cmd_set_item(db, args):
    if not args:
        error("character_id required")
    char_id = args[0]
    rest = args[1:]
    name = ""
    desc = ""
    qty = 1
    equipped = 0
    i = 0
    while i < len(rest):
        if rest[i] == "--name":
            name = rest[i + 1]; i += 2
        elif rest[i] == "--desc":
            desc = rest[i + 1]; i += 2
        elif rest[i] == "--qty":
            qty = int(rest[i + 1]); i += 2
        elif rest[i] == "--equipped":
            equipped = int(rest[i + 1]); i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not name:
        error("--name is required")
    cur = db.execute(
        "INSERT INTO character_inventory (character_id, name, description, quantity, equipped) "
        "VALUES (?, ?, ?, ?, ?)",
        (char_id, name, desc, qty, equipped),
    )
    db.commit()
    print(f"ITEM_ADDED: {cur.lastrowid}")


def cmd_get_items(db, args):
    if not args:
        error("character_id required")
    char_id = args[0]
    cur = db.execute(
        "SELECT id, name, description, quantity, equipped FROM character_inventory "
        "WHERE character_id = ? ORDER BY name",
        (char_id,),
    )
    print_table(cur)


def cmd_remove_item(db, args):
    if not args:
        error("item_id required")
    item_id = args[0]
    db.execute("DELETE FROM character_inventory WHERE id = ?", (item_id,))
    db.commit()
    print(f"ITEM_REMOVED: {item_id}")


def cmd_set_ability(db, args):
    if not args:
        error("character_id required")
    char_id = args[0]
    rest = args[1:]
    name = desc = category = ""
    uses = "at_will"
    i = 0
    while i < len(rest):
        if rest[i] == "--name":
            name = rest[i + 1]; i += 2
        elif rest[i] == "--desc":
            desc = rest[i + 1]; i += 2
        elif rest[i] == "--category":
            category = rest[i + 1]; i += 2
        elif rest[i] == "--uses":
            uses = rest[i + 1]; i += 2
        else:
            error(f"Unknown option: {rest[i]}")
    if not name or not desc or not category:
        error("--name, --desc, and --category are required")
    cur = db.execute(
        "INSERT INTO character_abilities (character_id, name, description, category, uses) "
        "VALUES (?, ?, ?, ?, ?)",
        (char_id, name, desc, category, uses),
    )
    db.commit()
    print(f"ABILITY_ADDED: {cur.lastrowid}")


def cmd_get_abilities(db, args):
    if not args:
        error("character_id required")
    char_id = args[0]
    cur = db.execute(
        "SELECT id, name, category, uses, description FROM character_abilities "
        "WHERE character_id = ? ORDER BY category, name",
        (char_id,),
    )
    print_table(cur)


if __name__ == "__main__":
    main()
