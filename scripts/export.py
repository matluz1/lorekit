#!/usr/bin/env python3
"""export.py -- Export session data for narrative rewriting."""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _db import require_db, error

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT_DIR = os.path.join(PROJECT_ROOT, ".export")


def usage():
    print("Usage: python scripts/export.py <action> [args]")
    print()
    print("Actions:")
    print("  dump <session_id>   export session data to .export/ directory")
    print("  clean               remove the .export/ directory")
    sys.exit(1)


def _section(title):
    return f"{'=' * 60}\n{title}\n{'=' * 60}"


def _subsection(title):
    return f"--- {title} ---"


def cmd_clean(db, args):
    if os.path.isdir(EXPORT_DIR):
        shutil.rmtree(EXPORT_DIR)
        print(f"CLEANED: {EXPORT_DIR}")
    else:
        print("Nothing to clean.")


def cmd_dump(db, args):
    if not args:
        error("session_id required")
    session_id = args[0]

    # Validate session exists
    session = db.execute(
        "SELECT id, name, setting, system_type, status, created_at, updated_at"
        " FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session is None:
        error(f"Session {session_id} not found")

    parts = []

    # -- 1. Session --
    parts.append(_section("SESSION"))
    parts.append(f"Name: {session[1]}")
    parts.append(f"Setting: {session[2]}")
    parts.append(f"System: {session[3]}")
    parts.append(f"Status: {session[4]}")
    parts.append(f"Created: {session[5]}")
    parts.append(f"Updated: {session[6]}")

    meta = db.execute(
        "SELECT key, value FROM session_meta WHERE session_id = ? ORDER BY key",
        (session_id,),
    ).fetchall()
    if meta:
        parts.append("")
        parts.append(_subsection("Metadata"))
        for row in meta:
            parts.append(f"{row[0]}: {row[1]}")

    # -- 2. Story --
    story = db.execute(
        "SELECT id, adventure_size, premise FROM stories WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if story:
        parts.append("")
        parts.append(_section("STORY"))
        parts.append(f"Size: {story[1]}")
        parts.append(f"Premise: {story[2]}")

        acts = db.execute(
            "SELECT act_order, title, description, goal, event, status"
            " FROM story_acts WHERE session_id = ? ORDER BY act_order",
            (session_id,),
        ).fetchall()
        if acts:
            parts.append("")
            for act in acts:
                parts.append(_subsection(f"Act {act[0]}: {act[1]}"))
                parts.append(f"Status: {act[5]}")
                if act[2]:
                    parts.append(f"Description: {act[2]}")
                if act[3]:
                    parts.append(f"Goal: {act[3]}")
                if act[4]:
                    parts.append(f"Event: {act[4]}")
                parts.append("")

    # -- 3. Characters --
    characters = db.execute(
        "SELECT c.id, c.name, c.type, c.level, c.status, COALESCE(r.name, '')"
        " FROM characters c LEFT JOIN regions r ON c.region_id = r.id"
        " WHERE c.session_id = ? ORDER BY c.type, c.name",
        (session_id,),
    ).fetchall()
    if characters:
        parts.append(_section("CHARACTERS"))
        for char in characters:
            char_id = char[0]
            parts.append(_subsection(f"{char[1]} ({char[2]})"))
            parts.append(f"ID: {char_id}")
            parts.append(f"Level: {char[3]}")
            parts.append(f"Status: {char[4]}")
            if char[5]:
                parts.append(f"Region: {char[5]}")

            attrs = db.execute(
                "SELECT category, key, value FROM character_attributes"
                " WHERE character_id = ? ORDER BY category, key",
                (char_id,),
            ).fetchall()
            if attrs:
                parts.append("")
                parts.append("Attributes:")
                for a in attrs:
                    parts.append(f"  [{a[0]}] {a[1]}: {a[2]}")

            items = db.execute(
                "SELECT name, description, quantity, equipped"
                " FROM character_inventory WHERE character_id = ? ORDER BY name",
                (char_id,),
            ).fetchall()
            if items:
                parts.append("")
                parts.append("Inventory:")
                for it in items:
                    eq = " (equipped)" if it[3] else ""
                    qty = f" x{it[2]}" if it[2] > 1 else ""
                    desc = f" -- {it[1]}" if it[1] else ""
                    parts.append(f"  {it[0]}{qty}{eq}{desc}")

            abilities = db.execute(
                "SELECT name, category, uses, description"
                " FROM character_abilities WHERE character_id = ? ORDER BY category, name",
                (char_id,),
            ).fetchall()
            if abilities:
                parts.append("")
                parts.append("Abilities:")
                for ab in abilities:
                    uses = f" ({ab[2]})" if ab[2] != "at_will" else ""
                    desc = f" -- {ab[3]}" if ab[3] else ""
                    parts.append(f"  [{ab[1]}] {ab[0]}{uses}{desc}")

            parts.append("")

    # -- 4. Regions --
    regions = db.execute(
        "SELECT id, name, description FROM regions"
        " WHERE session_id = ? ORDER BY name",
        (session_id,),
    ).fetchall()
    if regions:
        parts.append(_section("REGIONS"))
        for reg in regions:
            parts.append(_subsection(reg[1]))
            if reg[2]:
                parts.append(reg[2])
            npcs = db.execute(
                "SELECT name, status FROM characters"
                " WHERE region_id = ? AND type = 'npc' ORDER BY name",
                (reg[0],),
            ).fetchall()
            if npcs:
                parts.append(f"NPCs: {', '.join(n[0] + ' (' + n[1] + ')' for n in npcs)}")
            parts.append("")

    # -- 5. Timeline --
    timeline = db.execute(
        "SELECT entry_type, speaker, content, created_at FROM timeline"
        " WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    if timeline:
        parts.append(_section("TIMELINE"))
        for t in timeline:
            ts = t[3]
            if t[0] == "narration":
                parts.append(f"[{ts}] {t[2]}")
            else:
                parts.append(f"[{ts}] {t[1]}: \"{t[2]}\"")
        parts.append("")

    # -- 6. Journal --
    journal = db.execute(
        "SELECT entry_type, content, created_at FROM journal"
        " WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    if journal:
        parts.append(_section("JOURNAL"))
        for j in journal:
            parts.append(f"[{j[2]}] ({j[0]}) {j[1]}")
        parts.append("")

    output = "\n".join(parts) + "\n"

    os.makedirs(EXPORT_DIR, exist_ok=True)
    output_file = os.path.join(EXPORT_DIR, f"session_{session_id}.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"EXPORTED: {output_file}")


def main():
    argv = sys.argv[1:]
    if not argv:
        usage()

    action = argv[0]
    args = argv[1:]

    db = require_db()

    actions = {
        "dump": cmd_dump,
        "clean": cmd_clean,
    }

    fn = actions.get(action)
    if fn is None:
        error(f"Unknown action: {action}")
    fn(db, args)


if __name__ == "__main__":
    main()
