#!/usr/bin/env python3
"""LoreKit MCP server -- long-lived process with cached embedding model."""

import os
import sys


# Allow imports from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

from mcp.server.fastmcp import FastMCP

NPC_MCP_PORT = 3847
mcp = FastMCP("lorekit", host="127.0.0.1", port=NPC_MCP_PORT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_with_db(fn, *args, **kwargs):
    """Get a DB connection, call fn(db, ...), close DB."""
    from _db import require_db, LoreKitError

    db = require_db()
    try:
        return fn(db, *args, **kwargs)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()



# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


@mcp.tool()
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
    """Update session status."""
    from session import update

    return _run_with_db(update, session_id, status)


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


@mcp.tool()
def story_set(session_id: int, size: str, premise: str) -> str:
    """Create or overwrite the story plan for a session. Size: oneshot, short, campaign."""
    from story import set_story

    return _run_with_db(set_story, session_id, size, premise)


@mcp.tool()
def story_view(session_id: int, act_id: int = 0) -> str:
    """Show the story premise and all acts. If act_id is given, show full details for that act only."""
    if act_id:
        from story import view_act
        return _run_with_db(view_act, act_id)
    from story import view
    return _run_with_db(view, session_id)


@mcp.tool()
def story_add_act(session_id: int, title: str, desc: str = "", goal: str = "", event: str = "") -> str:
    """Append an act to the story. Order is auto-assigned."""
    from story import add_act

    return _run_with_db(add_act, session_id, title, desc, goal, event)


def story_view_act(act_id: int) -> str:
    """Show full details for a single act. (Internal — use story_view with act_id instead.)"""
    from story import view_act

    return _run_with_db(view_act, act_id)


@mcp.tool()
def story_update_act(act_id: int, title: str = "", desc: str = "", goal: str = "", event: str = "", status: str = "") -> str:
    """Update one or more fields on an act."""
    from story import update_act

    return _run_with_db(update_act, act_id, title, desc, goal, event, status)


@mcp.tool()
def story_advance(session_id: int) -> str:
    """Complete the current active act and activate the next pending one."""
    from story import advance

    return _run_with_db(advance, session_id)


# ---------------------------------------------------------------------------
# character
# ---------------------------------------------------------------------------


def character_create(session: int, name: str, level: int, type: str = "pc", region: int = 0) -> str:
    """Create a character. Type: pc or npc. Region is optional (0 = none)."""
    from character import create

    return _run_with_db(create, session, name, level, type, region)


@mcp.tool()
def character_view(character_id: int) -> str:
    """View full character sheet: identity, attributes, inventory, abilities."""
    from character import view

    return _run_with_db(view, character_id)


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


def character_set_ability(character_id: int, name: str, desc: str, category: str, uses: str = "at_will") -> str:
    """Add an ability to a character."""
    from character import set_ability

    return _run_with_db(set_ability, character_id, name, desc, category, uses)


def character_get_abilities(character_id: int) -> str:
    """List all abilities of a character."""
    from character import get_abilities

    return _run_with_db(get_abilities, character_id)


# ---------------------------------------------------------------------------
# region
# ---------------------------------------------------------------------------


@mcp.tool()
def region_create(session_id: int, name: str, desc: str = "", parent_id: int = 0) -> str:
    """Create a region in a session. Set parent_id to nest under another region."""
    from region import create

    return _run_with_db(create, session_id, name, desc, parent_id)


@mcp.tool()
def region_list(session_id: int) -> str:
    """List all regions in a session."""
    from region import list_regions

    return _run_with_db(list_regions, session_id)


@mcp.tool()
def region_view(region_id: int) -> str:
    """View region details and all NPCs linked to it."""
    from region import view

    return _run_with_db(view, region_id)


@mcp.tool()
def region_update(region_id: int, name: str = "", desc: str = "", parent_id: int = 0) -> str:
    """Update region name, description, and/or parent."""
    from region import update

    return _run_with_db(update, region_id, name, desc, parent_id)


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
def turn_revert(session_id: int) -> str:
    """Revert the last saved turn. Restores all game state (characters, items,
    attributes, story, regions, metadata) and removes timeline/journal entries
    created since the previous checkpoint."""
    from checkpoint import revert_to_previous

    return _run_with_db(revert_to_previous, session_id)


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


@mcp.tool()
def time_set(session_id: int, datetime: str) -> str:
    """Set the in-game narrative time (ISO 8601, e.g. '1347-03-15T14:00')."""
    from narrative_time import set_time

    return _run_with_db(set_time, session_id, datetime)


@mcp.tool()
def time_advance(session_id: int, amount: int, unit: str) -> str:
    """Advance the in-game clock. Units: minutes, hours, days, weeks, months, years."""
    from narrative_time import advance

    return _run_with_db(advance, session_id, amount, unit)


# ---------------------------------------------------------------------------
# rolldice
# ---------------------------------------------------------------------------


@mcp.tool()
def roll_dice(expression: str) -> str:
    """Roll dice using tabletop notation. Format: [N]d<sides>[kh<keep>][+/-mod]. Separate multiple expressions with spaces."""
    from rolldice import roll_expr, format_result

    from _db import LoreKitError

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
        from timeline import search as tl_search
        from journal import search as jn_search
        from _db import require_db, LoreKitError

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


@mcp.tool()
def recall_reindex(session_id: int) -> str:
    """Rebuild vector collections from SQL data for a session."""
    from recall import reindex

    return _run_with_db(reindex, session_id)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@mcp.tool()
def export_dump(session_id: int) -> str:
    """Export all session data to .export/session_<id>.txt."""
    from export import dump

    return _run_with_db(dump, session_id)


@mcp.tool()
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
    """
    if not narration and not player_choice:
        return "ERROR: Provide at least one of narration or player_choice"

    from _db import require_db, LoreKitError
    from timeline import add as tl_add
    from session import meta_set
    from checkpoint import create_checkpoint

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

        if narration:
            r = tl_add(db, session_id, "narration", narration, summary, narrative_time)
            results.append(r)
            r = meta_set(db, session_id, "last_gm_message", narration)
            results.append(r)

        if player_choice:
            r = tl_add(db, session_id, "player_choice", player_choice, narrative_time=narrative_time)
            results.append(r)

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
    region: int = 0,
    attrs: str = "[]",
    items: str = "[]",
    abilities: str = "[]",
) -> str:
    """Create a full character in one call: identity + attributes + items + abilities.

    attrs: JSON array of {"category":"stat","key":"str","value":"16"} objects.
    items: JSON array of {"name":"Sword","desc":"...","qty":1,"equipped":1} objects.
    abilities: JSON array of {"name":"Flame Burst","desc":"...","category":"spell","uses":"1/day"} objects.
    """
    import json as _json

    from _db import require_db, LoreKitError
    from character import create as char_create, set_attr, set_item, set_ability

    try:
        attrs_list = _json.loads(attrs)
        items_list = _json.loads(items)
        abilities_list = _json.loads(abilities)
    except _json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    db = require_db()
    try:
        r = char_create(db, session, name, level, type, region)
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
            set_ability(db, char_id, ab["name"], ab["desc"], ab["category"], ab.get("uses", "at_will"))
            ability_count += 1

        return f"CHARACTER_BUILT: {char_id} (attrs={attr_count}, items={item_count}, abilities={ability_count})"
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

    from _db import require_db, LoreKitError
    from session import create as sess_create, meta_set
    from story import set_story as story_set_fn, add_act, update_act
    from region import create as region_create_fn

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

    from _db import require_db, LoreKitError, format_table
    from session import view as sess_view, meta_get
    from story import view as story_view_fn
    from character import view as char_view
    from region import list_regions as region_list_fn
    from timeline import list_entries as timeline_list_fn
    from journal import list_entries as journal_list_fn

    db = require_db()
    try:
        parts = []

        parts.append("=== SESSION ===")
        parts.append(sess_view(db, session_id))

        parts.append("\n=== METADATA ===")
        parts.append(meta_get(db, session_id))

        nt_row = db.execute(
            "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
            (session_id,),
        ).fetchone()
        if nt_row:
            parts.append(f"\n=== NARRATIVE TIME ===")
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

        return "\n".join(parts)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def character_sheet_update(
    character_id: int,
    level: int = 0,
    status: str = "",
    region: int = 0,
    attrs: str = "[]",
    items: str = "[]",
    abilities: str = "[]",
    remove_items: str = "[]",
) -> str:
    """Batch update a character: level/status/region + attributes + items + abilities + remove items.

    attrs: JSON array of {"category":"stat","key":"hp","value":"25"} objects.
    items: JSON array of {"name":"Potion","desc":"...","qty":2,"equipped":0} objects.
    abilities: JSON array of {"name":"Shield","desc":"...","category":"spell","uses":"1/day"} objects.
    remove_items: JSON array of item names (strings) or item IDs (integers).
    """
    import json as _json

    from _db import require_db, LoreKitError
    from character import update as char_update, set_attr, set_item, set_ability, remove_item

    try:
        attrs_list = _json.loads(attrs)
        items_list = _json.loads(items)
        abilities_list = _json.loads(abilities)
        remove_list = _json.loads(remove_items)
    except _json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    db = require_db()
    try:
        results = []

        if level or status or region:
            r = char_update(db, character_id, level=level, status=status, region_id=region)
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
            set_ability(db, character_id, ab["name"], ab["desc"], ab["category"], ab.get("uses", "at_will"))
            ability_count += 1
        if ability_count:
            results.append(f"ABILITIES_SET: {ability_count}")

        if not results:
            return "NO_CHANGES: no fields provided"
        return "\n".join(results)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# npc_interact
# ---------------------------------------------------------------------------


# Read-only MCP tools NPCs are allowed to use.
_NPC_ALLOWED_TOOLS = [
    "mcp__lorekit__character_view",
    "mcp__lorekit__character_list",
    "mcp__lorekit__roll_dice",
    "mcp__lorekit__timeline_list",
    "mcp__lorekit__journal_list",
    "mcp__lorekit__recall_search",
    "mcp__lorekit__region_view",
    "mcp__lorekit__time_get",
]

_DEFAULT_NPC_MODEL = "opus"


def _load_npc_guides() -> str:
    """Load SHARED_GUIDE.md + NPC_GUIDE.md from project root."""
    project_root = os.path.dirname(os.path.abspath(__file__))
    parts = []
    for fname in ("SHARED_GUIDE.md", "NPC_GUIDE.md", "NPC_TOOLS.md"):
        path = os.path.join(project_root, fname)
        try:
            with open(path, "r") as f:
                parts.append(f.read())
        except FileNotFoundError:
            pass
    return "\n\n".join(parts)


def _build_npc_prompt(db, npc_id: int, session_id: int) -> tuple[str, str, str] | None:
    """Build NPC system prompt, model, and name from DB data.

    Returns (system_prompt, model, npc_name) or None if NPC/session not found.
    """
    import sqlite3
    db.row_factory = sqlite3.Row

    npc = db.execute(
        "SELECT id, name FROM characters WHERE id = ? AND type = 'npc'", (npc_id,)
    ).fetchone()
    if not npc:
        return None

    session = db.execute(
        "SELECT setting, system_type FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not session:
        return None

    npc_name = npc["name"]
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

    # Recent timeline for context
    timeline = db.execute(
        "SELECT entry_type, content, summary FROM timeline WHERE session_id = ? ORDER BY id DESC LIMIT 10",
        (session_id,),
    ).fetchall()
    timeline_section = ""
    if timeline:
        entries = []
        for e in reversed(timeline):
            entries.append(f"- {e['summary'] or e['content'][:150]}")
        timeline_section = "Recent events:\n" + "\n".join(entries) + "\n\n"

    guides = _load_npc_guides()

    system_prompt = f"""You are {npc_name}, {personality}.

World setting: {setting}
Rule system: {system_type}

Your attributes:
{chr(10).join(identity_lines) if identity_lines else "  (none)"}

Your inventory:
{chr(10).join(inv_lines) if inv_lines else "  (none)"}

Your abilities:
{chr(10).join(ability_lines) if ability_lines else "  (none)"}

{timeline_section}{guides}"""

    return system_prompt, model, npc_name


def _npc_log(msg: str):
    """Append a line to data/npc.log."""
    from datetime import datetime
    project_root = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(project_root, "data", "npc.log")
    ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
    with open(log_path, "a") as f:
        f.write(f"{ts} {msg}\n")


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
            if (
                evt.get("type") == "content_block_start"
                and evt.get("content_block", {}).get("type") == "tool_use"
            ):
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
def npc_interact(session_id: int, npc_id: int, message: str) -> str:
    """Make an NPC speak in character. Spawns an ephemeral AI process for the NPC.

    The GM should call this whenever the player wants to talk to an NPC.
    The message param should describe the situation and what the PC said.
    Returns the NPC's in-character response.
    """
    import subprocess

    from _db import require_db

    db = require_db()
    try:
        result = _build_npc_prompt(db, npc_id, session_id)
        if not result:
            return f"ERROR: NPC #{npc_id} not found in session #{session_id}"
        system_prompt, model, npc_name = result
    finally:
        db.close()

    project_root = os.path.dirname(os.path.abspath(__file__))

    # Use shared HTTP server if running, otherwise fall back to stdio
    if _is_npc_http_server_running():
        mcp_config = os.path.join(project_root, ".npc_mcp.json")
    else:
        mcp_config = os.path.join(project_root, ".mcp.json")

    cmd = [
        "claude",
        "-p",
        "--verbose",
        "--output-format", "stream-json",
        "--no-session-persistence",
        "--permission-mode", "bypassPermissions",
        "--tools", "",
        "--disable-slash-commands",
        "--mcp-config", mcp_config,
        "--strict-mcp-config",
        "--allowed-tools", *_NPC_ALLOWED_TOOLS,
        "--model", model,
        "--system-prompt", system_prompt,
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

        response_text, tool_names = _parse_npc_stream(proc.stdout, npc_name)

        result = response_text.strip() or f"{npc_name} says nothing."
        if tool_names:
            marker = f"[NPC_TOOLS:{npc_name}:{','.join(tool_names)}]"
            result = f"{marker}\n{result}"
        return result
    except subprocess.TimeoutExpired:
        return f"ERROR: NPC response timed out"
    except FileNotFoundError:
        return "ERROR: 'claude' CLI not found. Ensure it is installed and on PATH."



# ---------------------------------------------------------------------------
# Rules engine
# ---------------------------------------------------------------------------


@mcp.tool()
def rules_calc(character_id: int, system_path: str = "") -> str:
    """Recompute all derived stats for a character using the rules engine.

    Loads the system pack, reads the character's base attributes, resolves
    the dependency graph, writes derived stats back to the sheet, and
    returns a summary of what changed.

    If system_path is empty, reads the session's 'rules_system' metadata
    and looks for the pack under systems/<rules_system>/ in the project root.
    """
    import os

    from _db import LoreKitError, require_db

    db = require_db()
    try:
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
