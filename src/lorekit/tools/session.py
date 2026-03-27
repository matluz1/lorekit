import json
import sqlite3

from lorekit._mcp_app import mcp
from lorekit.tools._helpers import _load_combat_cfg, _run_with_db


def init_db() -> str:
    """Create or verify the LoreKit database schema. Safe to re-run."""
    from lorekit.db import init_schema

    db_path = init_schema()
    return f"Database initialized at {db_path}"


def session_create(name: str, setting: str, system: str) -> str:
    """Create a new adventure session. (Internal — use session_setup instead.)"""
    from lorekit.narrative.session import create

    return _run_with_db(create, name, setting, system)


def session_view(session_id: int) -> str:
    """View session details. (Internal — use session_resume or session_list instead.)"""
    from lorekit.narrative.session import view

    return _run_with_db(view, session_id)


@mcp.tool()
def session_list(status: str = "") -> str:
    """List all sessions. Optionally filter by status (active/finished).
    Call without arguments first to see all sessions — a finished session
    can still be resumed for a new adventure arc."""
    from lorekit.narrative.session import list_sessions

    return _run_with_db(list_sessions, status)


@mcp.tool()
def session_update(session_id: int, status: str) -> str:
    """Update session status. Auto-triggers NPC reflection when session is finished.
    WARNING: Only set status to 'finished' when the adventure's story is truly
    complete. If the player just wants to pause play, do nothing — the session
    stays active and can be resumed later with session_resume."""
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        from lorekit.narrative.session import update

        result = update(db, session_id, status)

        if status == "finished":
            from lorekit.npc.reflect import reflect_all

            ref_result = reflect_all(db, session_id, threshold=0.0, context_hint="Session ended")
            result += f"\n{ref_result}"

        return result
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def session_meta_set(session_id: int, key: str, value: str) -> str:
    """Set a session metadata key-value pair. Overwrites if key exists.

    Keys with the "lore_" prefix are automatically included in NPC prompts as world
    knowledge (capped at ~800 tokens). Use these for fundamental facts about the setting
    that all characters would know (e.g. lore_biology, lore_society, lore_magic).
    """
    from lorekit.narrative.session import meta_set

    return _run_with_db(meta_set, session_id, key, value)


@mcp.tool()
def session_meta_get(session_id: int, key: str = "") -> str:
    """Get session metadata. If key is empty, returns all metadata."""
    from lorekit.narrative.session import meta_get

    return _run_with_db(meta_get, session_id, key)


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
      Keys prefixed with "lore_" are automatically included in NPC prompts as world knowledge
      (capped at ~800 tokens). Use these for fundamental setting facts that all characters
      would know (e.g. lore_biology, lore_society, lore_magic). Other keys remain GM-only.
    acts: JSON array of {"title":"...","desc":"...","goal":"...","event":"..."} objects.
    regions: JSON array of {"name":"...","desc":"...","children":[{"name":"...","desc":"..."}]} objects.
    narrative_time: initial in-game time as ISO 8601, e.g. "1347-03-15T14:00".
    The first act is automatically set to "active".
    """
    from lorekit.db import LoreKitError, require_db
    from lorekit.narrative.region import create as region_create_fn
    from lorekit.narrative.session import create as sess_create
    from lorekit.narrative.session import meta_set
    from lorekit.narrative.story import add_act, update_act
    from lorekit.narrative.story import set_story as story_set_fn

    try:
        meta_dict = json.loads(meta)
        acts_list = json.loads(acts)
        regions_list = json.loads(regions)
    except json.JSONDecodeError as e:
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
    from lorekit.character import view as char_view
    from lorekit.db import LoreKitError, require_db
    from lorekit.narrative.journal import list_entries as journal_list_fn
    from lorekit.narrative.region import list_regions as region_list_fn
    from lorekit.narrative.session import meta_get
    from lorekit.narrative.session import view as sess_view
    from lorekit.narrative.story import view as story_view_fn
    from lorekit.narrative.timeline import list_entries as timeline_list_fn

    db = require_db()
    try:
        parts = []

        # Show save count if any manual saves exist
        save_count = db.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE session_id = ? AND name IS NOT NULL",
            (session_id,),
        ).fetchone()[0]
        if save_count:
            parts.append(f"📁 {save_count} save(s) available — use save_list to view")
            parts.append("")

        # Active encounter first (so it appears in truncated previews)
        enc_row = db.execute(
            "SELECT id FROM encounter_state WHERE session_id = ? AND status = 'active'",
            (session_id,),
        ).fetchone()
        if enc_row:
            from lorekit.encounter import get_status

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

        parts.append("\n=== CHARACTERS ===")
        db.row_factory = sqlite3.Row
        prefetched = db.execute(
            "SELECT id FROM characters WHERE session_id = ? AND prefetch = 1 ORDER BY id",
            (session_id,),
        ).fetchall()
        db.row_factory = None
        if prefetched:
            for ch in prefetched:
                parts.append(char_view(db, ch["id"]))
                parts.append("")
        else:
            parts.append("(no characters)")

        parts.append("=== REGIONS ===")
        parts.append(region_list_fn(db, session_id))

        parts.append("\n=== RECENT TIMELINE (last 20) ===")
        parts.append(timeline_list_fn(db, session_id, last=20))

        parts.append("\n=== RECENT JOURNAL (last 5) ===")
        parts.append(journal_list_fn(db, session_id, last=5))

        # Auto-reindex vector collections on resume
        try:
            from lorekit.support.recall import reindex

            reindex(db, session_id)
        except Exception:
            pass

        return "\n".join(parts)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()
