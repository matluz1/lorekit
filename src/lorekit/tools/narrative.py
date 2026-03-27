import json

from lorekit._mcp_app import mcp
from lorekit.tools._helpers import _run_with_db, _timeskip_hours


def region_create(session_id: int, name: str, desc: str = "", parent_id: int = 0) -> str:
    """Create a region in a session. Set parent_id to nest under another region."""
    from lorekit.narrative.region import create

    return _run_with_db(create, session_id, name, desc, parent_id)


def region_list(session_id: int) -> str:
    """List all regions in a session."""
    from lorekit.narrative.region import list_regions

    return _run_with_db(list_regions, session_id)


def region_view(region_id: int) -> str:
    """View region details and all NPCs linked to it."""
    from lorekit.narrative.region import view

    return _run_with_db(view, region_id)


def region_update(region_id: int, name: str = "", desc: str = "", parent_id: int = 0) -> str:
    """Update region name, description, and/or parent."""
    from lorekit.narrative.region import update

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


def timeline_add(session_id: int, type: str, content: str, summary: str = "", narrative_time: str = "") -> str:
    """Add a timeline entry. Type: narration or player_choice. Stamps with current narrative clock unless overridden."""
    from lorekit.narrative.timeline import add

    return _run_with_db(add, session_id, type, content, summary, narrative_time)


@mcp.tool()
def timeline_list(session_id: int, type: str = "", last: int = 0, id: str = "") -> str:
    """List timeline entries. Optionally filter by type and/or limit to last N."""
    from lorekit.narrative.timeline import list_entries

    entry_id = id
    if entry_id:
        return _run_with_db(list_entries, session_id, entry_id=entry_id)
    return _run_with_db(list_entries, session_id, type, last)


def timeline_search(session_id: int, query: str) -> str:
    """Search timeline content by keyword (case-insensitive)."""
    from lorekit.narrative.timeline import search

    return _run_with_db(search, session_id, query)


@mcp.tool()
def timeline_set_summary(timeline_id: int, summary: str) -> str:
    """Set the summary for an existing timeline entry. Re-indexes for semantic search."""
    from lorekit.narrative.timeline import set_summary

    return _run_with_db(set_summary, timeline_id, summary)


@mcp.tool()
def turn_revert(session_id: int, steps: int = 1) -> str:
    """Revert saved turns. Restores all game state (characters, items,
    attributes, story, regions, metadata) and removes timeline/journal entries
    created since the target checkpoint.

    Jumps directly to turn boundaries — auto-checkpoints created during
    combat resolution are skipped automatically.

    steps: how many turns to go back (default 1).
    """
    from lorekit.support.checkpoint import revert_to_previous

    return _run_with_db(revert_to_previous, session_id, steps)


@mcp.tool()
def turn_advance(session_id: int, steps: int = 1) -> str:
    """Redo previously reverted turns. Only works if no new action was
    taken since the revert (future turn checkpoints still exist).

    steps: how many turns to go forward (default 1).
    """
    from lorekit.support.checkpoint import advance_to_next

    return _run_with_db(advance_to_next, session_id, steps)


@mcp.tool()
def journal_add(session_id: int, type: str, content: str, narrative_time: str = "", scope: str = "participants") -> str:
    """Add a journal entry. Types: event, combat, discovery, npc, decision, note.

    scope: who can see this entry during NPC interactions.
      "participants" (default) — only NPCs tagged in the entry's entities.
      "region" — NPCs in the same region as tagged region entities.
      "all" — every NPC in the session (public announcements, world events).
      "gm" — hidden from all NPCs (GM-only notes, secrets, plot hooks).
    """
    from lorekit.narrative.journal import add

    return _run_with_db(add, session_id, type, content, narrative_time, scope)


@mcp.tool()
def journal_list(session_id: int, type: str = "", last: int = 0) -> str:
    """List journal entries. Optionally filter by type and/or limit to last N."""
    from lorekit.narrative.journal import list_entries

    return _run_with_db(list_entries, session_id, type, last)


def journal_search(session_id: int, query: str) -> str:
    """Search journal content by keyword (case-insensitive)."""
    from lorekit.narrative.journal import search

    return _run_with_db(search, session_id, query)


@mcp.tool()
def time_get(session_id: int) -> str:
    """Get the current in-game narrative time for a session."""
    from lorekit.narrative.time import get_time

    return _run_with_db(get_time, session_id)


def time_set(session_id: int, datetime: str) -> str:
    """Set the in-game narrative time (ISO 8601, e.g. '1347-03-15T14:00')."""
    from lorekit.narrative.time import set_time

    return _run_with_db(set_time, session_id, datetime)


@mcp.tool()
def time_advance(session_id: int, amount: int, unit: str) -> str:
    """Advance the in-game clock. Units: minutes, hours, days, weeks, months, years.
    Auto-triggers NPC reflection when unprocessed memory importance exceeds threshold."""
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        from lorekit.narrative.time import advance

        result = advance(db, session_id, amount, unit)

        # Auto-reflect NPCs whose unprocessed memories exceed the importance threshold
        from lorekit.npc.reflect import reflect_all

        ref_result = reflect_all(db, session_id, context_hint=f"{amount} {unit} have passed in-game")
        if "0 NPCs" not in ref_result:
            result += f"\n{ref_result}"

        return result
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def turn_save(
    session_id: int,
    narration: str = "",
    summary: str = "",
    player_choice: str = "",
    narrative_time: str = "",
    scope: str = "participants",
    force: bool = False,
) -> str:
    """Save a game turn: narration + player choice + last_gm_message in one call.

    At least one of narration or player_choice is required.
    If narration is provided, it is saved to the timeline and last_gm_message is updated.
    If player_choice is provided, it is saved to the timeline.
    Always include a summary when providing narration (used for semantic search).
    narrative_time: optional override for the in-game timestamp on these entries.
      If omitted, the current narrative clock is used automatically.
    scope: who can see these entries during NPC interactions.
      "participants" (default) — only NPCs tagged in the entry's entities.
      "region" — NPCs in the same region as tagged region entities.
      "all" — every NPC in the session (public scenes, announcements).
      "gm" — hidden from all NPCs (secrets, plot hooks, GM notes).
    Always call turn_save as your last action before the player acts.
    During combat, encounter_advance_turn reminds you when a PC turn begins.
    force: if True and the cursor is behind the tip, delete future checkpoints
      and save here (like making a new git commit after checkout — the old branch
      is lost). Without force, the call is rejected to prevent accidental data loss.

    WARNING: After a turn_revert, do NOT call turn_save until you have advanced
    back to the desired checkpoint with turn_advance (if needed), unless you pass
    force=True to confirm you want to discard the future checkpoints.
    """
    if not narration and not player_choice:
        return "ERROR: Provide at least one of narration or player_choice"

    from lorekit.db import LoreKitError, require_db
    from lorekit.narrative.session import meta_set
    from lorekit.narrative.timeline import add as tl_add
    from lorekit.support.checkpoint import create_checkpoint

    db = require_db()
    try:
        # On first turn, create checkpoint #0 (pre-game state) so we can revert it
        has_cp = db.execute(
            "SELECT 1 FROM checkpoints WHERE session_id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        if not has_cp:
            create_checkpoint(db, session_id, kind="turn")

        results = []
        saved_entries = []  # (source, source_id, text) for entity auto-tagging

        # Save player_choice BEFORE narration so that on resume the narration
        # is always the last timeline entry — making it clear the choice was
        # already resolved. If only a player_choice exists (no narration yet),
        # it correctly appears as the last entry, signaling a pending action.
        if player_choice:
            r = tl_add(db, session_id, "player_choice", player_choice, narrative_time=narrative_time, scope=scope)
            results.append(r)
            try:
                tl_id = int(r.split(": ")[1])
                saved_entries.append(("timeline", tl_id, player_choice))
            except (IndexError, ValueError):
                pass

        if narration:
            r = tl_add(db, session_id, "narration", narration, summary, narrative_time, scope=scope)
            results.append(r)
            try:
                tl_id = int(r.split(": ")[1])
                saved_entries.append(("timeline", tl_id, narration))
            except (IndexError, ValueError):
                pass
            r = meta_set(db, session_id, "last_gm_message", narration)
            results.append(r)

        # Auto-tag entities in saved entries
        try:
            from lorekit.npc.prefetch import extract_entities

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

        # Warn if saving mid-round (characters haven't acted yet)
        enc_row = db.execute(
            "SELECT initiative_order, current_turn FROM encounter_state WHERE session_id = ? AND status = 'active'",
            (session_id,),
        ).fetchone()
        if enc_row:
            init_order = json.loads(enc_row[0])
            current_turn = enc_row[1]
            remaining = len(init_order) - current_turn - 1
            if remaining > 0 and current_turn > 0:
                names = []
                from lorekit.queries import get_character_name as _get_name

                for cid in init_order[current_turn + 1 :]:
                    cname = _get_name(db, cid)
                    if cname:
                        names.append(cname)
                results.append(
                    f"⚠ INCOMPLETE ROUND: {remaining} character(s) have not acted this round ({', '.join(names)})"
                )

        # Checkpoint after writing (the "approved" state after this turn)
        create_checkpoint(db, session_id, force=force, kind="turn")

        return "\n".join(results)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


def story_set(session_id: int, size: str, premise: str) -> str:
    """Create or overwrite the story plan for a session. Size: oneshot, short, campaign."""
    from lorekit.narrative.story import set_story

    return _run_with_db(set_story, session_id, size, premise)


def story_view(session_id: int, act_id: int = 0) -> str:
    """Show the story premise and all acts. If act_id is given, show full details for that act only."""
    if act_id:
        from lorekit.narrative.story import view_act

        return _run_with_db(view_act, act_id)
    from lorekit.narrative.story import view

    return _run_with_db(view, session_id)


def story_add_act(session_id: int, title: str, desc: str = "", goal: str = "", event: str = "") -> str:
    """Append an act to the story. Order is auto-assigned."""
    from lorekit.narrative.story import add_act

    return _run_with_db(add_act, session_id, title, desc, goal, event)


def story_view_act(act_id: int) -> str:
    """Show full details for a single act. (Internal — use story_view with act_id instead.)"""
    from lorekit.narrative.story import view_act

    return _run_with_db(view_act, act_id)


def story_update_act(
    act_id: int, title: str = "", desc: str = "", goal: str = "", event: str = "", status: str = ""
) -> str:
    """Update one or more fields on an act."""
    from lorekit.narrative.story import update_act

    return _run_with_db(update_act, act_id, title, desc, goal, event, status)


def story_advance(session_id: int) -> str:
    """Complete the current active act and activate the next pending one."""
    from lorekit.narrative.story import advance

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
