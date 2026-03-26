from lorekit._mcp_app import mcp
from lorekit.tools._helpers import _run_with_db


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
