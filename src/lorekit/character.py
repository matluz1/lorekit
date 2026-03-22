#!/usr/bin/env python3
"""character.py -- Manage characters and their attributes, inventory, abilities."""

import sys

from lorekit.args import parse_args
from lorekit.db import LoreKitError, format_table, require_db


def usage():
    print("Usage: python core/character.py <action> [args]")
    print()
    print("Actions:")
    print(
        "  create --session <id> --name <name> --level <level> [--type pc|npc] [--gender <gender>] [--region <region_id>]"
    )
    print("  view <character_id>")
    print("  list --session <session_id> [--type pc|npc] [--region <region_id>]")
    print(
        "  update <character_id> [--name <name>] [--gender <gender>] [--level <level>] [--status <status>] [--region <region_id>]"
    )
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


def create(
    db, session_id: int, name: str, level: int, char_type: str = "pc", region_id: int = 0, gender: str = ""
) -> str:
    if char_type not in ("pc", "npc"):
        raise LoreKitError("type must be pc or npc")
    region_val = region_id if region_id else None
    cur = db.execute(
        "INSERT INTO characters (session_id, name, gender, level, type, region_id) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, name, gender, level, char_type, region_val),
    )
    db.commit()
    return f"CHARACTER_CREATED: {cur.lastrowid}"


def cmd_create(db, args):
    _, p = parse_args(
        args,
        {
            "--session": ("session", True, ""),
            "--name": ("name", True, ""),
            "--level": ("level", True, ""),
            "--type": ("char_type", False, "pc"),
            "--region": ("region", False, ""),
            "--gender": ("gender", False, ""),
        },
    )
    return create(
        db,
        int(p["session"]),
        p["name"],
        int(p["level"]),
        p["char_type"],
        int(p["region"]) if p["region"] else 0,
        p["gender"],
    )


def view(db, character_id: int) -> str:
    row = db.execute(
        "SELECT c.id, c.session_id, c.name, c.gender, c.level, c.status, c.type, "
        "COALESCE(r.name, ''), c.created_at "
        "FROM characters c LEFT JOIN regions r ON c.region_id = r.id "
        "WHERE c.id = ?",
        (character_id,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"Character {character_id} not found")
    lines = [
        f"ID: {row[0]}",
        f"SESSION: {row[1]}",
        f"NAME: {row[2]}",
        f"GENDER: {row[3]}",
        f"TYPE: {row[6]}",
        f"LEVEL: {row[4]}",
        f"STATUS: {row[5]}",
        f"REGION: {row[7]}",
        f"CREATED: {row[8]}",
        "",
        "--- ATTRIBUTES ---",
    ]
    cur = db.execute(
        "SELECT category, key, value FROM character_attributes WHERE character_id = ? ORDER BY category, key",
        (character_id,),
    )
    lines.append(format_table(cur))
    lines.append("")
    lines.append("--- INVENTORY ---")
    cur = db.execute(
        "SELECT id, name, description, quantity, equipped FROM character_inventory "
        "WHERE character_id = ? ORDER BY name",
        (character_id,),
    )
    lines.append(format_table(cur))
    lines.append("")
    lines.append("--- ABILITIES ---")
    cur = db.execute(
        "SELECT id, name, category, uses, description FROM character_abilities "
        "WHERE character_id = ? ORDER BY category, name",
        (character_id,),
    )
    lines.append(format_table(cur))

    # NPC-specific sections
    if row[6] == "npc":
        session_id = row[1]

        # NPC core identity
        core_row = db.execute(
            "SELECT self_concept, current_goals, emotional_state, relationships, behavioral_patterns "
            "FROM npc_core WHERE session_id = ? AND npc_id = ?",
            (session_id, character_id),
        ).fetchone()
        if core_row:
            lines.append("")
            lines.append("--- NPC CORE ---")
            labels = ["SELF_CONCEPT", "CURRENT_GOALS", "EMOTIONAL_STATE", "RELATIONSHIPS", "BEHAVIORAL_PATTERNS"]
            for label, val in zip(labels, core_row):
                if val:
                    lines.append(f"{label}: {val}")

        # Top 5 NPC memories by importance
        mem_rows = db.execute(
            "SELECT content, importance, memory_type, narrative_time "
            "FROM npc_memories WHERE npc_id = ? AND session_id = ? "
            "ORDER BY importance DESC LIMIT 5",
            (character_id, session_id),
        ).fetchall()
        if mem_rows:
            lines.append("")
            lines.append("--- NPC MEMORIES ---")
            for m in mem_rows:
                lines.append(f"[{m[2]}] (importance={m[1]}) {m[0]}")
                if m[3]:
                    lines.append(f"  narrative_time: {m[3]}")

    return "\n".join(lines)


def cmd_view(db, args):
    cid, _ = parse_args(args, {}, positional="character_id")
    return view(db, int(cid))


def list_chars(db, session_id: int, char_type: str = "", region_id: int = 0) -> str:
    query = "SELECT id, name, gender, type, level, status FROM characters WHERE session_id = ?"
    params: list = [session_id]
    if char_type:
        query += " AND type = ?"
        params.append(char_type)
    if region_id:
        query += " AND region_id = ?"
        params.append(region_id)
    query += " ORDER BY id"
    cur = db.execute(query, params)
    return format_table(cur)


def cmd_list(db, args):
    _, p = parse_args(
        args,
        {
            "--session": ("session", True, ""),
            "--type": ("char_type", False, ""),
            "--region": ("region", False, ""),
        },
    )
    return list_chars(db, int(p["session"]), p["char_type"], int(p["region"]) if p["region"] else 0)


def update(
    db, character_id: int, name: str = "", level: int = 0, status: str = "", region_id: int = 0, gender: str = ""
) -> str:
    _COLUMN_MAP = {
        "name": ("name", str),
        "gender": ("gender", str),
        "level": ("level", int),
        "status": ("status", str),
        "region_id": ("region_id", int),
    }
    values = {"name": name, "gender": gender, "level": level, "status": status, "region_id": region_id}
    sets = []
    params = []
    for key, (col, typ) in _COLUMN_MAP.items():
        if values[key]:
            sets.append(f"{col} = ?")
            params.append(typ(values[key]))
    if not sets:
        raise LoreKitError("Provide name, gender, level, status, and/or region")
    params.append(character_id)
    db.execute(f"UPDATE characters SET {','.join(sets)} WHERE id = ?", params)
    db.commit()
    return f"CHARACTER_UPDATED: {character_id}"


def cmd_update(db, args):
    cid, p = parse_args(
        args,
        {
            "--name": ("name", False, ""),
            "--gender": ("gender", False, ""),
            "--level": ("level", False, ""),
            "--status": ("status", False, ""),
            "--region": ("region", False, ""),
        },
        positional="character_id",
    )
    return update(
        db,
        int(cid),
        p["name"],
        int(p["level"]) if p["level"] else 0,
        p["status"],
        int(p["region"]) if p["region"] else 0,
        p["gender"],
    )


def set_attr(db, character_id: int, category: str, key: str, value: str) -> str:
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
        (character_id, category, key, value),
    )
    db.commit()
    return f"ATTR_SET: {key} = {value}"


def cmd_set_attr(db, args):
    cid, p = parse_args(
        args,
        {
            "--category": ("category", True, ""),
            "--key": ("key", True, ""),
            "--value": ("value", True, ""),
        },
        positional="character_id",
    )
    return set_attr(db, int(cid), p["category"], p["key"], p["value"])


def get_attr(db, character_id: int, category: str = "") -> str:
    if category:
        cur = db.execute(
            "SELECT key, value FROM character_attributes WHERE character_id = ? AND category = ? ORDER BY key",
            (character_id, category),
        )
    else:
        cur = db.execute(
            "SELECT category, key, value FROM character_attributes WHERE character_id = ? ORDER BY category, key",
            (character_id,),
        )
    return format_table(cur)


def cmd_get_attr(db, args):
    cid, p = parse_args(
        args,
        {
            "--category": ("category", False, ""),
        },
        positional="character_id",
    )
    return get_attr(db, int(cid), p["category"])


def set_item(db, character_id: int, name: str, desc: str = "", qty: int = 1, equipped: int = 0) -> str:
    cur = db.execute(
        "INSERT INTO character_inventory (character_id, name, description, quantity, equipped) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(character_id, name) DO UPDATE SET "
        "description = excluded.description, quantity = excluded.quantity, equipped = excluded.equipped",
        (character_id, name, desc, qty, equipped),
    )
    db.commit()
    return f"ITEM_SET: {cur.lastrowid}"


def cmd_set_item(db, args):
    cid, p = parse_args(
        args,
        {
            "--name": ("name", True, ""),
            "--desc": ("desc", False, ""),
            "--qty": ("qty", False, "1"),
            "--equipped": ("equipped", False, "0"),
        },
        positional="character_id",
    )
    return set_item(db, int(cid), p["name"], p["desc"], int(p["qty"]), int(p["equipped"]))


def get_items(db, character_id: int) -> str:
    cur = db.execute(
        "SELECT id, name, description, quantity, equipped FROM character_inventory "
        "WHERE character_id = ? ORDER BY name",
        (character_id,),
    )
    return format_table(cur)


def cmd_get_items(db, args):
    cid, _ = parse_args(args, {}, positional="character_id")
    return get_items(db, int(cid))


def remove_item(db, item_id: int) -> str:
    db.execute("DELETE FROM character_inventory WHERE id = ?", (item_id,))
    db.commit()
    return f"ITEM_REMOVED: {item_id}"


def cmd_remove_item(db, args):
    iid, _ = parse_args(args, {}, positional="item_id")
    return remove_item(db, int(iid))


def set_ability(
    db, character_id: int, name: str, desc: str, category: str, uses: str = "at_will", cost: float = 0
) -> str:
    cur = db.execute(
        "INSERT INTO character_abilities (character_id, name, description, category, uses, cost) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(character_id, name) DO UPDATE SET "
        "description = excluded.description, category = excluded.category, uses = excluded.uses, cost = excluded.cost",
        (character_id, name, desc, category, uses, cost),
    )
    db.commit()
    return f"ABILITY_SET: {cur.lastrowid}"


def cmd_set_ability(db, args):
    cid, p = parse_args(
        args,
        {
            "--name": ("name", True, ""),
            "--desc": ("desc", True, ""),
            "--category": ("category", True, ""),
            "--uses": ("uses", False, "at_will"),
        },
        positional="character_id",
    )
    return set_ability(db, int(cid), p["name"], p["desc"], p["category"], p["uses"])


def remove_ability(db, character_id: int, name: str) -> str:
    """Remove an ability by name from a character."""
    cur = db.execute(
        "DELETE FROM character_abilities WHERE character_id = ? AND name = ?",
        (character_id, name),
    )
    db.commit()
    if cur.rowcount:
        return f"ABILITY_REMOVED: {name}"
    return f"ABILITY_NOT_FOUND: {name}"


def get_abilities(db, character_id: int) -> str:
    cur = db.execute(
        "SELECT id, name, category, uses, description FROM character_abilities "
        "WHERE character_id = ? ORDER BY category, name",
        (character_id,),
    )
    return format_table(cur)


def cmd_get_abilities(db, args):
    cid, _ = parse_args(args, {}, positional="character_id")
    return get_abilities(db, int(cid))


if __name__ == "__main__":
    main()
