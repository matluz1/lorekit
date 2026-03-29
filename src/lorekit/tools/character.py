import copy
import json
import os

from lorekit._mcp_app import mcp
from lorekit.rules import try_rules_calc
from lorekit.tools._helpers import (
    _embed_ability_metadata,
    _resolve_character,
    _resolve_system_path_for_character,
    _run_with_db,
    _sync_condition_modifiers_for,
)


def character_create(session: int, name: str, level: int, type: str = "pc", region: int = 0) -> str:
    """Create a character. Type: pc or npc. Region is optional (0 = none)."""
    from lorekit.character import create

    return _run_with_db(create, session, name, level, type, region)


@mcp.tool()
def character_view(character_id: int | str) -> str:
    """View full character sheet: identity, attributes, inventory, abilities.

    character_id: numeric ID or character name (case-insensitive).
    """
    from lorekit.character import view
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        cid = _resolve_character(db, character_id)
        return view(db, cid)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def character_list(session: int, type: str = "", region: int = 0) -> str:
    """List characters in a session. Optionally filter by type and/or region."""
    from lorekit.character import list_chars

    return _run_with_db(list_chars, session, type, region)


def character_update(character_id: int, name: str = "", level: int = 0, status: str = "", region: int = 0) -> str:
    """Update character fields. Only provided fields are changed."""
    from lorekit.character import update

    return _run_with_db(update, character_id, name, level, status, region)


def character_set_attr(character_id: int, category: str, key: str, value: str) -> str:
    """Set a character attribute. Overwrites if category+key exists."""
    from lorekit.character import set_attr

    return _run_with_db(set_attr, character_id, category, key, value)


def character_get_attr(character_id: int, category: str = "") -> str:
    """Get character attributes. Optionally filter by category."""
    from lorekit.character import get_attr

    return _run_with_db(get_attr, character_id, category)


def character_set_item(character_id: int, name: str, desc: str = "", qty: int = 1, equipped: int = 0) -> str:
    """Add an item to a character's inventory."""
    from lorekit.character import set_item

    return _run_with_db(set_item, character_id, name, desc, qty, equipped)


def character_get_items(character_id: int) -> str:
    """List all items in a character's inventory."""
    from lorekit.character import get_items

    return _run_with_db(get_items, character_id)


def character_remove_item(item_id: int) -> str:
    """Remove an item from inventory by item ID."""
    from lorekit.character import remove_item

    return _run_with_db(remove_item, item_id)


def character_set_ability(
    character_id: int, name: str, desc: str, category: str, uses: str = "at_will", cost: float = 0
) -> str:
    """Add an ability to a character. cost: point cost for budget tracking."""
    from lorekit.character import set_ability

    return _run_with_db(set_ability, character_id, name, desc, category, uses, cost)


def character_get_abilities(character_id: int) -> str:
    """List all abilities of a character."""
    from lorekit.character import get_abilities

    return _run_with_db(get_abilities, character_id)


@mcp.tool()
def character_build(
    session: int,
    name: str,
    level: int,
    type: str = "pc",
    gender: str = "",
    region: int = 0,
    prefetch: int = -1,
    attrs: str = "[]",
    items: str = "[]",
    abilities: str = "[]",
    core: str = "{}",
    aliases: str = "[]",
) -> str:
    """Create a full character in one call: identity + attributes + items + abilities.

    gender: character gender (e.g. "female", "male", etc"). Used in prompts for correct pronoun usage.
    prefetch: whether session_resume should include this character's full sheet.
      Defaults to true for PCs, false for NPCs. Set to 1 for companion NPCs
      that should always be visible on resume.
    attrs: JSON array of {"category":"stat","key":"str","value":"16"} objects.
    items: JSON array of {"name":"Sword","desc":"...","qty":1,"equipped":1} objects.
    abilities: JSON array of {"name":"Flame Burst","desc":"...","category":"spell","uses":"1/day"} objects.
      Optional fields: "cost" (point cost), "array_of" (name of primary power for alternates),
      "dynamic" (true for dynamic alternates). array_of/dynamic are embedded into the description JSON.
      "action" (dict with key + action def): auto-registers as action_override for combat.
      "uses_action" (string): maps ability to an existing system action (e.g. "setup_deception").
      "movement" (dict with mode + flags): auto-registers as movement_mode (e.g. {"mode":"teleport","skip_adjacency":true}).
    core: JSON object of NPC core identity fields (only for type=npc).
      Keys: self_concept, current_goals, emotional_state, relationships, behavioral_patterns.
    aliases: JSON array of alternative names for this character (e.g. ["Bob", "the bartender"]).
    """
    from lorekit.character import create as char_create
    from lorekit.character import set_ability, set_attr, set_item
    from lorekit.db import LoreKitError, require_db

    try:
        attrs_list = json.loads(attrs)
        items_list = json.loads(items)
        abilities_list = json.loads(abilities)
        core_dict = json.loads(core)
        aliases_list = json.loads(aliases)
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    db = require_db()
    try:
        r = char_create(db, session, name, level, type, region, gender, prefetch)
        char_id = int(r.split(": ")[1])

        attr_count = 0
        for a in attrs_list:
            set_attr(db, char_id, a["category"], a["key"], str(a["value"]))
            attr_count += 1

        item_count = 0
        for it in items_list:
            set_item(db, char_id, it["name"], it.get("desc", ""), it.get("qty", 1), it.get("equipped", 0))
            item_count += 1

        ability_count = 0
        for ab in abilities_list:
            desc = _embed_ability_metadata(ab)
            set_ability(db, char_id, ab["name"], desc, ab["category"], ab.get("uses", "at_will"), ab.get("cost", 0))

            # Auto-register action_override from ability's action field
            action_def = ab.get("action")
            if action_def:
                adef = copy.deepcopy(action_def)
                akey = adef.pop("key", ab["name"].lower().replace(" ", "_"))
                set_attr(db, char_id, "action_override", akey, json.dumps(adef))

            # Auto-register movement_mode from ability's movement field
            movement_def = ab.get("movement")
            if movement_def:
                mode = movement_def.get("mode", "special")
                set_attr(db, char_id, "movement_mode", mode, json.dumps(movement_def))

            ability_count += 1

        core_set = False
        if core_dict and type == "npc":
            from lorekit.npc.memory import set_core

            set_core(db, session, char_id, **core_dict)
            core_set = True

        # Set aliases
        alias_count = 0
        for alias in aliases_list:
            if isinstance(alias, str) and alias.strip():
                db.execute(
                    "INSERT OR IGNORE INTO character_aliases (character_id, alias) VALUES (?, ?)",
                    (char_id, alias.strip()),
                )
                alias_count += 1
        if alias_count:
            db.commit()

        summary = f"CHARACTER_BUILT: {char_id} (attrs={attr_count}, items={item_count}, abilities={ability_count}"
        if core_set:
            summary += ", core_set=True"
        if alias_count:
            summary += f", aliases={alias_count}"
        summary += ")"

        # Auto-run rules_calc if session has a rules_system configured
        rules_summary = try_rules_calc(db, char_id)
        if rules_summary:
            summary += "\n" + rules_summary

        return summary
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def ability_from_template(
    character_id: int,
    template_key: str,
    overrides: str = "{}",
) -> str:
    """Create a power/ability from a common archetype template (e.g. Blast, Force Field, Strike).

    Use this instead of manually building a power with character_sheet_update when the
    player wants a standard power archetype. The template provides sensible defaults
    (cost, action, range, duration, modifiers); overrides let you customize ranks,
    add extras/flaws, or set feeds. Available templates depend on the system pack —
    call with an invalid key to see the full list.

    overrides: JSON object of fields to override on the template defaults.
      M&M example: {"ranks": 10, "extras": ["Accurate"], "feeds": {"bonus_ranged_damage": 10}}
    """
    from lorekit.character import set_ability
    from lorekit.db import LoreKitError, require_db

    try:
        overrides_dict = json.loads(overrides)
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON overrides: {e}"

    db = require_db()
    try:
        # Find character's session and system path
        system_path, _, err = _resolve_system_path_for_character(db, character_id)
        if err:
            return err
        if not system_path:
            return "ERROR: No rules_system set for this session."

        # Load system.json templates config
        system_file = os.path.join(system_path, "system.json")
        if not os.path.isfile(system_file):
            return "ERROR: system.json not found"

        with open(system_file) as f:
            system_data = json.load(f)

        templates_cfg = system_data.get("templates")
        if not templates_cfg:
            return "ERROR: No templates configured in system pack"

        source_file = os.path.join(system_path, templates_cfg["source"])
        if not os.path.isfile(source_file):
            return f"ERROR: Templates file not found: {templates_cfg['source']}"

        with open(source_file) as f:
            templates_data = json.load(f)

        template = templates_data.get(template_key)
        if template is None:
            available = ", ".join(sorted(templates_data.keys()))
            return f"ERROR: Template '{template_key}' not found. Available: {available}"

        # Deep-merge overrides on top of template
        merged = copy.deepcopy(template)
        for key, val in overrides_dict.items():
            merged[key] = val

        ability_category = templates_cfg.get("ability_category", "ability")
        ability_name = merged.get("name", template_key)

        # Store the merged data as the ability description (JSON)
        set_ability(db, character_id, ability_name, json.dumps(merged), ability_category, "at_will")

        # Auto-register action_override from template's action field
        action_def = merged.get("action")
        if isinstance(action_def, dict):
            adef = copy.deepcopy(action_def)
            akey = adef.pop("key", ability_name.lower().replace(" ", "_"))
            from lorekit.character import set_attr

            set_attr(db, character_id, "action_override", akey, json.dumps(adef))

        # Auto-register movement_mode from template's movement field
        movement_def = merged.get("movement")
        if isinstance(movement_def, dict):
            mode = movement_def.get("mode", "special")
            from lorekit.character import set_attr

            set_attr(db, character_id, "movement_mode", mode, json.dumps(movement_def))

        # Auto-run rules_calc
        rules_summary = try_rules_calc(db, character_id)
        result = f"ABILITY_FROM_TEMPLATE: {ability_name} (template={template_key})"
        if rules_summary:
            result += "\n" + rules_summary
        return result
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def character_sheet_update(
    character_id: int | str,
    level: int = 0,
    status: str = "",
    gender: str = "",
    region: int = 0,
    prefetch: int = -1,
    attrs: str = "[]",
    items: str = "[]",
    abilities: str = "[]",
    remove_items: str = "[]",
    remove_abilities: str = "[]",
    core: str = "{}",
    aliases: str = "[]",
) -> str:
    """Batch update a character: level/status/region/gender + attributes + items + abilities + remove items/abilities.

    gender: character gender (e.g. "female", "male", etc). Used in prompts for correct pronoun usage.
    prefetch: set to 1 to include this character in session_resume, 0 to exclude. -1 leaves unchanged.
    attrs: JSON array of {"category":"stat","key":"hp","value":"25"} objects.
    items: JSON array of {"name":"Potion","desc":"...","qty":2,"equipped":0} objects.
    abilities: JSON array of {"name":"Shield","desc":"...","category":"spell","uses":"1/day"} objects.
      Optional fields: "cost" (point cost), "array_of" (name of primary power for alternates),
      "dynamic" (true for dynamic alternates). array_of/dynamic are embedded into the description JSON.
    remove_items: JSON array of item names (strings) or item IDs (integers).
    remove_abilities: JSON array of ability names (strings) to remove.
    core: JSON object of NPC core identity fields (only for NPCs).
      Keys: self_concept, current_goals, emotional_state, relationships, behavioral_patterns.
    aliases: JSON array of alternative names for this character (e.g. ["Bob", "the bartender"]).
      Replaces existing aliases entirely.
    """
    from lorekit.character import remove_ability, remove_item, set_ability, set_attr, set_item
    from lorekit.character import update as char_update
    from lorekit.db import LoreKitError, require_db

    try:
        attrs_list = json.loads(attrs)
        items_list = json.loads(items)
        abilities_list = json.loads(abilities)
        remove_list = json.loads(remove_items)
        remove_abilities_list = json.loads(remove_abilities)
        core_dict = json.loads(core)
        aliases_list = json.loads(aliases)
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        results = []

        if level or status or region or gender:
            r = char_update(db, character_id, level=level, status=status, region_id=region, gender=gender)
            results.append(r)

        if prefetch != -1:
            db.execute("UPDATE characters SET prefetch = ? WHERE id = ?", (prefetch, character_id))
            db.commit()
            results.append(f"PREFETCH: {'on' if prefetch else 'off'}")

        attr_count = 0
        for a in attrs_list:
            set_attr(db, character_id, a["category"], a["key"], str(a["value"]))
            attr_count += 1
        if attr_count:
            results.append(f"ATTRS_SET: {attr_count}")

        remove_count = 0
        for item_ref in remove_list:
            if isinstance(item_ref, int):
                remove_item(db, item_ref)
                remove_count += 1
            elif isinstance(item_ref, str):
                row = db.execute(
                    "SELECT id FROM character_inventory WHERE character_id = ? AND name = ?",
                    (character_id, item_ref),
                ).fetchone()
                if row:
                    remove_item(db, row[0])
                    remove_count += 1
        if remove_count:
            results.append(f"ITEMS_REMOVED: {remove_count}")

        remove_ab_count = 0
        for ab_name in remove_abilities_list:
            if isinstance(ab_name, str) and ab_name.strip():
                remove_ability(db, character_id, ab_name.strip())
                remove_ab_count += 1
        if remove_ab_count:
            results.append(f"ABILITIES_REMOVED: {remove_ab_count}")

        item_count = 0
        for it in items_list:
            set_item(db, character_id, it["name"], it.get("desc", ""), it.get("qty", 1), it.get("equipped", 0))
            item_count += 1
        if item_count:
            results.append(f"ITEMS_SET: {item_count}")

        ability_count = 0
        for ab in abilities_list:
            desc = _embed_ability_metadata(ab)
            set_ability(
                db, character_id, ab["name"], desc, ab["category"], ab.get("uses", "at_will"), ab.get("cost", 0)
            )

            # Auto-register action_override from ability's action field
            action_def = ab.get("action")
            if action_def:
                adef = copy.deepcopy(action_def)
                akey = adef.pop("key", ab["name"].lower().replace(" ", "_"))
                set_attr(db, character_id, "action_override", akey, json.dumps(adef))

            # Auto-register movement_mode from ability's movement field
            movement_def = ab.get("movement")
            if movement_def:
                mode = movement_def.get("mode", "special")
                set_attr(db, character_id, "movement_mode", mode, json.dumps(movement_def))

            ability_count += 1
        if ability_count:
            results.append(f"ABILITIES_SET: {ability_count}")

        if aliases_list:
            # Replace all aliases for this character
            db.execute("DELETE FROM character_aliases WHERE character_id = ?", (character_id,))
            alias_count = 0
            for alias in aliases_list:
                if isinstance(alias, str) and alias.strip():
                    db.execute(
                        "INSERT OR IGNORE INTO character_aliases (character_id, alias) VALUES (?, ?)",
                        (character_id, alias.strip()),
                    )
                    alias_count += 1
            db.commit()
            if alias_count:
                results.append(f"ALIASES_SET: {alias_count}")

        if core_dict:
            # Verify character is an NPC
            char_row = db.execute("SELECT type, session_id FROM characters WHERE id = ?", (character_id,)).fetchone()
            if char_row and char_row[0] == "npc":
                from lorekit.npc.memory import set_core

                set_core(db, char_row[1], character_id, **core_dict)
                results.append("NPC_CORE_SET")

        if not results:
            return "NO_CHANGES: no fields provided"

        # Auto-run rules_calc if anything changed and session has rules_system
        if results:
            rules_summary = try_rules_calc(db, character_id)
            if rules_summary:
                results.append(rules_summary)

        return "\n".join(results)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()
