#!/usr/bin/env python3
"""LoreKit MCP server -- long-lived process with cached embedding model."""

import io
import os
import sys

# Silence ChromaDB telemetry notice
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

# Allow imports from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lorekit")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cmd(fn, *args):
    """Call fn(*args), capturing stdout/stderr and catching SystemExit."""
    old_out, old_err = sys.stdout, sys.stderr
    buf_out, buf_err = io.StringIO(), io.StringIO()
    try:
        sys.stdout, sys.stderr = buf_out, buf_err
        fn(*args)
    except SystemExit:
        pass
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    err = buf_err.getvalue().strip()
    out = buf_out.getvalue().strip()
    if err and out:
        return f"{out}\n{err}"
    return err or out


def _run_with_db(fn, args_list):
    """Get a DB connection, call fn(db, args_list), close DB."""
    from _db import require_db

    db = require_db()
    try:
        return _run_cmd(fn, db, args_list)
    finally:
        db.close()


def _run_no_db(fn, args_list):
    """Call fn(args_list) without a DB connection (for recall.py)."""
    return _run_cmd(fn, args_list)


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
def region_create(session_id: int, name: str, desc: str = "") -> str:
    """Create a region in a session."""
    from region import cmd_create

    args = [str(session_id), "--name", name]
    if desc:
        args += ["--desc", desc]
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
def region_update(region_id: int, name: str = "", desc: str = "") -> str:
    """Update region name and/or description."""
    from region import cmd_update

    args = [str(region_id)]
    if name:
        args += ["--name", name]
    if desc:
        args += ["--desc", desc]
    return _run_with_db(cmd_update, args)


# ---------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------


@mcp.tool()
def timeline_add(session_id: int, type: str, content: str, summary: str = "") -> str:
    """Add a timeline entry. Type: narration or player_choice."""
    from timeline import cmd_add

    args = [str(session_id), "--type", type, "--content", content]
    if summary:
        args += ["--summary", summary]
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


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------


@mcp.tool()
def journal_add(session_id: int, type: str, content: str) -> str:
    """Add a journal entry. Types: event, combat, discovery, npc, decision, note."""
    from journal import cmd_add

    return _run_with_db(cmd_add, [str(session_id), "--type", type, "--content", content])


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
# rolldice
# ---------------------------------------------------------------------------


@mcp.tool()
def roll_dice(expression: str) -> str:
    """Roll dice using tabletop notation. Format: [N]d<sides>[kh<keep>][+/-mod]. Separate multiple expressions with spaces."""
    from rolldice import roll_expr, format_result

    expressions = expression.split()
    results = []
    for expr in expressions:
        # roll_expr prints to stderr and calls sys.exit(1) on invalid input
        err_buf = io.StringIO()
        old_stderr = sys.stderr
        try:
            sys.stderr = err_buf
            r = roll_expr(expr)
            results.append((expr, r))
        except SystemExit:
            sys.stderr = old_stderr
            return err_buf.getvalue().strip()
        finally:
            sys.stderr = old_stderr

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
    return _run_no_db(cmd_search, args)


@mcp.tool()
def recall_reindex(session_id: int) -> str:
    """Rebuild vector collections from SQL data for a session."""
    from recall import cmd_reindex

    return _run_no_db(cmd_reindex, [str(session_id)])


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
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Eagerly load the embedding model so the first vector operation
    # doesn't pay a cold-start penalty.
    from _vectordb import _get_model

    _get_model()
    mcp.run()
