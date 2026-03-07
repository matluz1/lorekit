#!/usr/bin/env python3
"""LoreKit MCP server -- long-lived process with cached embedding model."""

import os
import sys

# Silence ChromaDB telemetry notice
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

# Allow imports from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

from mcp.server.fastmcp import FastMCP

NPC_MCP_PORT = 3847
mcp = FastMCP("lorekit", host="127.0.0.1", port=NPC_MCP_PORT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_with_db(fn, args_list):
    """Get a DB connection, call fn(db, args_list), close DB."""
    from _db import require_db, LoreKitError

    db = require_db()
    try:
        return fn(db, args_list)
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


@mcp.tool()
def session_create(name: str, setting: str, system: str) -> str:
    """Create a new adventure session."""
    from session import cmd_create

    return _run_with_db(cmd_create, ["--name", name, "--setting", setting, "--system", system])


@mcp.tool()
def session_view(session_id: int) -> str:
    """View session details."""
    from session import cmd_view

    return _run_with_db(cmd_view, [str(session_id)])


@mcp.tool()
def session_list(status: str = "") -> str:
    """List sessions. Optionally filter by status (active/finished)."""
    from session import cmd_list

    args = []
    if status:
        args += ["--status", status]
    return _run_with_db(cmd_list, args)


@mcp.tool()
def session_update(session_id: int, status: str) -> str:
    """Update session status."""
    from session import cmd_update

    return _run_with_db(cmd_update, [str(session_id), "--status", status])


@mcp.tool()
def session_meta_set(session_id: int, key: str, value: str) -> str:
    """Set a session metadata key-value pair. Overwrites if key exists."""
    from session import cmd_meta_set

    return _run_with_db(cmd_meta_set, [str(session_id), "--key", key, "--value", value])


@mcp.tool()
def session_meta_get(session_id: int, key: str = "") -> str:
    """Get session metadata. If key is empty, returns all metadata."""
    from session import cmd_meta_get

    args = [str(session_id)]
    if key:
        args += ["--key", key]
    return _run_with_db(cmd_meta_get, args)


# ---------------------------------------------------------------------------
# story
# ---------------------------------------------------------------------------


@mcp.tool()
def story_set(session_id: int, size: str, premise: str) -> str:
    """Create or overwrite the story plan for a session. Size: oneshot, short, campaign."""
    from story import cmd_set

    return _run_with_db(cmd_set, [str(session_id), "--size", size, "--premise", premise])


@mcp.tool()
def story_view(session_id: int) -> str:
    """Show the story premise and all acts for a session."""
    from story import cmd_view

    return _run_with_db(cmd_view, [str(session_id)])


@mcp.tool()
def story_add_act(session_id: int, title: str, desc: str = "", goal: str = "", event: str = "") -> str:
    """Append an act to the story. Order is auto-assigned."""
    from story import cmd_add_act

    args = [str(session_id), "--title", title]
    if desc:
        args += ["--desc", desc]
    if goal:
        args += ["--goal", goal]
    if event:
        args += ["--event", event]
    return _run_with_db(cmd_add_act, args)


@mcp.tool()
def story_view_act(act_id: int) -> str:
    """Show full details for a single act."""
    from story import cmd_view_act

    return _run_with_db(cmd_view_act, [str(act_id)])


@mcp.tool()
def story_update_act(act_id: int, title: str = "", desc: str = "", goal: str = "", event: str = "", status: str = "") -> str:
    """Update one or more fields on an act."""
    from story import cmd_update_act

    args = [str(act_id)]
    if title:
        args += ["--title", title]
    if desc:
        args += ["--desc", desc]
    if goal:
        args += ["--goal", goal]
    if event:
        args += ["--event", event]
    if status:
        args += ["--status", status]
    return _run_with_db(cmd_update_act, args)


@mcp.tool()
def story_advance(session_id: int) -> str:
    """Complete the current active act and activate the next pending one."""
    from story import cmd_advance

    return _run_with_db(cmd_advance, [str(session_id)])


# ---------------------------------------------------------------------------
# character
# ---------------------------------------------------------------------------


@mcp.tool()
def character_create(session: int, name: str, level: int, type: str = "pc", region: int = 0) -> str:
    """Create a character. Type: pc or npc. Region is optional (0 = none)."""
    from character import cmd_create

    args = ["--session", str(session), "--name", name, "--level", str(level), "--type", type]
    if region:
        args += ["--region", str(region)]
    return _run_with_db(cmd_create, args)


@mcp.tool()
def character_view(character_id: int) -> str:
    """View full character sheet: identity, attributes, inventory, abilities."""
    from character import cmd_view

    return _run_with_db(cmd_view, [str(character_id)])


@mcp.tool()
def character_list(session: int, type: str = "", region: int = 0) -> str:
    """List characters in a session. Optionally filter by type and/or region."""
    from character import cmd_list

    args = ["--session", str(session)]
    if type:
        args += ["--type", type]
    if region:
        args += ["--region", str(region)]
    return _run_with_db(cmd_list, args)


@mcp.tool()
def character_update(character_id: int, name: str = "", level: int = 0, status: str = "", region: int = 0) -> str:
    """Update character fields. Only provided fields are changed."""
    from character import cmd_update

    args = [str(character_id)]
    if name:
        args += ["--name", name]
    if level:
        args += ["--level", str(level)]
    if status:
        args += ["--status", status]
    if region:
        args += ["--region", str(region)]
    return _run_with_db(cmd_update, args)


@mcp.tool()
def character_set_attr(character_id: int, category: str, key: str, value: str) -> str:
    """Set a character attribute. Overwrites if category+key exists."""
    from character import cmd_set_attr

    return _run_with_db(cmd_set_attr, [str(character_id), "--category", category, "--key", key, "--value", value])


@mcp.tool()
def character_get_attr(character_id: int, category: str = "") -> str:
    """Get character attributes. Optionally filter by category."""
    from character import cmd_get_attr

    args = [str(character_id)]
    if category:
        args += ["--category", category]
    return _run_with_db(cmd_get_attr, args)


@mcp.tool()
def character_set_item(character_id: int, name: str, desc: str = "", qty: int = 1, equipped: int = 0) -> str:
    """Add an item to a character's inventory."""
    from character import cmd_set_item

    args = [str(character_id), "--name", name]
    if desc:
        args += ["--desc", desc]
    if qty != 1:
        args += ["--qty", str(qty)]
    if equipped:
        args += ["--equipped", str(equipped)]
    return _run_with_db(cmd_set_item, args)


@mcp.tool()
def character_get_items(character_id: int) -> str:
    """List all items in a character's inventory."""
    from character import cmd_get_items

    return _run_with_db(cmd_get_items, [str(character_id)])


@mcp.tool()
def character_remove_item(item_id: int) -> str:
    """Remove an item from inventory by item ID."""
    from character import cmd_remove_item

    return _run_with_db(cmd_remove_item, [str(item_id)])


@mcp.tool()
def character_set_ability(character_id: int, name: str, desc: str, category: str, uses: str = "at_will") -> str:
    """Add an ability to a character."""
    from character import cmd_set_ability

    return _run_with_db(cmd_set_ability, [str(character_id), "--name", name, "--desc", desc, "--category", category, "--uses", uses])


@mcp.tool()
def character_get_abilities(character_id: int) -> str:
    """List all abilities of a character."""
    from character import cmd_get_abilities

    return _run_with_db(cmd_get_abilities, [str(character_id)])


# ---------------------------------------------------------------------------
# region
# ---------------------------------------------------------------------------


@mcp.tool()
def region_create(session_id: int, name: str, desc: str = "", parent_id: int = 0) -> str:
    """Create a region in a session. Set parent_id to nest under another region."""
    from region import cmd_create

    args = [str(session_id), "--name", name]
    if desc:
        args += ["--desc", desc]
    if parent_id:
        args += ["--parent", str(parent_id)]
    return _run_with_db(cmd_create, args)


@mcp.tool()
def region_list(session_id: int) -> str:
    """List all regions in a session."""
    from region import cmd_list

    return _run_with_db(cmd_list, [str(session_id)])


@mcp.tool()
def region_view(region_id: int) -> str:
    """View region details and all NPCs linked to it."""
    from region import cmd_view

    return _run_with_db(cmd_view, [str(region_id)])


@mcp.tool()
def region_update(region_id: int, name: str = "", desc: str = "", parent_id: int = 0) -> str:
    """Update region name, description, and/or parent."""
    from region import cmd_update

    args = [str(region_id)]
    if name:
        args += ["--name", name]
    if desc:
        args += ["--desc", desc]
    if parent_id:
        args += ["--parent", str(parent_id)]
    return _run_with_db(cmd_update, args)


# ---------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------


@mcp.tool()
def timeline_add(session_id: int, type: str, content: str, summary: str = "", narrative_time: str = "") -> str:
    """Add a timeline entry. Type: narration or player_choice. Stamps with current narrative clock unless overridden."""
    from timeline import cmd_add

    args = [str(session_id), "--type", type, "--content", content]
    if summary:
        args += ["--summary", summary]
    if narrative_time:
        args += ["--time", narrative_time]
    return _run_with_db(cmd_add, args)


@mcp.tool()
def timeline_list(session_id: int, type: str = "", last: int = 0, id: str = "") -> str:
    """List timeline entries. Optionally filter by type and/or limit to last N."""
    from timeline import cmd_list

    args = [str(session_id)]
    if id:
        args += ["--id", id]
    elif type:
        args += ["--type", type]
    if not id and last:
        args += ["--last", str(last)]
    return _run_with_db(cmd_list, args)


@mcp.tool()
def timeline_search(session_id: int, query: str) -> str:
    """Search timeline content by keyword (case-insensitive)."""
    from timeline import cmd_search

    return _run_with_db(cmd_search, [str(session_id), "--query", query])


@mcp.tool()
def timeline_set_summary(timeline_id: int, summary: str) -> str:
    """Set the summary for an existing timeline entry. Re-indexes for semantic search."""
    from timeline import cmd_set_summary

    return _run_with_db(cmd_set_summary, [str(timeline_id), "--summary", summary])


@mcp.tool()
def timeline_revert(session_id: int) -> str:
    """Revert the last narration and all entries after it. Cleans up the vector index and restores last_gm_message."""
    from timeline import cmd_revert

    return _run_with_db(cmd_revert, [str(session_id)])


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------


@mcp.tool()
def journal_add(session_id: int, type: str, content: str, narrative_time: str = "") -> str:
    """Add a journal entry. Types: event, combat, discovery, npc, decision, note. Stamps with current narrative clock unless overridden."""
    from journal import cmd_add

    args = [str(session_id), "--type", type, "--content", content]
    if narrative_time:
        args += ["--time", narrative_time]
    return _run_with_db(cmd_add, args)


@mcp.tool()
def journal_list(session_id: int, type: str = "", last: int = 0) -> str:
    """List journal entries. Optionally filter by type and/or limit to last N."""
    from journal import cmd_list

    args = [str(session_id)]
    if type:
        args += ["--type", type]
    if last:
        args += ["--last", str(last)]
    return _run_with_db(cmd_list, args)


@mcp.tool()
def journal_search(session_id: int, query: str) -> str:
    """Search journal content by keyword (case-insensitive)."""
    from journal import cmd_search

    return _run_with_db(cmd_search, [str(session_id), "--query", query])


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------


@mcp.tool()
def time_get(session_id: int) -> str:
    """Get the current in-game narrative time for a session."""
    from narrative_time import cmd_get

    return _run_with_db(cmd_get, [str(session_id)])


@mcp.tool()
def time_set(session_id: int, datetime: str) -> str:
    """Set the in-game narrative time (ISO 8601, e.g. '1347-03-15T14:00')."""
    from narrative_time import cmd_set

    return _run_with_db(cmd_set, [str(session_id), "--datetime", datetime])


@mcp.tool()
def time_advance(session_id: int, amount: int, unit: str) -> str:
    """Advance the in-game clock. Units: minutes, hours, days, weeks, months, years."""
    from narrative_time import cmd_advance

    return _run_with_db(cmd_advance, [str(session_id), "--amount", str(amount), "--unit", unit])


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
def recall_search(session_id: int, query: str, source: str = "", n: int = 0) -> str:
    """Semantic search across timeline and journal. Source: timeline, journal, or empty for both."""
    from recall import cmd_search

    args = [str(session_id), "--query", query]
    if source:
        args += ["--source", source]
    if n > 0:
        args += ["--n", str(n)]
    return _run_with_db(cmd_search, args)


@mcp.tool()
def recall_reindex(session_id: int) -> str:
    """Rebuild vector collections from SQL data for a session."""
    from recall import cmd_reindex

    return _run_with_db(cmd_reindex, [str(session_id)])


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@mcp.tool()
def export_dump(session_id: int) -> str:
    """Export all session data to .export/session_<id>.txt."""
    from export import cmd_dump

    return _run_with_db(cmd_dump, [str(session_id)])


@mcp.tool()
def export_clean() -> str:
    """Remove the .export/ directory and all files inside it."""
    from export import cmd_clean

    return _run_with_db(cmd_clean, [])


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
    from timeline import cmd_add
    from session import cmd_meta_set

    db = require_db()
    try:
        results = []

        if narration:
            args = [str(session_id), "--type", "narration", "--content", narration]
            if summary:
                args += ["--summary", summary]
            if narrative_time:
                args += ["--time", narrative_time]
            r = cmd_add(db, args)
            results.append(r)

            # Update last_gm_message
            r = cmd_meta_set(db, [str(session_id), "--key", "last_gm_message", "--value", narration])
            results.append(r)

        if player_choice:
            pc_args = [str(session_id), "--type", "player_choice", "--content", player_choice]
            if narrative_time:
                pc_args += ["--time", narrative_time]
            r = cmd_add(db, pc_args)
            results.append(r)

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
    from character import cmd_create, cmd_set_attr, cmd_set_item, cmd_set_ability

    try:
        attrs_list = _json.loads(attrs)
        items_list = _json.loads(items)
        abilities_list = _json.loads(abilities)
    except _json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    db = require_db()
    try:
        # Create character
        create_args = ["--session", str(session), "--name", name, "--level", str(level), "--type", type]
        if region:
            create_args += ["--region", str(region)]
        r = cmd_create(db, create_args)
        char_id = int(r.split(": ")[1])

        # Set attributes
        attr_count = 0
        for a in attrs_list:
            cmd_set_attr(db, [str(char_id), "--category", a["category"], "--key", a["key"], "--value", str(a["value"])])
            attr_count += 1

        # Set items
        item_count = 0
        for it in items_list:
            args = [str(char_id), "--name", it["name"]]
            if it.get("desc"):
                args += ["--desc", it["desc"]]
            if it.get("qty") and it["qty"] != 1:
                args += ["--qty", str(it["qty"])]
            if it.get("equipped"):
                args += ["--equipped", str(it["equipped"])]
            cmd_set_item(db, args)
            item_count += 1

        # Set abilities
        ability_count = 0
        for ab in abilities_list:
            args = [str(char_id), "--name", ab["name"], "--desc", ab["desc"], "--category", ab["category"]]
            if ab.get("uses"):
                args += ["--uses", ab["uses"]]
            cmd_set_ability(db, args)
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
    from session import cmd_create as sess_create, cmd_meta_set
    from story import cmd_set as story_set_fn, cmd_add_act, cmd_update_act
    from region import cmd_create as region_create_fn

    try:
        meta_dict = _json.loads(meta)
        acts_list = _json.loads(acts)
        regions_list = _json.loads(regions)
    except _json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON: {e}"

    db = require_db()
    try:
        # Create session
        r = sess_create(db, ["--name", name, "--setting", setting, "--system", system])
        sid = int(r.split(": ")[1])
        parts = [r]

        # Set metadata
        meta_count = 0
        for k, v in meta_dict.items():
            cmd_meta_set(db, [str(sid), "--key", k, "--value", str(v)])
            meta_count += 1
        if meta_count:
            parts.append(f"META_SET: {meta_count} keys")

        # Set narrative time
        if narrative_time:
            cmd_meta_set(db, [str(sid), "--key", "narrative_time", "--value", narrative_time])
            parts.append(f"TIME_SET: {narrative_time}")

        # Create story
        if story_size and story_premise:
            r = story_set_fn(db, [str(sid), "--size", story_size, "--premise", story_premise])
            parts.append(r)

        # Create acts
        first_act_id = None
        act_count = 0
        for act in acts_list:
            args = [str(sid), "--title", act["title"]]
            if act.get("desc"):
                args += ["--desc", act["desc"]]
            if act.get("goal"):
                args += ["--goal", act["goal"]]
            if act.get("event"):
                args += ["--event", act["event"]]
            r = cmd_add_act(db, args)
            if first_act_id is None:
                first_act_id = int(r.split(": ")[1])
            act_count += 1

        if first_act_id is not None:
            cmd_update_act(db, [str(first_act_id), "--status", "active"])
            parts.append(f"ACTS_ADDED: {act_count} (first act set to active)")

        # Create regions (with children)
        region_count = 0

        def _create_regions(region_list, parent_id=None):
            nonlocal region_count
            for reg in region_list:
                args = [str(sid), "--name", reg["name"]]
                if reg.get("desc"):
                    args += ["--desc", reg["desc"]]
                if parent_id:
                    args += ["--parent", str(parent_id)]
                r = region_create_fn(db, args)
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
    from session import cmd_view as sess_view, cmd_meta_get
    from story import cmd_view as story_view_fn
    from character import cmd_view as char_view, cmd_list as char_list
    from region import cmd_list as region_list_fn
    from timeline import cmd_list as timeline_list_fn
    from journal import cmd_list as journal_list_fn

    db = require_db()
    try:
        parts = []

        # Session details
        parts.append("=== SESSION ===")
        parts.append(sess_view(db, [str(session_id)]))

        # All metadata
        parts.append("\n=== METADATA ===")
        parts.append(cmd_meta_get(db, [str(session_id)]))

        # Narrative time
        nt_row = db.execute(
            "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
            (session_id,),
        ).fetchone()
        if nt_row:
            parts.append(f"\n=== NARRATIVE TIME ===")
            parts.append(f"CURRENT: {nt_row[0]}")

        # Story + acts
        parts.append("\n=== STORY ===")
        try:
            parts.append(story_view_fn(db, [str(session_id)]))

            # Show active act details
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

        # All PCs with full sheets
        parts.append("\n=== PLAYER CHARACTERS ===")
        db.row_factory = sqlite3.Row
        pcs = db.execute(
            "SELECT id FROM characters WHERE session_id = ? AND type = 'pc' ORDER BY id",
            (session_id,),
        ).fetchall()
        db.row_factory = None
        if pcs:
            for pc in pcs:
                parts.append(char_view(db, [str(pc["id"])]))
                parts.append("")
        else:
            parts.append("(no PCs)")

        # Regions
        parts.append("=== REGIONS ===")
        parts.append(region_list_fn(db, [str(session_id)]))

        # Last 20 timeline entries
        parts.append("\n=== RECENT TIMELINE (last 20) ===")
        parts.append(timeline_list_fn(db, [str(session_id), "--last", "20"]))

        # Last 5 journal notes
        parts.append("\n=== RECENT JOURNAL (last 5) ===")
        parts.append(journal_list_fn(db, [str(session_id), "--last", "5"]))

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
    from character import cmd_update, cmd_set_attr, cmd_set_item, cmd_set_ability, cmd_remove_item

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

        # Update core fields
        update_args = [str(character_id)]
        if level:
            update_args += ["--level", str(level)]
        if status:
            update_args += ["--status", status]
        if region:
            update_args += ["--region", str(region)]
        if len(update_args) > 1:
            r = cmd_update(db, update_args)
            results.append(r)

        # Set attributes
        attr_count = 0
        for a in attrs_list:
            cmd_set_attr(db, [str(character_id), "--category", a["category"], "--key", a["key"], "--value", str(a["value"])])
            attr_count += 1
        if attr_count:
            results.append(f"ATTRS_SET: {attr_count}")

        # Remove items (by name or ID)
        remove_count = 0
        for item_ref in remove_list:
            if isinstance(item_ref, int):
                cmd_remove_item(db, [str(item_ref)])
                remove_count += 1
            elif isinstance(item_ref, str):
                row = db.execute(
                    "SELECT id FROM character_inventory WHERE character_id = ? AND name = ?",
                    (character_id, item_ref),
                ).fetchone()
                if row:
                    cmd_remove_item(db, [str(row[0])])
                    remove_count += 1
        if remove_count:
            results.append(f"ITEMS_REMOVED: {remove_count}")

        # Set items
        item_count = 0
        for it in items_list:
            args = [str(character_id), "--name", it["name"]]
            if it.get("desc"):
                args += ["--desc", it["desc"]]
            if it.get("qty") and it["qty"] != 1:
                args += ["--qty", str(it["qty"])]
            if it.get("equipped"):
                args += ["--equipped", str(it["equipped"])]
            cmd_set_item(db, args)
            item_count += 1
        if item_count:
            results.append(f"ITEMS_SET: {item_count}")

        # Set abilities
        ability_count = 0
        for ab in abilities_list:
            args = [str(character_id), "--name", ab["name"], "--desc", ab["desc"], "--category", ab["category"]]
            if ab.get("uses"):
                args += ["--uses", ab["uses"]]
            cmd_set_ability(db, args)
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
    "mcp__lorekit__character_get_attr",
    "mcp__lorekit__character_get_items",
    "mcp__lorekit__character_get_abilities",
    "mcp__lorekit__roll_dice",
    "mcp__lorekit__timeline_list",
    "mcp__lorekit__timeline_search",
    "mcp__lorekit__journal_list",
    "mcp__lorekit__journal_search",
    "mcp__lorekit__recall_search",
    "mcp__lorekit__region_view",
    "mcp__lorekit__character_list",
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
