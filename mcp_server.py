#!/usr/bin/env python3
"""LoreKit MCP server -- long-lived process with cached embedding model."""

import os
import sys

# Allow imports from core/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))

from mcp.server.fastmcp import FastMCP
from rules_engine import try_rules_calc

NPC_MCP_PORT = 3847
mcp = FastMCP("lorekit", host="127.0.0.1", port=NPC_MCP_PORT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_character(db, identifier, session_id: int | None = None) -> int:
    """Resolve a character by ID or name.

    - int or numeric string → used as ID directly
    - string → case-insensitive name search, scoped to session_id if given
    - Raises LoreKitError on not found or ambiguous match
    """
    from _db import LoreKitError

    # Numeric passthrough
    if isinstance(identifier, int):
        return identifier
    if isinstance(identifier, str) and identifier.strip().isdigit():
        return int(identifier.strip())

    # Name search
    name = identifier.strip()
    if session_id is not None:
        rows = db.execute(
            "SELECT id, name FROM characters WHERE session_id = ? AND LOWER(name) = LOWER(?)",
            (session_id, name),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, name FROM characters WHERE LOWER(name) = LOWER(?)",
            (name,),
        ).fetchall()

    if len(rows) == 1:
        return rows[0][0]
    if len(rows) == 0:
        # Fallback: check aliases
        if session_id is not None:
            alias_rows = db.execute(
                "SELECT ca.character_id FROM character_aliases ca "
                "JOIN characters c ON c.id = ca.character_id "
                "WHERE c.session_id = ? AND LOWER(ca.alias) = LOWER(?)",
                (session_id, name),
            ).fetchall()
        else:
            alias_rows = db.execute(
                "SELECT character_id FROM character_aliases WHERE LOWER(alias) = LOWER(?)",
                (name,),
            ).fetchall()
        if len(alias_rows) == 1:
            return alias_rows[0][0]
        if len(alias_rows) > 1:
            raise LoreKitError(f"Ambiguous alias '{name}'")
        raise LoreKitError(f"Character '{name}' not found")
    # Ambiguous
    options = ", ".join(f"{r[1]} (id={r[0]})" for r in rows)
    raise LoreKitError(f"Ambiguous name '{name}' — matches: {options}")


def _run_with_db(fn, *args, **kwargs):
    """Get a DB connection, call fn(db, ...), close DB."""
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        return fn(db, *args, **kwargs)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


def _timeskip_hours(amount, unit):
    """Convert a time amount+unit to approximate hours."""
    multipliers = {
        "minutes": 1 / 60,
        "hours": 1,
        "days": 24,
        "weeks": 168,
        "months": 720,
        "years": 8760,
    }
    return amount * multipliers.get(unit, 0)


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


def init_db() -> str:
    """Create or verify the LoreKit database schema. Safe to re-run."""
    from _db import init_schema

    db_path = init_schema()
    return f"Database initialized at {db_path}"


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------


def session_create(name: str, setting: str, system: str) -> str:
    """Create a new adventure session. (Internal — use session_setup instead.)"""
    from session import create

    return _run_with_db(create, name, setting, system)


def session_view(session_id: int) -> str:
    """View session details. (Internal — use session_resume or session_list instead.)"""
    from session import view

    return _run_with_db(view, session_id)


@mcp.tool()
def session_list(status: str = "") -> str:
    """List sessions. Optionally filter by status (active/finished)."""
    from session import list_sessions

    return _run_with_db(list_sessions, status)


@mcp.tool()
def session_update(session_id: int, status: str) -> str:
    """Update session status. Auto-triggers NPC reflection when session is finished."""
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        from session import update

        result = update(db, session_id, status)

        if status == "finished":
            from npc_reflect import reflect_all

            ref_result = reflect_all(db, session_id, threshold=0.0, context_hint="Session ended")
            result += f"\n{ref_result}"

        return result
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def session_meta_set(session_id: int, key: str, value: str) -> str:
    """Set a session metadata key-value pair. Overwrites if key exists."""
    from session import meta_set

    return _run_with_db(meta_set, session_id, key, value)


@mcp.tool()
def session_meta_get(session_id: int, key: str = "") -> str:
    """Get session metadata. If key is empty, returns all metadata."""
    from session import meta_get

    return _run_with_db(meta_get, session_id, key)


# ---------------------------------------------------------------------------
# story
# ---------------------------------------------------------------------------


def story_set(session_id: int, size: str, premise: str) -> str:
    """Create or overwrite the story plan for a session. Size: oneshot, short, campaign."""
    from story import set_story

    return _run_with_db(set_story, session_id, size, premise)


def story_view(session_id: int, act_id: int = 0) -> str:
    """Show the story premise and all acts. If act_id is given, show full details for that act only."""
    if act_id:
        from story import view_act

        return _run_with_db(view_act, act_id)
    from story import view

    return _run_with_db(view, session_id)


def story_add_act(session_id: int, title: str, desc: str = "", goal: str = "", event: str = "") -> str:
    """Append an act to the story. Order is auto-assigned."""
    from story import add_act

    return _run_with_db(add_act, session_id, title, desc, goal, event)


def story_view_act(act_id: int) -> str:
    """Show full details for a single act. (Internal — use story_view with act_id instead.)"""
    from story import view_act

    return _run_with_db(view_act, act_id)


def story_update_act(
    act_id: int, title: str = "", desc: str = "", goal: str = "", event: str = "", status: str = ""
) -> str:
    """Update one or more fields on an act."""
    from story import update_act

    return _run_with_db(update_act, act_id, title, desc, goal, event, status)


def story_advance(session_id: int) -> str:
    """Complete the current active act and activate the next pending one."""
    from story import advance

    return _run_with_db(advance, session_id)


@mcp.tool()
def story(
    action: str,
    session_id: int = 0,
    act_id: int = 0,
    title: str = "",
    desc: str = "",
    goal: str = "",
    event: str = "",
    status: str = "",
    size: str = "",
    premise: str = "",
) -> str:
    """Manage story plan and acts.

    action: "set", "view", "add_act", "update_act", or "advance".

    set — create/overwrite story plan (requires session_id, size, premise)
    view — show story + acts (requires session_id; optional act_id for detail)
    add_act — append an act (requires session_id, title; optional desc, goal, event)
    update_act — update act fields (requires act_id; optional title, desc, goal, event, status)
    advance — complete current act, activate next (requires session_id)
    """
    if action == "set":
        return story_set(session_id, size, premise)
    elif action == "view":
        return story_view(session_id, act_id)
    elif action == "add_act":
        return story_add_act(session_id, title, desc, goal, event)
    elif action == "update_act":
        return story_update_act(act_id, title, desc, goal, event, status)
    elif action == "advance":
        return story_advance(session_id)
    else:
        return f"ERROR: Unknown action '{action}'. Use set, view, add_act, update_act, or advance."


# ---------------------------------------------------------------------------
# character
# ---------------------------------------------------------------------------


def character_create(session: int, name: str, level: int, type: str = "pc", region: int = 0) -> str:
    """Create a character. Type: pc or npc. Region is optional (0 = none)."""
    from character import create

    return _run_with_db(create, session, name, level, type, region)


@mcp.tool()
def character_view(character_id: int | str) -> str:
    """View full character sheet: identity, attributes, inventory, abilities.

    character_id: numeric ID or character name (case-insensitive).
    """
    from _db import LoreKitError, require_db
    from character import view

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
    from character import list_chars

    return _run_with_db(list_chars, session, type, region)


def character_update(character_id: int, name: str = "", level: int = 0, status: str = "", region: int = 0) -> str:
    """Update character fields. Only provided fields are changed."""
    from character import update

    return _run_with_db(update, character_id, name, level, status, region)


def character_set_attr(character_id: int, category: str, key: str, value: str) -> str:
    """Set a character attribute. Overwrites if category+key exists."""
    from character import set_attr

    return _run_with_db(set_attr, character_id, category, key, value)


def character_get_attr(character_id: int, category: str = "") -> str:
    """Get character attributes. Optionally filter by category."""
    from character import get_attr

    return _run_with_db(get_attr, character_id, category)


def character_set_item(character_id: int, name: str, desc: str = "", qty: int = 1, equipped: int = 0) -> str:
    """Add an item to a character's inventory."""
    from character import set_item

    return _run_with_db(set_item, character_id, name, desc, qty, equipped)


def character_get_items(character_id: int) -> str:
    """List all items in a character's inventory."""
    from character import get_items

    return _run_with_db(get_items, character_id)


def character_remove_item(item_id: int) -> str:
    """Remove an item from inventory by item ID."""
    from character import remove_item

    return _run_with_db(remove_item, item_id)


def character_set_ability(
    character_id: int, name: str, desc: str, category: str, uses: str = "at_will", cost: float = 0
) -> str:
    """Add an ability to a character. cost: point cost for budget tracking."""
    from character import set_ability

    return _run_with_db(set_ability, character_id, name, desc, category, uses, cost)


def character_get_abilities(character_id: int) -> str:
    """List all abilities of a character."""
    from character import get_abilities

    return _run_with_db(get_abilities, character_id)


# ---------------------------------------------------------------------------
# region
# ---------------------------------------------------------------------------


def region_create(session_id: int, name: str, desc: str = "", parent_id: int = 0) -> str:
    """Create a region in a session. Set parent_id to nest under another region."""
    from region import create

    return _run_with_db(create, session_id, name, desc, parent_id)


def region_list(session_id: int) -> str:
    """List all regions in a session."""
    from region import list_regions

    return _run_with_db(list_regions, session_id)


def region_view(region_id: int) -> str:
    """View region details and all NPCs linked to it."""
    from region import view

    return _run_with_db(view, region_id)


def region_update(region_id: int, name: str = "", desc: str = "", parent_id: int = 0) -> str:
    """Update region name, description, and/or parent."""
    from region import update

    return _run_with_db(update, region_id, name, desc, parent_id)


@mcp.tool()
def region(
    action: str,
    session_id: int = 0,
    region_id: int = 0,
    name: str = "",
    desc: str = "",
    parent_id: int = 0,
) -> str:
    """Manage regions in a session.

    action: "create", "list", "view", or "update".

    create — create a region (requires session_id, name; optional desc, parent_id)
    list — list all regions (requires session_id)
    view — view region details + linked NPCs (requires region_id)
    update — update region fields (requires region_id; optional name, desc, parent_id)
    """
    if action == "create":
        return region_create(session_id, name, desc, parent_id)
    elif action == "list":
        return region_list(session_id)
    elif action == "view":
        return region_view(region_id)
    elif action == "update":
        return region_update(region_id, name, desc, parent_id)
    else:
        return f"ERROR: Unknown action '{action}'. Use create, list, view, or update."


# ---------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------


def timeline_add(session_id: int, type: str, content: str, summary: str = "", narrative_time: str = "") -> str:
    """Add a timeline entry. Type: narration or player_choice. Stamps with current narrative clock unless overridden."""
    from timeline import add

    return _run_with_db(add, session_id, type, content, summary, narrative_time)


@mcp.tool()
def timeline_list(session_id: int, type: str = "", last: int = 0, id: str = "") -> str:
    """List timeline entries. Optionally filter by type and/or limit to last N."""
    from timeline import list_entries

    entry_id = id
    if entry_id:
        return _run_with_db(list_entries, session_id, entry_id=entry_id)
    return _run_with_db(list_entries, session_id, type, last)


def timeline_search(session_id: int, query: str) -> str:
    """Search timeline content by keyword (case-insensitive)."""
    from timeline import search

    return _run_with_db(search, session_id, query)


@mcp.tool()
def timeline_set_summary(timeline_id: int, summary: str) -> str:
    """Set the summary for an existing timeline entry. Re-indexes for semantic search."""
    from timeline import set_summary

    return _run_with_db(set_summary, timeline_id, summary)


@mcp.tool()
def turn_revert(session_id: int, steps: int = 1) -> str:
    """Revert saved turns. Restores all game state (characters, items,
    attributes, story, regions, metadata) and removes timeline/journal entries
    created since the target checkpoint.

    steps: how many checkpoints to go back (default 1). Use higher values
    to skip multiple turns at once instead of reverting one at a time.
    """
    from checkpoint import revert_to_previous

    return _run_with_db(revert_to_previous, session_id, steps)


@mcp.tool()
def turn_advance(session_id: int, steps: int = 1) -> str:
    """Redo previously reverted turns. Only works if no new action was
    taken since the revert (future checkpoints still exist).

    steps: how many checkpoints to go forward (default 1).
    """
    from checkpoint import advance_to_next

    return _run_with_db(advance_to_next, session_id, steps)


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------


@mcp.tool()
def journal_add(session_id: int, type: str, content: str, narrative_time: str = "") -> str:
    """Add a journal entry. Types: event, combat, discovery, npc, decision, note. Stamps with current narrative clock unless overridden."""
    from journal import add

    return _run_with_db(add, session_id, type, content, narrative_time)


@mcp.tool()
def journal_list(session_id: int, type: str = "", last: int = 0) -> str:
    """List journal entries. Optionally filter by type and/or limit to last N."""
    from journal import list_entries

    return _run_with_db(list_entries, session_id, type, last)


def journal_search(session_id: int, query: str) -> str:
    """Search journal content by keyword (case-insensitive)."""
    from journal import search

    return _run_with_db(search, session_id, query)


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------


@mcp.tool()
def time_get(session_id: int) -> str:
    """Get the current in-game narrative time for a session."""
    from narrative_time import get_time

    return _run_with_db(get_time, session_id)


def time_set(session_id: int, datetime: str) -> str:
    """Set the in-game narrative time (ISO 8601, e.g. '1347-03-15T14:00')."""
    from narrative_time import set_time

    return _run_with_db(set_time, session_id, datetime)


@mcp.tool()
def time_advance(session_id: int, amount: int, unit: str) -> str:
    """Advance the in-game clock. Units: minutes, hours, days, weeks, months, years.
    Auto-triggers NPC reflection on large timeskips (>= 7 days)."""
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        from narrative_time import advance

        result = advance(db, session_id, amount, unit)

        # Check for large timeskip → auto-reflect
        hours = _timeskip_hours(amount, unit)
        if hours >= 168:  # 7 days
            from npc_reflect import reflect_all

            ref_result = reflect_all(db, session_id, context_hint=f"{amount} {unit} have passed in-game")
            result += f"\n{ref_result}"

        return result
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# rolldice
# ---------------------------------------------------------------------------


@mcp.tool()
def roll_dice(expression: str) -> str:
    """Roll dice using tabletop notation. Format: [N]d<sides>[kh<keep>][+/-mod]. Separate multiple expressions with spaces."""
    from _db import LoreKitError
    from rolldice import format_result, roll_expr

    expressions = expression.split()
    results = []
    for expr in expressions:
        try:
            r = roll_expr(expr)
            results.append((expr, r))
        except LoreKitError as e:
            return f"ERROR: {e}"

    if len(results) == 1:
        return format_result(results[0][1])
    blocks = []
    for expr, r in results:
        blocks.append(f"--- {expr} ---\n{format_result(r)}")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


@mcp.tool()
def recall_search(session_id: int, query: str, source: str = "", n: int = 0, mode: str = "semantic") -> str:
    """Search timeline and journal by meaning (semantic) or exact keyword match.

    mode: "semantic" (default) finds content by meaning. "keyword" finds exact text matches (case-insensitive).
    source: "timeline", "journal", or empty for both.
    n: override result count (0 = defaults). Only applies to semantic mode.
    """
    if mode == "keyword":
        from _db import LoreKitError, require_db
        from journal import search as jn_search
        from timeline import search as tl_search

        db = require_db()
        try:
            parts = []
            if source in ("", "timeline"):
                r = tl_search(db, session_id, query)
                if source == "":
                    parts.append("--- TIMELINE ---")
                parts.append(r)
            if source in ("", "journal"):
                r = jn_search(db, session_id, query)
                if source == "":
                    parts.append("\n--- JOURNAL ---")
                parts.append(r)
            return "\n".join(parts)
        except LoreKitError as e:
            return f"ERROR: {e}"
        finally:
            db.close()

    from recall import search

    return _run_with_db(search, session_id, query, source, n)


def recall_reindex(session_id: int) -> str:
    """Rebuild vector collections from SQL data for a session."""
    from recall import reindex

    return _run_with_db(reindex, session_id)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@mcp.tool()
def export_dump(session_id: int, clean_previous: bool = False) -> str:
    """Export all session data to .export/session_<id>.txt.

    clean_previous: if true, removes the .export/ directory before exporting.
    """
    if clean_previous:
        from export import clean

        _run_with_db(clean)
    from export import dump

    return _run_with_db(dump, session_id)


def export_clean() -> str:
    """Remove the .export/ directory and all files inside it."""
    from export import clean

    return _run_with_db(clean)


# ---------------------------------------------------------------------------
# Aggregate wrapper tools
# ---------------------------------------------------------------------------


@mcp.tool()
def turn_save(
    session_id: int,
    narration: str = "",
    summary: str = "",
    player_choice: str = "",
    narrative_time: str = "",
) -> str:
    """Save a game turn: narration + player choice + last_gm_message in one call.

    At least one of narration or player_choice is required.
    If narration is provided, it is saved to the timeline and last_gm_message is updated.
    If player_choice is provided, it is saved to the timeline.
    Always include a summary when providing narration (used for semantic search).
    narrative_time: optional override for the in-game timestamp on these entries.
      If omitted, the current narrative clock is used automatically.
    Always call turn_save as your last action before the player acts.
    During combat, encounter_advance_turn reminds you when a PC turn begins.

    WARNING: After a turn_revert, do NOT call turn_save until you have advanced
    back to the desired checkpoint with turn_advance (if needed). Calling turn_save while the
    cursor is rewound will permanently delete all future checkpoints (like making
    a new git commit after checkout — the old branch is lost).
    """
    if not narration and not player_choice:
        return "ERROR: Provide at least one of narration or player_choice"

    from _db import LoreKitError, require_db
    from checkpoint import create_checkpoint
    from session import meta_set
    from timeline import add as tl_add

    db = require_db()
    try:
        # On first turn, create checkpoint #0 (pre-game state) so we can revert it
        has_cp = db.execute(
            "SELECT 1 FROM checkpoints WHERE session_id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        if not has_cp:
            create_checkpoint(db, session_id)

        results = []
        saved_entries = []  # (source, source_id, text) for entity auto-tagging

        if narration:
            r = tl_add(db, session_id, "narration", narration, summary, narrative_time)
            results.append(r)
            # Extract timeline ID for auto-tagging
            try:
                tl_id = int(r.split(": ")[1])
                saved_entries.append(("timeline", tl_id, narration))
            except (IndexError, ValueError):
                pass
            r = meta_set(db, session_id, "last_gm_message", narration)
            results.append(r)

        if player_choice:
            r = tl_add(db, session_id, "player_choice", player_choice, narrative_time=narrative_time)
            results.append(r)
            try:
                tl_id = int(r.split(": ")[1])
                saved_entries.append(("timeline", tl_id, player_choice))
            except (IndexError, ValueError):
                pass

        # Auto-tag entities in saved entries
        try:
            from prefetch import extract_entities

            for source, source_id, text in saved_entries:
                entities = extract_entities(db, session_id, text)
                for _name, entity_type, entity_id in entities["matched_names"]:
                    db.execute(
                        "INSERT OR IGNORE INTO entry_entities (source, source_id, entity_type, entity_id) "
                        "VALUES (?, ?, ?, ?)",
                        (source, source_id, entity_type, entity_id),
                    )
            db.commit()
        except Exception:
            pass  # tagging is best-effort

        # Checkpoint after writing (the "approved" state after this turn)
        create_checkpoint(db, session_id)

        return "\n".join(results)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def character_build(
    session: int,
    name: str,
    level: int,
    type: str = "pc",
    gender: str = "",
    region: int = 0,
    attrs: str = "[]",
    items: str = "[]",
    abilities: str = "[]",
    core: str = "{}",
    aliases: str = "[]",
) -> str:
    """Create a full character in one call: identity + attributes + items + abilities.

    gender: character gender (e.g. "female", "male", etc"). Used in prompts for correct pronoun usage.
    attrs: JSON array of {"category":"stat","key":"str","value":"16"} objects.
    items: JSON array of {"name":"Sword","desc":"...","qty":1,"equipped":1} objects.
    abilities: JSON array of {"name":"Flame Burst","desc":"...","category":"spell","uses":"1/day"} objects.
    core: JSON object of NPC core identity fields (only for type=npc).
      Keys: self_concept, current_goals, emotional_state, relationships, behavioral_patterns.
    aliases: JSON array of alternative names for this character (e.g. ["Bob", "the bartender"]).
    """
    import json as _json

    from _db import LoreKitError, require_db
    from character import create as char_create
    from character import set_ability, set_attr, set_item

    try:
        attrs_list = _json.loads(attrs)
        items_list = _json.loads(items)
        abilities_list = _json.loads(abilities)
        core_dict = _json.loads(core)
        aliases_list = _json.loads(aliases)
    except _json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    db = require_db()
    try:
        r = char_create(db, session, name, level, type, region, gender)
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
            set_ability(
                db, char_id, ab["name"], ab["desc"], ab["category"], ab.get("uses", "at_will"), ab.get("cost", 0)
            )
            ability_count += 1

        core_set = False
        if core_dict and type == "npc":
            from npc_memory import set_core

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
    import copy
    import json as _json
    import os

    from _db import LoreKitError, require_db
    from character import set_ability

    try:
        overrides_dict = _json.loads(overrides)
    except _json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON overrides: {e}"

    db = require_db()
    try:
        # Find character's session and system path
        row = db.execute(
            "SELECT session_id FROM characters WHERE id = ?",
            (character_id,),
        ).fetchone()
        if row is None:
            return f"ERROR: Character {character_id} not found"

        system_path = _resolve_system_path_for_session(db, row[0])
        if not system_path:
            return "ERROR: No rules_system set for this session."

        # Load system.json templates config
        system_file = os.path.join(system_path, "system.json")
        if not os.path.isfile(system_file):
            return "ERROR: system.json not found"

        with open(system_file) as f:
            system_data = _json.load(f)

        templates_cfg = system_data.get("templates")
        if not templates_cfg:
            return "ERROR: No templates configured in system pack"

        source_file = os.path.join(system_path, templates_cfg["source"])
        if not os.path.isfile(source_file):
            return f"ERROR: Templates file not found: {templates_cfg['source']}"

        with open(source_file) as f:
            templates_data = _json.load(f)

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
        set_ability(db, character_id, ability_name, _json.dumps(merged), ability_category, "at_will")

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
def session_setup(
    name: str,
    setting: str,
    system: str,
    meta: str = "{}",
    story_size: str = "",
    story_premise: str = "",
    acts: str = "[]",
    regions: str = "[]",
    narrative_time: str = "",
) -> str:
    """Set up an entire session in one call: session + metadata + story + acts + regions + narrative time.

    meta: JSON object of key-value pairs, e.g. {"language":"English","house_rules":"..."}.
    acts: JSON array of {"title":"...","desc":"...","goal":"...","event":"..."} objects.
    regions: JSON array of {"name":"...","desc":"...","children":[{"name":"...","desc":"..."}]} objects.
    narrative_time: initial in-game time as ISO 8601, e.g. "1347-03-15T14:00".
    The first act is automatically set to "active".
    """
    import json as _json

    from _db import LoreKitError, require_db
    from region import create as region_create_fn
    from session import create as sess_create
    from session import meta_set
    from story import add_act, update_act
    from story import set_story as story_set_fn

    try:
        meta_dict = _json.loads(meta)
        acts_list = _json.loads(acts)
        regions_list = _json.loads(regions)
    except _json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    db = require_db()
    try:
        r = sess_create(db, name, setting, system)
        sid = int(r.split(": ")[1])
        parts = [r]

        meta_count = 0
        for k, v in meta_dict.items():
            meta_set(db, sid, k, str(v))
            meta_count += 1
        if meta_count:
            parts.append(f"META_SET: {meta_count} keys")

        if narrative_time:
            meta_set(db, sid, "narrative_time", narrative_time)
            parts.append(f"TIME_SET: {narrative_time}")

        if story_size and story_premise:
            r = story_set_fn(db, sid, story_size, story_premise)
            parts.append(r)

        first_act_id = None
        act_count = 0
        for act in acts_list:
            r = add_act(db, sid, act["title"], act.get("desc", ""), act.get("goal", ""), act.get("event", ""))
            if first_act_id is None:
                first_act_id = int(r.split(": ")[1])
            act_count += 1

        if first_act_id is not None:
            update_act(db, first_act_id, status="active")
            parts.append(f"ACTS_ADDED: {act_count} (first act set to active)")

        region_count = 0

        def _create_regions(region_list, parent_id=0):
            nonlocal region_count
            for reg in region_list:
                r = region_create_fn(db, sid, reg["name"], reg.get("desc", ""), parent_id)
                rid = int(r.split(": ")[1])
                region_count += 1
                if reg.get("children"):
                    _create_regions(reg["children"], parent_id=rid)

        _create_regions(regions_list)
        if region_count:
            parts.append(f"REGIONS_CREATED: {region_count}")

        return "\n".join(parts)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def session_resume(session_id: int) -> str:
    """Assemble full context for resuming a session in one call.

    Returns: session details, narrative time, last_gm_message, active story act,
    all PCs with full sheets, all regions, last 20 timeline entries, and last 5
    journal notes.
    """
    import sqlite3

    from _db import LoreKitError, format_table, require_db
    from character import view as char_view
    from journal import list_entries as journal_list_fn
    from region import list_regions as region_list_fn
    from session import meta_get
    from session import view as sess_view
    from story import view as story_view_fn
    from timeline import list_entries as timeline_list_fn

    db = require_db()
    try:
        parts = []

        # Active encounter first (so it appears in truncated previews)
        enc_row = db.execute(
            "SELECT id FROM encounter_state WHERE session_id = ? AND status = 'active'",
            (session_id,),
        ).fetchone()
        if enc_row:
            from encounter import get_status

            combat_cfg = _load_combat_cfg(db, session_id)
            parts.append("=== ACTIVE ENCOUNTER ===")
            parts.append(get_status(db, session_id, combat_cfg=combat_cfg))
            parts.append("")

        parts.append("=== SESSION ===")
        parts.append(sess_view(db, session_id))

        parts.append("\n=== METADATA ===")
        parts.append(meta_get(db, session_id))

        nt_row = db.execute(
            "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
            (session_id,),
        ).fetchone()
        if nt_row:
            parts.append("\n=== NARRATIVE TIME ===")
            parts.append(f"CURRENT: {nt_row[0]}")

        parts.append("\n=== STORY ===")
        try:
            parts.append(story_view_fn(db, session_id))

            db.row_factory = sqlite3.Row
            active_act = db.execute(
                "SELECT id, act_order, title, description, goal, event "
                "FROM story_acts WHERE session_id = ? AND status = 'active' LIMIT 1",
                (session_id,),
            ).fetchone()
            db.row_factory = None
            if active_act:
                parts.append(f"\nACTIVE ACT: #{active_act['act_order']} — {active_act['title']}")
                if active_act["description"]:
                    parts.append(f"DESCRIPTION: {active_act['description']}")
                if active_act["goal"]:
                    parts.append(f"GOAL: {active_act['goal']}")
                if active_act["event"]:
                    parts.append(f"EVENT: {active_act['event']}")
        except LoreKitError:
            parts.append("(no story set)")

        parts.append("\n=== PLAYER CHARACTERS ===")
        db.row_factory = sqlite3.Row
        pcs = db.execute(
            "SELECT id FROM characters WHERE session_id = ? AND type = 'pc' ORDER BY id",
            (session_id,),
        ).fetchall()
        db.row_factory = None
        if pcs:
            for pc in pcs:
                parts.append(char_view(db, pc["id"]))
                parts.append("")
        else:
            parts.append("(no PCs)")

        parts.append("=== REGIONS ===")
        parts.append(region_list_fn(db, session_id))

        parts.append("\n=== RECENT TIMELINE (last 20) ===")
        parts.append(timeline_list_fn(db, session_id, last=20))

        parts.append("\n=== RECENT JOURNAL (last 5) ===")
        parts.append(journal_list_fn(db, session_id, last=5))

        # Auto-reindex vector collections on resume
        try:
            from recall import reindex

            reindex(db, session_id)
        except Exception:
            pass

        return "\n".join(parts)
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
    attrs: str = "[]",
    items: str = "[]",
    abilities: str = "[]",
    remove_items: str = "[]",
    core: str = "{}",
    aliases: str = "[]",
) -> str:
    """Batch update a character: level/status/region/gender + attributes + items + abilities + remove items.

    gender: character gender (e.g. "female", "male", etc). Used in prompts for correct pronoun usage.
    attrs: JSON array of {"category":"stat","key":"hp","value":"25"} objects.
    items: JSON array of {"name":"Potion","desc":"...","qty":2,"equipped":0} objects.
    abilities: JSON array of {"name":"Shield","desc":"...","category":"spell","uses":"1/day"} objects.
    remove_items: JSON array of item names (strings) or item IDs (integers).
    core: JSON object of NPC core identity fields (only for NPCs).
      Keys: self_concept, current_goals, emotional_state, relationships, behavioral_patterns.
    aliases: JSON array of alternative names for this character (e.g. ["Bob", "the bartender"]).
      Replaces existing aliases entirely.
    """
    import json as _json

    from _db import LoreKitError, require_db
    from character import remove_item, set_ability, set_attr, set_item
    from character import update as char_update

    try:
        attrs_list = _json.loads(attrs)
        items_list = _json.loads(items)
        abilities_list = _json.loads(abilities)
        remove_list = _json.loads(remove_items)
        core_dict = _json.loads(core)
        aliases_list = _json.loads(aliases)
    except _json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        results = []

        if level or status or region or gender:
            r = char_update(db, character_id, level=level, status=status, region_id=region, gender=gender)
            results.append(r)

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

        item_count = 0
        for it in items_list:
            set_item(db, character_id, it["name"], it.get("desc", ""), it.get("qty", 1), it.get("equipped", 0))
            item_count += 1
        if item_count:
            results.append(f"ITEMS_SET: {item_count}")

        ability_count = 0
        for ab in abilities_list:
            set_ability(
                db, character_id, ab["name"], ab["desc"], ab["category"], ab.get("uses", "at_will"), ab.get("cost", 0)
            )
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
                from npc_memory import set_core

                set_core(db, char_row[1], character_id, **core_dict)
                results.append("NPC_CORE_SET")

        if not results:
            return "NO_CHANGES: no fields provided"

        # Auto-run rules_calc if attributes changed and session has rules_system
        if attrs_list:
            rules_summary = try_rules_calc(db, character_id)
            if rules_summary:
                results.append(rules_summary)

        return "\n".join(results)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# npc_interact
# ---------------------------------------------------------------------------


# NPCs are pure narrative agents — no tools. Context is pre-loaded by prefetch.
_NPC_ALLOWED_TOOLS: list[str] = []

_MCP_PREFIX = "mcp__lorekit__"
_NPC_ALLOWED_SET = set(_NPC_ALLOWED_TOOLS)


def _get_npc_disallowed_tools() -> list[str]:
    """All tools are disallowed for NPCs — context is pre-fetched."""
    return [f"{_MCP_PREFIX}{name}" for name in mcp._tool_manager._tools]


_DEFAULT_NPC_MODEL = "opus"


def _load_npc_guides() -> str:
    """Load SHARED_GUIDE.md + NPC_GUIDE.md from guidelines/."""
    project_root = os.path.dirname(os.path.abspath(__file__))
    guidelines_dir = os.path.join(project_root, "guidelines")
    parts = []
    for fname in ("SHARED_GUIDE.md", "NPC_GUIDE.md", "NPC_TOOLS.md"):
        path = os.path.join(guidelines_dir, fname)
        try:
            with open(path, "r") as f:
                parts.append(f.read())
        except FileNotFoundError:
            pass
    return "\n\n".join(parts)


def _build_npc_prompt(db, npc_id: int, session_id: int, gm_message: str = "") -> tuple[str, str, str] | None:
    """Build NPC system prompt with pre-fetched context.

    Returns (system_prompt, model, npc_name) or None if NPC/session not found.
    """
    import sqlite3

    from prefetch import assemble_context

    db.row_factory = sqlite3.Row

    npc = db.execute("SELECT id, name, gender FROM characters WHERE id = ? AND type = 'npc'", (npc_id,)).fetchone()
    if not npc:
        return None

    session = db.execute("SELECT setting, system_type FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        return None

    npc_name = npc["name"]
    npc_gender = npc["gender"]
    setting = session["setting"]
    system_type = session["system_type"]

    # Attributes
    attrs = db.execute(
        "SELECT category, key, value FROM character_attributes WHERE character_id = ?",
        (npc_id,),
    ).fetchall()

    personality = "a common NPC"
    model = _DEFAULT_NPC_MODEL
    identity_lines = []
    for a in attrs:
        if a["category"] == "identity" and a["key"] == "personality":
            personality = a["value"]
        elif a["category"] == "system" and a["key"] == "model":
            model = a["value"]
        if a["category"] != "system":
            identity_lines.append(f"  {a['key']}: {a['value']}")

    # Inventory
    items = db.execute(
        "SELECT name, quantity, equipped FROM character_inventory WHERE character_id = ?",
        (npc_id,),
    ).fetchall()
    inv_lines = []
    for item in items:
        line = f"  {item['name']}"
        if item["quantity"] > 1:
            line += f" x{item['quantity']}"
        if item["equipped"]:
            line += " (equipped)"
        inv_lines.append(line)

    # Abilities
    abilities = db.execute(
        "SELECT name, uses, description FROM character_abilities WHERE character_id = ?",
        (npc_id,),
    ).fetchall()
    ability_lines = [f"  {ab['name']} ({ab['uses']}): {ab['description']}" for ab in abilities]

    # Combat modifiers (active conditions/buffs)
    combat_lines = []
    combat_rows = db.execute(
        "SELECT source, target_stat, modifier_type, value, bonus_type, duration_type, duration "
        "FROM combat_state WHERE character_id = ?",
        (npc_id,),
    ).fetchall()
    for cr in combat_rows:
        line = f"  {cr['source']}: {cr['modifier_type']} {cr['value']:+d} to {cr['target_stat']}"
        if cr["bonus_type"]:
            line += f" ({cr['bonus_type']})"
        if cr["duration_type"] == "rounds" and cr["duration"]:
            line += f" [{cr['duration']}r left]"
        combat_lines.append(line)

    # Get narrative time
    meta_row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
        (session_id,),
    ).fetchone()
    narrative_time = meta_row["value"] if meta_row else ""

    # Pre-fetch: core identity + memories + timeline
    prefetch_result = assemble_context(
        db,
        session_id,
        npc_id,
        gm_message,
        narrative_time=narrative_time,
    )

    _npc_log(f"[PREFETCH] {npc_name}: {prefetch_result.debug}")

    guides = _load_npc_guides()

    gender_line = f"\nGender: {npc_gender}" if npc_gender else ""

    system_prompt = f"""You are {npc_name}, {personality}.{gender_line}

World setting: {setting}
Rule system: {system_type}

Your attributes:
{chr(10).join(identity_lines) if identity_lines else "  (none)"}

Your inventory:
{chr(10).join(inv_lines) if inv_lines else "  (none)"}

Your abilities:
{chr(10).join(ability_lines) if ability_lines else "  (none)"}

{"Active conditions:" + chr(10) + chr(10).join(combat_lines) + chr(10) if combat_lines else ""}{prefetch_result.context}

{guides}"""

    return system_prompt, model, npc_name


def _npc_log(msg: str):
    """Append a line to data/npc.log."""
    from datetime import datetime

    project_root = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(project_root, "data", "lorekit.log")
    ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
    with open(log_path, "a") as f:
        f.write(f"{ts} NPC {msg}\n")


def _parse_npc_stream(stdout: str, npc_name: str = "NPC") -> tuple[str, list[str]]:
    """Parse stream-json output from the NPC process.

    Returns (response_text, list_of_tool_names_used).
    """
    import json

    _npc_log(f"[START] ─── {npc_name} ───")

    text_parts: list[str] = []
    tool_names: list[str] = []
    args_buffer = ""
    think_buffer = ""

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        if msg.get("type") == "assistant":
            # CLI outputs assistant messages with content arrays
            for block in msg.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    if name:
                        tool_names.append(name)
                        args = block.get("input", {})
                        _npc_log(f"[TOOL] {name}")
                        _npc_log(f"[ARGS] {json.dumps(args, ensure_ascii=False)}")
                elif block.get("type") == "thinking":
                    _npc_log(f"[THINK] {block.get('thinking', '')}")
                elif block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                    _npc_log(f"[TEXT] {block.get('text', '')}")
        elif msg.get("type") == "stream_event":
            evt = msg.get("event", {})
            if evt.get("type") == "content_block_start" and evt.get("content_block", {}).get("type") == "tool_use":
                name = evt["content_block"].get("name", "")
                if name:
                    tool_names.append(name)
                    _npc_log(f"[TOOL] {name}")
                    args_buffer = ""
            elif evt.get("type") == "content_block_delta":
                delta = evt.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_parts.append(delta.get("text", ""))
                elif delta.get("type") == "thinking_delta":
                    think_buffer += delta.get("thinking", "")
                elif delta.get("type") == "input_json_delta":
                    args_buffer += delta.get("partial_json", "")
            elif evt.get("type") == "content_block_stop":
                if think_buffer:
                    _npc_log(f"[THINK] {think_buffer}")
                    think_buffer = ""
                if args_buffer:
                    _npc_log(f"[ARGS] {args_buffer}")
                    args_buffer = ""
        elif msg.get("type") == "result":
            # Fallback: grab result text if we missed deltas
            if not text_parts and msg.get("result"):
                text_parts.append(msg["result"])

    _npc_log(f"[END] ─── {npc_name} ───")
    return "".join(text_parts), tool_names


def _is_npc_http_server_running() -> bool:
    """Check if the shared MCP HTTP server is listening."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", NPC_MCP_PORT), timeout=0.3):
            return True
    except (ConnectionRefusedError, OSError):
        return False


@mcp.tool()
def npc_interact(session_id: int, npc_id: int | str, message: str) -> str:
    """Make an NPC speak in character. Spawns an ephemeral AI process for the NPC.

    The GM should call this whenever the player wants to talk to an NPC.
    The message param should describe the situation and what the PC said.
    Returns the NPC's in-character response.

    npc_id: numeric ID or NPC name (case-insensitive).
    """
    import subprocess

    from _db import require_db

    db = require_db()
    try:
        npc_id = _resolve_character(db, npc_id, session_id)
        result = _build_npc_prompt(db, npc_id, session_id, gm_message=message)
        if not result:
            return f"ERROR: NPC #{npc_id} not found in session #{session_id}"
        system_prompt, model, npc_name = result
    finally:
        db.close()

    project_root = os.path.dirname(os.path.abspath(__file__))

    # NPC is a pure narrative agent — no MCP tools needed
    cmd = [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--no-session-persistence",
        "--permission-mode",
        "bypassPermissions",
        "--tools",
        "",
        "--disable-slash-commands",
        "--model",
        model,
        "--system-prompt",
        system_prompt,
    ]
    cmd.append(message)
    _npc_log(f"[USER] → {npc_name}: {message[:500]}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            return f"ERROR: NPC process failed: {stderr or 'unknown error'}"

        response_text, _tool_names = _parse_npc_stream(proc.stdout, npc_name)

        # Post-process: extract memories/state from NPC response
        from core.npc_postprocess import process_npc_response

        db2 = require_db()
        try:
            # Get narrative time from session meta
            meta_row = db2.execute(
                "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
                (session_id,),
            ).fetchone()
            narrative_time = meta_row[0] if meta_row else ""

            clean_text = process_npc_response(db2, session_id, npc_id, response_text, npc_name, narrative_time)
        except Exception:
            clean_text = response_text  # fallback: return raw text
        finally:
            db2.close()

        return clean_text.strip() or f"{npc_name} says nothing."
    except subprocess.TimeoutExpired:
        return "ERROR: NPC response timed out"
    except FileNotFoundError:
        return "ERROR: 'claude' CLI not found. Ensure it is installed and on PATH."


@mcp.tool()
def npc_memory_add(
    session_id: int,
    npc_id: int | str,
    content: str,
    importance: float = 0.5,
    memory_type: str = "experience",
    entities: str = "[]",
    narrative_time: str = "",
) -> str:
    """Add a memory to an NPC. Memories persist and influence future NPC behavior.

    memory_type: experience, observation, relationship, or reflection.
    importance: 0.0 to 1.0 (higher = more likely to be recalled).
    entities: JSON array of entity names referenced in this memory.
    narrative_time: in-game timestamp for the memory.
    """
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        resolved_npc_id = _resolve_character(db, npc_id, session_id)

        # Verify it's an NPC
        row = db.execute("SELECT type FROM characters WHERE id = ?", (resolved_npc_id,)).fetchone()
        if not row or row[0] != "npc":
            return f"ERROR: Character {resolved_npc_id} is not an NPC"

        from npc_memory import add_memory

        memory_id = add_memory(
            db, session_id, resolved_npc_id, content, importance, memory_type, entities, narrative_time
        )
        return f"NPC_MEMORY_ADDED: {memory_id}"
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def npc_reflect(session_id: int, npc_id: int | str) -> str:
    """Trigger reflection for a single NPC. Generates insights from accumulated memories."""
    from _db import require_db

    db = require_db()
    try:
        npc_id = _resolve_character(db, npc_id, session_id)
        # Verify it's an NPC
        char = db.execute("SELECT type FROM characters WHERE id = ?", (npc_id,)).fetchone()
        if not char or char[0] != "npc":
            return f"ERROR: Character #{npc_id} is not an NPC"
        from npc_reflect import generate_reflection

        result = generate_reflection(db, session_id, npc_id)
        return f"NPC_REFLECTED: {result['npc_name']} — {result['reflections_stored']} reflections, {result['rules_added']} behavioral rules"
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def entry_untag(source: str, source_id: int, entity_type: str, entity_id: int) -> str:
    """Remove an entity tag from a timeline or journal entry.

    Use this to correct auto-tagging errors (e.g. a character was falsely
    matched in text).

    source: 'timeline' or 'journal'.
    entity_type: 'character' or 'region'.
    """
    from _db import require_db

    if source not in ("timeline", "journal"):
        return "ERROR: source must be 'timeline' or 'journal'"
    if entity_type not in ("character", "region"):
        return "ERROR: entity_type must be 'character' or 'region'"

    db = require_db()
    try:
        cur = db.execute(
            "DELETE FROM entry_entities WHERE source = ? AND source_id = ? AND entity_type = ? AND entity_id = ?",
            (source, source_id, entity_type, entity_id),
        )
        db.commit()
        if cur.rowcount == 0:
            return "NO_CHANGE: tag not found"
        return "ENTRY_UNTAGGED"
    finally:
        db.close()


@mcp.tool()
def npc_combat_turn(session_id: int, npc_id: int | str) -> str:
    """Execute a full NPC combat turn: decision + movement + action + advance.

    Asks the NPC agent what to do (with combat context: positions, relative
    health, available actions), then executes the intent mechanically:
    move (if chosen) → resolve action (if chosen) → advance turn.

    The NPC returns structured intent (action, target, movement, narration).
    Narrative-only turns (null intent) still tick modifiers and advance
    initiative.

    npc_id: numeric ID or NPC name (case-insensitive).
    """
    import subprocess

    from _db import LoreKitError, require_db

    db = require_db()
    try:
        npc_id = _resolve_character(db, npc_id, session_id)

        # Load combat config and system path
        combat_cfg = _load_combat_cfg(db, session_id)
        system_path = _resolve_system_path_for_session(db, session_id)
        if not system_path:
            return "ERROR: No rules_system set for this session."

        from npc_combat import build_combat_context

        combat_context = build_combat_context(db, npc_id, session_id, combat_cfg)

        # Build NPC prompt with combat context as invocation message
        result = _build_npc_prompt(db, npc_id, session_id, gm_message=combat_context)
        if not result:
            return f"ERROR: NPC #{npc_id} not found in session #{session_id}"
        system_prompt, model, npc_name = result
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()

    # Call NPC subprocess for combat decision — no MCP tools
    project_root = os.path.dirname(os.path.abspath(__file__))

    cmd = [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--no-session-persistence",
        "--permission-mode",
        "bypassPermissions",
        "--tools",
        "",
        "--disable-slash-commands",
        "--model",
        model,
        "--system-prompt",
        system_prompt,
        combat_context,
    ]

    _npc_log(f"[COMBAT] → {npc_name}: combat turn")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            return f"ERROR: NPC process failed: {stderr or 'unknown error'}"

        response_text, _ = _parse_npc_stream(proc.stdout, npc_name)
    except subprocess.TimeoutExpired:
        return "ERROR: NPC response timed out"
    except FileNotFoundError:
        return "ERROR: 'claude' CLI not found."

    # Parse structured intent from NPC response
    from npc_combat import execute_combat_turn, parse_combat_intent
    from system_pack import load_system_pack

    db3 = require_db()
    try:
        pack = load_system_pack(system_path)
        intent_schema = pack.intent or None
    finally:
        db3.close()

    intent = parse_combat_intent(response_text, schema=intent_schema)

    import json

    _npc_log(f"[COMBAT] ← {npc_name}: {json.dumps(intent, default=str)}")

    # Build output
    lines = [f"NPC TURN: {npc_name}"]

    if intent.get("narration"):
        lines.append(f'DECISION: "{intent["narration"]}"')

    if not intent["action"] and not intent["move_to"]:
        lines.append("ACTION: None (narrative only)")

    # Execute mechanical part
    db2 = require_db()
    try:
        mech_lines = execute_combat_turn(
            db2,
            session_id,
            npc_id,
            intent,
            combat_cfg,
            system_path,
        )
        lines.extend(mech_lines)
    except LoreKitError as e:
        lines.append(f"ERROR: {e}")
    finally:
        db2.close()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------


@mcp.tool()
def system_info(system: str = "", session_id: int = 0, section: str = "all") -> str:
    """Show what a system pack provides: actions, attributes, derived stats, build options.

    Use this to discover action names, attribute names, and formulas before
    calling rules_calc, rules_resolve, or character_build.

    system: system pack name (e.g. "mm3e", "pf2e").
    session_id: alternatively, resolve the system from a session's rules_system metadata.
    section: "actions", "defaults", "derived", "build", "constraints", "resolution", "combat", or "all".
    """
    import os

    from _db import LoreKitError, require_db

    if not system and session_id <= 0:
        return "ERROR: Provide either system (pack name) or session_id."

    try:
        if system:
            project_root = os.path.dirname(os.path.abspath(__file__))
            pack_dir = os.path.join(project_root, "systems", system)
        else:
            db = require_db()
            try:
                pack_dir = _resolve_system_path_for_session(db, session_id)
                if not pack_dir:
                    return "ERROR: No rules_system set for this session."
            finally:
                db.close()

        from system_pack import system_info as _system_info

        return _system_info(pack_dir, section)
    except (LoreKitError, FileNotFoundError) as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Rules engine
# ---------------------------------------------------------------------------


@mcp.tool()
def rules_check(character_id: int | str, check: str, dc: int, system_path: str = "") -> str:
    """Roll a derived stat against a DC. Reads pre-computed values (run rules_calc first).

    Returns the roll result with success/failure and margin.

    character_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata
    and looks for the pack under systems/<rules_system>/ in the project root.
    """
    import os

    from _db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if not system_path:
            row = db.execute(
                "SELECT session_id FROM characters WHERE id = ?",
                (character_id,),
            ).fetchone()
            if row is None:
                return f"ERROR: Character {character_id} not found"
            session_id = row[0]
            meta_row = db.execute(
                "SELECT value FROM session_meta WHERE session_id = ? AND key = 'rules_system'",
                (session_id,),
            ).fetchone()
            if meta_row is None:
                return "ERROR: No rules_system set for this session. Use session_meta_set to configure it."
            system_name = meta_row[0]
            project_root = os.path.dirname(os.path.abspath(__file__))
            system_path = os.path.join(project_root, "systems", system_name)

        from rules_engine import rules_check as _rules_check

        return _rules_check(db, character_id, check, dc, system_path)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def rules_resolve(
    attacker_id: int | str, defender_id: int | str, action: str, options: str = "{}", system_path: str = ""
) -> str:
    """Resolve a combat action between two characters.

    Rolls attack vs defense, then applies damage/effects per the system's
    resolution rules (threshold for PF2e, degree for M&M3e).

    Both characters must have derived stats computed (run rules_calc first).

    attacker_id/defender_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata
    and looks for the pack under systems/<rules_system>/ in the project root.
    """
    import json
    import os

    from _db import LoreKitError, require_db

    db = require_db()
    try:
        attacker_id = _resolve_character(db, attacker_id)
        defender_id = _resolve_character(db, defender_id)
        if not system_path:
            row = db.execute(
                "SELECT session_id FROM characters WHERE id = ?",
                (attacker_id,),
            ).fetchone()
            if row is None:
                return f"ERROR: Character {attacker_id} not found"
            session_id = row[0]
            meta_row = db.execute(
                "SELECT value FROM session_meta WHERE session_id = ? AND key = 'rules_system'",
                (session_id,),
            ).fetchone()
            if meta_row is None:
                return "ERROR: No rules_system set for this session. Use session_meta_set to configure it."
            system_name = meta_row[0]
            project_root = os.path.dirname(os.path.abspath(__file__))
            system_path = os.path.join(project_root, "systems", system_name)

        opts = json.loads(options) if options else {}

        # Area effect: options contains "area" dict
        area = opts.pop("area", None)
        if area:
            from combat_engine import resolve_area_action

            radius = area.get("radius", 0)
            center = area.get("center", "target")
            exclude_self = area.get("exclude_self", True)

            # Resolve center zone name
            if center == "target":
                if defender_id <= 0:
                    return "ERROR: area.center is 'target' but no defender_id provided"
                # Look up defender's zone name
                from encounter import (
                    _get_active_encounter,
                    _get_character_zone,
                    _zone_id_to_name,
                )

                enc = _get_active_encounter(db, session_id)
                if enc is None:
                    return "ERROR: No active encounter — area effects require an encounter"
                def_zid = _get_character_zone(db, enc[0], defender_id)
                if def_zid is None:
                    return f"ERROR: Defender {defender_id} is not placed in the encounter"
                center_zone = _zone_id_to_name(db, def_zid)
            elif center == "self":
                center_zone = "self"
            else:
                center_zone = center

            return resolve_area_action(
                db,
                attacker_id,
                action,
                system_path,
                center_zone,
                radius,
                exclude_self,
                opts,
            )

        from combat_engine import resolve_action

        return resolve_action(db, attacker_id, defender_id, action, system_path, opts)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


def rules_calc(character_id: int | str, system_path: str = "") -> str:
    """Recompute all derived stats for a character using the rules engine.

    Loads the system pack, reads the character's base attributes, resolves
    the dependency graph, writes derived stats back to the sheet, and
    returns a summary of what changed.

    character_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata
    and looks for the pack under systems/<rules_system>/ in the project root.
    """
    import os

    from _db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if not system_path:
            # Look up character's session, then session's rules_system meta
            row = db.execute(
                "SELECT session_id FROM characters WHERE id = ?",
                (character_id,),
            ).fetchone()
            if row is None:
                return f"ERROR: Character {character_id} not found"
            session_id = row[0]
            meta_row = db.execute(
                "SELECT value FROM session_meta WHERE session_id = ? AND key = 'rules_system'",
                (session_id,),
            ).fetchone()
            if meta_row is None:
                return "ERROR: No rules_system set for this session. Use session_meta_set to configure it."
            system_name = meta_row[0]
            project_root = os.path.dirname(os.path.abspath(__file__))
            system_path = os.path.join(project_root, "systems", system_name)

        from rules_engine import rules_calc as _rules_calc

        return _rules_calc(db, character_id, system_path)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


def end_turn(character_id: int | str, system_path: str = "") -> str:
    """Tick durations on a character's combat modifiers at end of turn.

    Processes each modifier according to the system pack's end_turn config:
    - rounds: decrement duration, remove when expired
    - save_ends (D&D): roll a save, remove on success

    Automatically recomputes derived stats when modifiers expire.

    character_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata.
    """
    import os

    from _db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if not system_path:
            row = db.execute(
                "SELECT session_id FROM characters WHERE id = ?",
                (character_id,),
            ).fetchone()
            if row is None:
                return f"ERROR: Character {character_id} not found"
            session_id = row[0]
            meta_row = db.execute(
                "SELECT value FROM session_meta WHERE session_id = ? AND key = 'rules_system'",
                (session_id,),
            ).fetchone()
            if meta_row is None:
                return "ERROR: No rules_system set for this session. Use session_meta_set to configure it."
            system_name = meta_row[0]
            project_root = os.path.dirname(os.path.abspath(__file__))
            system_path = os.path.join(project_root, "systems", system_name)

        from combat_engine import end_turn as _end_turn

        return _end_turn(db, character_id, system_path)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def combat_modifier(
    character_id: int | str,
    action: str,
    source: str = "",
    target_stat: str = "",
    value: int = 0,
    modifier_type: str = "buff",
    bonus_type: str = "",
    duration_type: str = "encounter",
    duration: int = 0,
    save_stat: str = "",
    save_dc: int = 0,
) -> str:
    """Manage transient combat modifiers on a character.

    character_id: numeric ID or character name (case-insensitive).
    action: "add", "list", "remove", or "clear".

    add — apply a transient modifier (pre-combat buffs, environmental effects,
    GM fiat). Requires source, target_stat, value, duration_type.
    Optional save_stat/save_dc for save-ends duration types.
    list — show all active modifiers on the character.
    remove — remove a modifier by source name.
    clear — remove all encounter/rounds/concentration modifiers (end of combat).
    """
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if action == "add":
            if not source or not target_stat:
                return "ERROR: 'add' requires source and target_stat"
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "bonus_type, duration_type, duration, save_stat, save_dc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET "
                "value = excluded.value, bonus_type = excluded.bonus_type, "
                "duration_type = excluded.duration_type, duration = excluded.duration, "
                "save_stat = excluded.save_stat, save_dc = excluded.save_dc",
                (
                    character_id,
                    source,
                    target_stat,
                    modifier_type,
                    value,
                    bonus_type or None,
                    duration_type,
                    duration or None,
                    save_stat or None,
                    save_dc or None,
                ),
            )
            db.commit()
            type_tag = f" [{bonus_type}]" if bonus_type else ""
            result = (
                f"MODIFIER ADDED: {source} → {target_stat} {value:+d}{type_tag} "
                f"({duration_type}{f', {duration} rounds' if duration else ''})"
            )
            recalc = try_rules_calc(db, character_id)
            if recalc:
                result += "\n" + recalc
            return result

        elif action == "list":
            rows = db.execute(
                "SELECT source, target_stat, value, bonus_type, modifier_type, "
                "duration_type, duration FROM combat_state "
                "WHERE character_id = ? ORDER BY created_at",
                (character_id,),
            ).fetchall()
            if not rows:
                return f"No active modifiers on character {character_id}"
            lines = [f"MODIFIERS: character {character_id}"]
            for src, stat, val, btype, mtype, dtype, dur in rows:
                type_tag = f" [{btype}]" if btype else ""
                dur_info = f" ({dur} rounds)" if dur else ""
                lines.append(f"  {src}: {stat} {val:+d}{type_tag} ({dtype}{dur_info})")
            return "\n".join(lines)

        elif action == "remove":
            if not source:
                return "ERROR: 'remove' requires source"
            deleted = db.execute(
                "DELETE FROM combat_state WHERE character_id = ? AND source = ?",
                (character_id, source),
            ).rowcount
            db.commit()
            result = f"REMOVED: {deleted} modifier(s) from source '{source}'"
            if deleted:
                recalc = try_rules_calc(db, character_id)
                if recalc:
                    result += "\n" + recalc
            return result

        elif action == "clear":
            deleted = db.execute(
                "DELETE FROM combat_state WHERE character_id = ? "
                "AND duration_type IN ('encounter', 'rounds', 'concentration')",
                (character_id,),
            ).rowcount
            db.commit()
            result = f"CLEARED: {deleted} transient modifier(s) from character {character_id}"
            if deleted:
                recalc = try_rules_calc(db, character_id)
                if recalc:
                    result += "\n" + recalc
            return result

        else:
            return f"ERROR: Unknown action '{action}'. Use add, list, remove, or clear."

    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


def rules_modifiers(character_id: int | str, stat: str = "", system_path: str = "") -> str:
    """Show modifier decomposition for a character's stats.

    Displays all active modifiers with their types, sources, and which
    ones survived stacking. If stat is specified, shows only that stat;
    otherwise shows all stats with active modifiers.

    character_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata.
    """
    import os

    from _db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if not system_path:
            row = db.execute(
                "SELECT session_id FROM characters WHERE id = ?",
                (character_id,),
            ).fetchone()
            if row is None:
                return f"ERROR: Character {character_id} not found"
            session_id = row[0]
            meta_row = db.execute(
                "SELECT value FROM session_meta WHERE session_id = ? AND key = 'rules_system'",
                (session_id,),
            ).fetchone()
            if meta_row is None:
                return "ERROR: No rules_system set for this session."
            system_name = meta_row[0]
            project_root = os.path.dirname(os.path.abspath(__file__))
            system_path = os.path.join(project_root, "systems", system_name)

        from rules_engine import (
            CharacterData,
            _load_combat_modifiers,
            load_character_data,
            load_system_pack,
        )
        from rules_stacking import (
            ModifierEntry,
            decompose_modifiers,
            load_stacking_policy,
        )

        pack = load_system_pack(system_path)
        char = load_character_data(db, character_id)
        policy = load_stacking_policy(pack.stacking)

        # Collect modifiers from character attributes
        all_mods: list[ModifierEntry] = []
        for cat, attrs in char.attributes.items():
            for key, val in attrs.items():
                if key.startswith("bonus_"):
                    try:
                        num_val = float(val) if "." in val else int(val)
                    except (ValueError, TypeError):
                        continue
                    if num_val != 0:
                        all_mods.append(ModifierEntry(key, num_val, source=cat))

        # Add combat_state modifiers
        all_mods.extend(_load_combat_modifiers(db, character_id))

        if not all_mods:
            return f"No active modifiers on {char.name}"

        decomposed = decompose_modifiers(all_mods, policy, stat=stat or None)

        if not decomposed:
            return f"No modifiers found for stat '{stat}' on {char.name}"

        lines = [f"MODIFIERS: {char.name}" + (f" — {stat}" if stat else "")]
        for d in decomposed:
            status = "" if d.active else " (suppressed)"
            type_tag = f" [{d.bonus_type}]" if d.bonus_type else ""
            lines.append(f"  {d.source}: {d.target_stat} {d.value:+g}{type_tag}{status}")
        return "\n".join(lines)

    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Rest
# ---------------------------------------------------------------------------


@mcp.tool()
def rest(session_id: int, type: str) -> str:
    """Apply rest rules to all PCs in the session.

    type: rest type from system pack (e.g. "short", "long").
    Restores stats via formulas, resets ability uses, clears combat
    modifiers, and optionally advances time. All rules come from
    the system pack's "rest" section.
    """
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        system_path = _resolve_system_path_for_session(db, session_id)
        if not system_path:
            return "ERROR: No rules_system set for this session."

        from rest import rest as _rest

        return _rest(db, session_id, type, system_path)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Encounter (combat positioning)
# ---------------------------------------------------------------------------


def _resolve_system_path_for_session(db, session_id: int) -> str:
    """Resolve system pack path from session metadata."""
    import os

    meta_row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'rules_system'",
        (session_id,),
    ).fetchone()
    if meta_row is None:
        return ""
    system_name = meta_row[0]
    project_root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(project_root, "systems", system_name)


def _load_combat_cfg(db, session_id: int) -> dict:
    """Load the combat config from the session's system pack."""
    system_path = _resolve_system_path_for_session(db, session_id)
    if not system_path:
        return {}
    from system_pack import load_system_pack

    try:
        pack = load_system_pack(system_path)
        return pack.combat
    except Exception:
        return {}


@mcp.tool()
def encounter_start(
    session_id: int,
    zones: str = "[]",
    initiative: str = "auto",
    adjacency: str = "",
    placements: str = "",
    template: str = "",
) -> str:
    """Start a combat encounter with zone-based positioning.

    Creates zones, sets initiative order, optionally places characters.
    Adjacency defaults to a linear chain if not specified.

    template: encounter template name from system pack (e.g. "tavern_brawl").
      Loads pre-built zones and adjacency. zones/adjacency params override
      template values if both are provided.
    zones: JSON array — [{"name": "Entrance", "tags": ["cover"]}, ...]
      Can be empty "[]" when using a template.
    initiative: "auto" or JSON array — [{"character_id": 5, "roll": 22}, ...]
      When "auto", rolls d20 + initiative_stat (from system pack) for each
      placed character. Requires placements.
    adjacency: JSON array (optional) — [{"from": "A", "to": "B", "weight": 1}, ...]
    placements: JSON array (optional) — [{"character_id": 5, "zone": "Entrance"}, ...]
    """
    import json

    from _db import LoreKitError, require_db

    db = require_db()
    try:
        zones_list = json.loads(zones) if zones else None
        if not zones_list:
            zones_list = None
        init_value = initiative.strip()
        if init_value == '"auto"' or init_value == "auto":
            init_list = "auto"
        else:
            init_list = json.loads(initiative)
        adj_list = json.loads(adjacency) if adjacency else None
        place_list = json.loads(placements) if placements else None

        combat_cfg = _load_combat_cfg(db, session_id)
        system_path = _resolve_system_path_for_session(db, session_id)

        from encounter import start_encounter

        return start_encounter(
            db,
            session_id,
            zones_list,
            init_list,
            adjacency=adj_list,
            placements=place_list,
            combat_cfg=combat_cfg,
            template=template,
            pack_dir=system_path,
        )
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_status(session_id: int) -> str:
    """Return the current encounter state: round, turn, positions, distances.

    Shows initiative order, zone positions with terrain tags, and pairwise
    distances between all characters.
    """
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        combat_cfg = _load_combat_cfg(db, session_id)

        from encounter import get_status

        return get_status(db, session_id, combat_cfg=combat_cfg)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_move(character_id: int | str, target_zone: str) -> str:
    """Move a character to a different zone during an encounter.

    Validates movement cost against the character's movement budget
    (derived stat 'movement_zones' or system default). Applies/removes
    terrain modifiers automatically.

    character_id: numeric ID or character name (case-insensitive).
    """
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        # Find the character's session and active encounter
        row = db.execute(
            "SELECT session_id FROM characters WHERE id = ?",
            (character_id,),
        ).fetchone()
        if row is None:
            return f"ERROR: Character {character_id} not found"
        session_id = row[0]

        from encounter import _require_active_encounter

        enc_id, _, _, _ = _require_active_encounter(db, session_id)
        combat_cfg = _load_combat_cfg(db, session_id)

        # Try to get movement budget from derived stats
        movement_budget = None
        mv_row = db.execute(
            "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'movement_zones'",
            (character_id,),
        ).fetchone()
        if mv_row is not None:
            try:
                movement_budget = int(mv_row[0])
            except (ValueError, TypeError):
                pass

        from encounter import move_character

        return move_character(
            db,
            enc_id,
            character_id,
            target_zone,
            combat_cfg=combat_cfg,
            movement_budget=movement_budget,
        )
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_advance_turn(session_id: int) -> str:
    """Advance to the next character in initiative order.

    Increments the round counter when wrapping past the last character.
    Returns the new active character with position summary.
    When a PC turn begins, reminds you to call turn_save with narration.
    """
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        combat_cfg = _load_combat_cfg(db, session_id)

        from encounter import advance_turn

        return advance_turn(db, session_id, combat_cfg=combat_cfg)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_end(session_id: int) -> str:
    """End the active encounter with combat summary.

    Removes all zones, character positions, terrain modifiers, and
    encounter-duration combat modifiers. Generates a combat summary
    (participants, defeated, vital stats) and auto-saves to journal.
    """
    from _db import LoreKitError, require_db

    db = require_db()
    try:
        combat_cfg = _load_combat_cfg(db, session_id)
        from encounter import end_encounter

        return end_encounter(db, session_id, combat_cfg=combat_cfg)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_zone_update(session_id: int, zone_name: str, tags: str) -> str:
    """Modify zone tags mid-combat (fire spreads, wall collapses, Darkness cast).

    Updates the zone's tags and applies/removes terrain modifiers for all
    characters currently in the zone.

    tags: JSON array — ["difficult_terrain", "cover"]
    """
    import json

    from _db import LoreKitError, require_db

    db = require_db()
    try:
        from encounter import _require_active_encounter, update_zone_tags

        enc_id, _, _, _ = _require_active_encounter(db, session_id)
        combat_cfg = _load_combat_cfg(db, session_id)
        tags_list = json.loads(tags)

        return update_zone_tags(db, enc_id, zone_name, tags_list, combat_cfg=combat_cfg)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Eagerly load the embedding model so the first vector operation
    # doesn't pay a cold-start penalty.
    from _vectordb import _get_model

    _get_model()

    if "--http" in sys.argv:
        # HTTP transport for NPC subprocess connections (shared server)
        mcp.run(transport="streamable-http")
    else:
        # Default: stdio transport for GM's Claude session
        mcp.run()
