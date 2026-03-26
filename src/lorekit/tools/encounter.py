import json

from lorekit._mcp_app import mcp
from lorekit.tools._helpers import (
    _auto_register_reactions,
    _load_combat_cfg,
    _resolve_character,
    _resolve_system_path_for_session,
    _session_for_character,
)


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
    from lorekit.db import LoreKitError, require_db

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

        from lorekit.encounter import start_encounter

        result = start_encounter(
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

        # Auto-register reactions from character abilities
        reaction_lines = _auto_register_reactions(db, session_id)
        if reaction_lines:
            result += "\n" + "\n".join(reaction_lines)

        return result
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
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        combat_cfg = _load_combat_cfg(db, session_id)

        from lorekit.encounter import get_status

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
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        # Find the character's session and active encounter
        session_id = _session_for_character(db, character_id)

        from lorekit.encounter import _require_active_encounter

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

        # Check for movement modes that bypass adjacency (e.g. teleport)
        mode_rows = db.execute(
            "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'movement_mode'",
            (character_id,),
        ).fetchall()
        skip_adj = any(json.loads(v).get("skip_adjacency") for (v,) in mode_rows) if mode_rows else False

        from lorekit.encounter import move_character

        return move_character(
            db,
            enc_id,
            character_id,
            target_zone,
            combat_cfg=combat_cfg,
            movement_budget=movement_budget,
            skip_adjacency=skip_adj,
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
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        combat_cfg = _load_combat_cfg(db, session_id)

        from lorekit.encounter import advance_turn

        return advance_turn(db, session_id, combat_cfg=combat_cfg)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_ready(
    character_id: int | str,
    action: str,
    trigger: str,
    targets: str = "",
) -> str:
    """Ready an action on the current character's turn.

    The character gives up their turn to hold a specified action until a
    trigger condition occurs. Call encounter_execute_ready when the trigger
    fires during another character's turn.

    character_id: numeric ID or character name.
    action: action name to ready (e.g. "grab", "close_attack").
    trigger: text description of the trigger condition (e.g. "when Quill moves").
    targets: optional target name or ID for the readied action.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        session_id = _session_for_character(db, character_id)
        system_path = _resolve_system_path_for_session(db, session_id)
        from lorekit.encounter import ready_action

        result = ready_action(db, session_id, character_id, action, trigger, targets, pack_dir=system_path or None)

        # Auto-advance turn after readying
        combat_cfg = _load_combat_cfg(db, session_id)
        from lorekit.encounter import advance_turn

        advance_result = advance_turn(db, session_id, combat_cfg=combat_cfg)
        return result + "\n\n" + advance_result
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_execute_ready(character_id: int | str) -> str:
    """Fire a character's readied action.

    Called when the trigger condition occurs during another character's turn.
    Resolves the readied action and consumes it.

    character_id: numeric ID or name of the character whose readied action to fire.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        session_id = _session_for_character(db, character_id)
        system_path = _resolve_system_path_for_session(db, session_id)
        from lorekit.encounter import execute_ready

        return execute_ready(db, session_id, character_id, pack_dir=system_path or None)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_delay(character_id: int | str) -> str:
    """Delay the current character's turn.

    Removes the character from initiative order temporarily and advances
    to the next character. Use encounter_undelay when they want to act.

    character_id: numeric ID or character name.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        session_id = _session_for_character(db, character_id)
        from lorekit.encounter import delay_turn

        return delay_turn(db, session_id, character_id)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_undelay(character_id: int | str) -> str:
    """Insert a delayed character back into initiative and start their turn.

    The character acts immediately, inserted just before the current
    character in initiative. Their new position persists for subsequent rounds.

    character_id: numeric ID or name of the delayed character.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        session_id = _session_for_character(db, character_id)
        combat_cfg = _load_combat_cfg(db, session_id)
        from lorekit.encounter import undelay

        return undelay(db, session_id, character_id, combat_cfg=combat_cfg)
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
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        combat_cfg = _load_combat_cfg(db, session_id)
        system_path = _resolve_system_path_for_session(db, session_id)
        from lorekit.encounter import end_encounter

        return end_encounter(db, session_id, combat_cfg=combat_cfg, pack_dir=system_path or None)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_join(
    character_id: int | str,
    zone: str,
    team: str = "",
    initiative_roll: int = 0,
) -> str:
    """Add a character to an active encounter mid-combat (summon, reinforcement).

    Inserts the character into initiative order, places in the specified zone,
    and applies terrain modifiers. The character acts on their next turn.

    character_id: numeric ID or character name.
    zone: name of the zone to place the character in.
    team: optional team name for ally/enemy grouping.
    initiative_roll: initiative value for ordering (default 0 = after current turn).
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        session_id = _session_for_character(db, _resolve_character(db, character_id))
        character_id = _resolve_character(db, character_id)
        combat_cfg = _load_combat_cfg(db, session_id)
        from lorekit.encounter import join_encounter

        return join_encounter(db, session_id, character_id, zone, team, initiative_roll, combat_cfg)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_leave(character_id: int | str) -> str:
    """Remove a character from an active encounter (dismissed summon, death, retreat).

    Removes from initiative order, clears zone placement, removes
    encounter-duration modifiers and terrain modifiers.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        session_id = _session_for_character(db, character_id)
        combat_cfg = _load_combat_cfg(db, session_id)
        system_path = _resolve_system_path_for_session(db, session_id)
        from lorekit.encounter import leave_encounter

        return leave_encounter(db, session_id, character_id, combat_cfg, pack_dir=system_path or None)
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
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        from lorekit.encounter import _require_active_encounter, update_zone_tags

        enc_id, _, _, _ = _require_active_encounter(db, session_id)
        combat_cfg = _load_combat_cfg(db, session_id)
        tags_list = json.loads(tags)

        return update_zone_tags(db, enc_id, zone_name, tags_list, combat_cfg=combat_cfg)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_zone_add(
    session_id: int,
    zone_name: str,
    tags: str = "[]",
    adjacent_to: str = "[]",
) -> str:
    """Create a new zone mid-combat (pocket dimension, aerial, collapsing floor reveals basement).

    zone_name: name for the new zone.
    tags: JSON array — ["cover", "difficult_terrain"]
    adjacent_to: JSON array — [{"zone": "Arena", "weight": 1}, ...]
      Declares which existing zones connect to the new one. Empty = isolated.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        from lorekit.encounter import _require_active_encounter, add_zone

        enc_id, _, _, _ = _require_active_encounter(db, session_id)
        tag_list = json.loads(tags) if tags else []
        adj_list = json.loads(adjacent_to) if adjacent_to else []

        return add_zone(db, enc_id, zone_name, tags=tag_list, adjacent_to=adj_list)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def encounter_zone_remove(
    session_id: int,
    zone_name: str,
    evacuate_to: str = "",
) -> str:
    """Remove a zone mid-combat (portal closes, terrain collapses).

    Moves any occupants to evacuate_to zone (required if zone has characters).
    Removes all adjacency edges and terrain modifiers.

    zone_name: zone to remove.
    evacuate_to: zone to move occupants to (required if zone is occupied).
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        from lorekit.encounter import _require_active_encounter, remove_zone

        enc_id, _, _, _ = _require_active_encounter(db, session_id)
        combat_cfg = _load_combat_cfg(db, session_id)

        return remove_zone(db, enc_id, zone_name, evacuate_to=evacuate_to or None, combat_cfg=combat_cfg)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()
