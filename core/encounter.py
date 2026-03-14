"""encounter.py — Zone-based combat positioning and encounter state.

Manages encounter lifecycle (start, status, advance turn, end) and
zone-based positioning (movement validation, range checks, terrain
modifiers). Zone graph uses weighted adjacency with Dijkstra shortest
path for distance calculations.

All system-specific values (zone_scale, terrain effects, movement
formulas) come from the system pack's `combat` section. The module
is zero-knowledge about what zones or tags mean.
"""

from __future__ import annotations

import heapq
import json
from typing import Any

from _db import LoreKitError


def _resolve_system_path(db, session_id: int) -> str | None:
    """Resolve the system pack directory from session metadata.

    Returns the full path, or None if no rules_system is configured.
    """
    import os

    meta_row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'rules_system'",
        (session_id,),
    ).fetchone()
    if meta_row is None:
        return None

    system_name = meta_row[0]
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    system_path = os.path.join(project_root, "systems", system_name)
    return system_path if os.path.isdir(system_path) else None


# ---------------------------------------------------------------------------
# Zone graph — shortest path
# ---------------------------------------------------------------------------

def _build_adjacency(db, encounter_id: int) -> dict[int, list[tuple[int, int]]]:
    """Build adjacency list from zone_adjacency rows.

    Returns {zone_id: [(neighbor_id, weight), ...]} with bidirectional edges.
    """
    zone_ids = [
        r[0] for r in db.execute(
            "SELECT id FROM encounter_zones WHERE encounter_id = ?",
            (encounter_id,),
        ).fetchall()
    ]
    adj: dict[int, list[tuple[int, int]]] = {z: [] for z in zone_ids}

    if not zone_ids:
        return adj

    ph = ",".join("?" * len(zone_ids))
    rows = db.execute(
        f"SELECT zone_a, zone_b, weight FROM zone_adjacency "
        f"WHERE zone_a IN ({ph})",
        zone_ids,
    ).fetchall()

    for a, b, w in rows:
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))

    return adj


def _shortest_path(adj: dict[int, list[tuple[int, int]]], start: int, end: int) -> int | None:
    """Dijkstra shortest path cost between two zone IDs.

    Returns the total weight, or None if unreachable.
    """
    if start == end:
        return 0

    dist: dict[int, int] = {start: 0}
    heap = [(0, start)]

    while heap:
        d, node = heapq.heappop(heap)
        if node == end:
            return d
        if d > dist.get(node, float("inf")):
            continue
        for neighbor, weight in adj.get(node, []):
            nd = d + weight
            if nd < dist.get(neighbor, float("inf")):
                dist[neighbor] = nd
                heapq.heappush(heap, (nd, neighbor))

    return None


def _zone_distance(db, encounter_id: int, zone_a_id: int, zone_b_id: int) -> int | None:
    """Compute shortest path distance between two zones."""
    adj = _build_adjacency(db, encounter_id)
    return _shortest_path(adj, zone_a_id, zone_b_id)


def _get_zone_tags(db, zone_id: int) -> list[str]:
    """Get tags for a zone."""
    row = db.execute("SELECT tags FROM encounter_zones WHERE id = ?", (zone_id,)).fetchone()
    if row is None:
        return []
    return json.loads(row[0])


def _movement_cost(db, adj: dict[int, list[tuple[int, int]]],
                   start: int, end: int,
                   combat_cfg: dict) -> int | None:
    """Compute movement cost accounting for difficult terrain multipliers.

    Traverses the shortest path and applies zone_tags multipliers for
    zones along the way.
    """
    if start == end:
        return 0

    zone_tags_cfg = combat_cfg.get("zone_tags", {})

    # Dijkstra with terrain-aware costs
    dist: dict[int, int] = {start: 0}
    heap = [(0, start)]

    while heap:
        d, node = heapq.heappop(heap)
        if node == end:
            return d
        if d > dist.get(node, float("inf")):
            continue
        for neighbor, weight in adj.get(node, []):
            # Check destination zone for movement multipliers
            tags = _get_zone_tags(db, neighbor)
            multiplier = 1
            for tag in tags:
                tag_cfg = zone_tags_cfg.get(tag, {})
                m = tag_cfg.get("movement_multiplier")
                if m and m > multiplier:
                    multiplier = m
            nd = d + weight * multiplier
            if nd < dist.get(neighbor, float("inf")):
                dist[neighbor] = nd
                heapq.heappush(heap, (nd, neighbor))

    return None


# ---------------------------------------------------------------------------
# Terrain modifier management
# ---------------------------------------------------------------------------

def _apply_zone_terrain(db, character_id: int, zone_id: int,
                        zone_name: str, combat_cfg: dict) -> list[str]:
    """Apply terrain modifiers from zone tags to a character via combat_state.

    Returns list of modifier descriptions applied.
    """
    tags = _get_zone_tags(db, zone_id)
    zone_tags_cfg = combat_cfg.get("zone_tags", {})
    applied = []

    for tag in tags:
        tag_cfg = zone_tags_cfg.get(tag, {})
        target_stat = tag_cfg.get("target_stat")
        value = tag_cfg.get("value")
        if target_stat and value is not None:
            mod_type = tag_cfg.get("modifier_type", "environment")
            source = f"zone:{zone_name}:{tag}"
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type) "
                "VALUES (?, ?, ?, ?, ?, 'encounter') "
                "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET "
                "value = excluded.value",
                (character_id, source, target_stat, mod_type, value),
            )
            applied.append(f"{tag}: {target_stat} {value:+d}")

    return applied


def _remove_zone_terrain(db, character_id: int, zone_name: str) -> int:
    """Remove terrain modifiers from a zone for a character.

    Returns number of modifiers removed.
    """
    return db.execute(
        "DELETE FROM combat_state WHERE character_id = ? AND source LIKE ?",
        (character_id, f"zone:{zone_name}:%"),
    ).rowcount


# ---------------------------------------------------------------------------
# Encounter lifecycle
# ---------------------------------------------------------------------------

def _get_active_encounter(db, session_id: int):
    """Get the active encounter for a session, or None."""
    return db.execute(
        "SELECT id, round, initiative_order, current_turn "
        "FROM encounter_state WHERE session_id = ? AND status = 'active'",
        (session_id,),
    ).fetchone()


def _require_active_encounter(db, session_id: int):
    """Get active encounter or raise."""
    row = _get_active_encounter(db, session_id)
    if row is None:
        raise LoreKitError("No active encounter in this session")
    return row


def _zone_name_to_id(db, encounter_id: int, name: str) -> int:
    """Resolve zone name to ID within an encounter."""
    row = db.execute(
        "SELECT id FROM encounter_zones WHERE encounter_id = ? AND name = ?",
        (encounter_id, name),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"Zone '{name}' not found in encounter {encounter_id}")
    return row[0]


def _zone_id_to_name(db, zone_id: int) -> str:
    """Resolve zone ID to name."""
    row = db.execute("SELECT name FROM encounter_zones WHERE id = ?", (zone_id,)).fetchone()
    if row is None:
        raise LoreKitError(f"Zone ID {zone_id} not found")
    return row[0]


def _get_character_zone(db, encounter_id: int, character_id: int):
    """Get zone_id for a character in an encounter, or None."""
    row = db.execute(
        "SELECT zone_id FROM character_zone WHERE encounter_id = ? AND character_id = ?",
        (encounter_id, character_id),
    ).fetchone()
    return row[0] if row else None


def start_encounter(
    db, session_id: int, zones: list[dict], initiative: list[dict],
    adjacency: list[dict] | None = None,
    placements: list[dict] | None = None,
    combat_cfg: dict | None = None,
) -> str:
    """Start a combat encounter with zones, initiative, and optional placements.

    Parameters:
    - zones: [{"name": "...", "tags": ["cover", ...]}, ...]
    - initiative: [{"character_id": N, "roll": M}, ...]
    - adjacency: [{"from": "A", "to": "B", "weight": 1}, ...] or None for linear chain
    - placements: [{"character_id": N, "zone": "name"}, ...] or None
    - combat_cfg: system pack's combat section (for terrain modifiers)
    """
    # Check no active encounter already
    existing = _get_active_encounter(db, session_id)
    if existing is not None:
        raise LoreKitError("An encounter is already active in this session. End it first.")

    if not zones:
        raise LoreKitError("At least one zone is required")

    # Sort initiative descending
    sorted_init = sorted(initiative, key=lambda x: x["roll"], reverse=True)
    init_order = [entry["character_id"] for entry in sorted_init]

    # Create encounter
    cur = db.execute(
        "INSERT INTO encounter_state (session_id, initiative_order) VALUES (?, ?)",
        (session_id, json.dumps(init_order)),
    )
    enc_id = cur.lastrowid

    # Create zones
    zone_id_map: dict[str, int] = {}
    for zone in zones:
        name = zone["name"]
        tags = json.dumps(zone.get("tags", []))
        zcur = db.execute(
            "INSERT INTO encounter_zones (encounter_id, name, tags) VALUES (?, ?, ?)",
            (enc_id, name, tags),
        )
        zone_id_map[name] = zcur.lastrowid

    # Create adjacency
    if adjacency:
        for edge in adjacency:
            a_id = zone_id_map.get(edge["from"])
            b_id = zone_id_map.get(edge["to"])
            if a_id is None or b_id is None:
                raise LoreKitError(
                    f"Adjacency references unknown zone: {edge['from']} or {edge['to']}"
                )
            weight = edge.get("weight", 1)
            db.execute(
                "INSERT INTO zone_adjacency (zone_a, zone_b, weight) VALUES (?, ?, ?)",
                (a_id, b_id, weight),
            )
    else:
        # Default: linear chain
        zone_names = [z["name"] for z in zones]
        for i in range(len(zone_names) - 1):
            a_id = zone_id_map[zone_names[i]]
            b_id = zone_id_map[zone_names[i + 1]]
            db.execute(
                "INSERT INTO zone_adjacency (zone_a, zone_b, weight) VALUES (?, ?, ?)",
                (a_id, b_id, 1),
            )

    # Place characters
    cfg = combat_cfg or {}
    terrain_lines = []
    if placements:
        for p in placements:
            cid = p["character_id"]
            zone_name = p["zone"]
            zid = zone_id_map.get(zone_name)
            if zid is None:
                raise LoreKitError(f"Placement references unknown zone: {zone_name}")
            db.execute(
                "INSERT INTO character_zone (encounter_id, character_id, zone_id) "
                "VALUES (?, ?, ?)",
                (enc_id, cid, zid),
            )
            # Apply terrain modifiers
            mods = _apply_zone_terrain(db, cid, zid, zone_name, cfg)
            if mods:
                terrain_lines.append(f"  Terrain on {_char_name(db, cid)}: {', '.join(mods)}")

    db.commit()

    # Auto-recalc derived stats for placed characters with terrain modifiers
    if placements:
        from rules_engine import try_rules_calc
        for p in placements:
            recalc = try_rules_calc(db, p["character_id"])
            if recalc:
                terrain_lines.append(recalc)

    # Format output
    lines = [f"ENCOUNTER STARTED (session {session_id})"]
    lines.append(f"Round: 1")

    # Initiative display
    init_names = []
    for entry in sorted_init:
        cname = _char_name(db, entry["character_id"])
        init_names.append(f"{cname} ({entry['roll']})")
    lines.append(f"Initiative: {', '.join(init_names)}")

    # Zones display
    zone_parts = []
    for z in zones:
        tags = z.get("tags", [])
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        zone_parts.append(f"{z['name']}{tag_str}")
    lines.append(f"Zones: {' ↔ '.join(zone_parts)}")

    # Placements display
    if placements:
        pos_parts = []
        for p in placements:
            cname = _char_name(db, p["character_id"])
            pos_parts.append(f"{cname} → {p['zone']}")
        lines.append(f"Positions: {', '.join(pos_parts)}")

    lines.extend(terrain_lines)

    return "\n".join(lines)


def _char_name(db, character_id: int) -> str:
    """Get character name by ID."""
    row = db.execute("SELECT name FROM characters WHERE id = ?", (character_id,)).fetchone()
    return row[0] if row else f"character {character_id}"


def get_status(db, session_id: int, combat_cfg: dict | None = None) -> str:
    """Return the current encounter state as a formatted string."""
    enc_id, rnd, init_json, current_turn = _require_active_encounter(db, session_id)
    init_order = json.loads(init_json)
    cfg = combat_cfg or {}
    zone_scale = cfg.get("zone_scale", 1)
    movement_unit = cfg.get("movement_unit", "zone")

    # Current turn character
    current_char_id = init_order[current_turn] if init_order else None
    current_name = _char_name(db, current_char_id) if current_char_id else "none"

    lines = [f"ENCOUNTER STATUS (session {session_id})"]
    lines.append(f"Round: {rnd}, Turn: {current_name}")

    # Initiative
    init_names = [_char_name(db, cid) for cid in init_order]
    lines.append(f"Initiative: {', '.join(init_names)}")

    # Positions
    zones_rows = db.execute(
        "SELECT id, name, tags FROM encounter_zones WHERE encounter_id = ?",
        (enc_id,),
    ).fetchall()
    zone_map = {r[0]: (r[1], json.loads(r[2])) for r in zones_rows}

    char_zones = db.execute(
        "SELECT character_id, zone_id FROM character_zone WHERE encounter_id = ?",
        (enc_id,),
    ).fetchall()

    lines.append("Positions:")
    char_zone_map: dict[int, int] = {}
    for cid, zid in char_zones:
        char_zone_map[cid] = zid
        zname, ztags = zone_map.get(zid, (f"zone {zid}", []))
        tag_str = f" [{', '.join(ztags)}]" if ztags else ""
        lines.append(f"  {_char_name(db, cid)} → {zname}{tag_str}")

    # Distances
    if len(char_zones) > 1:
        adj = _build_adjacency(db, enc_id)
        lines.append("Distances:")
        seen = set()
        for cid_a, zid_a in char_zones:
            for cid_b, zid_b in char_zones:
                if cid_a >= cid_b:
                    continue
                pair = (min(cid_a, cid_b), max(cid_a, cid_b))
                if pair in seen:
                    continue
                seen.add(pair)
                dist = _shortest_path(adj, zid_a, zid_b)
                if dist is not None:
                    if zone_scale > 1:
                        lines.append(
                            f"  {_char_name(db, cid_a)} ↔ {_char_name(db, cid_b)}: "
                            f"{dist} zone(s) ({dist * zone_scale}{movement_unit})"
                        )
                    else:
                        lines.append(
                            f"  {_char_name(db, cid_a)} ↔ {_char_name(db, cid_b)}: "
                            f"{dist} zone(s)"
                        )
                else:
                    lines.append(
                        f"  {_char_name(db, cid_a)} ↔ {_char_name(db, cid_b)}: unreachable"
                    )

    return "\n".join(lines)


def move_character(
    db, encounter_id: int, character_id: int, target_zone: str,
    combat_cfg: dict | None = None,
    movement_budget: int | None = None,
) -> str:
    """Move a character to a different zone with validation.

    Parameters:
    - movement_budget: max zones the character can traverse (from derived stat
      or system default). If None, movement is unrestricted.
    - combat_cfg: system pack's combat section (for terrain costs)
    """
    cfg = combat_cfg or {}
    zone_scale = cfg.get("zone_scale", 1)
    movement_unit = cfg.get("movement_unit", "zone")

    # Resolve target zone
    target_zid = _zone_name_to_id(db, encounter_id, target_zone)

    # Get current zone
    current_zid = _get_character_zone(db, encounter_id, character_id)
    if current_zid is None:
        raise LoreKitError(
            f"Character {_char_name(db, character_id)} is not placed in the encounter"
        )

    if current_zid == target_zid:
        return f"{_char_name(db, character_id)} is already in {target_zone}"

    current_zone_name = _zone_id_to_name(db, current_zid)

    # Validate movement cost
    adj = _build_adjacency(db, encounter_id)
    cost = _movement_cost(db, adj, current_zid, target_zid, cfg)

    if cost is None:
        raise LoreKitError(
            f"Cannot reach {target_zone} from {current_zone_name} — no path exists"
        )

    if movement_budget is not None and cost > movement_budget:
        if zone_scale > 1:
            raise LoreKitError(
                f"Cannot reach {target_zone}. Cost: {cost} zone(s) "
                f"({cost * zone_scale}{movement_unit}). "
                f"Movement budget: {movement_budget} zone(s) "
                f"({movement_budget * zone_scale}{movement_unit}). "
                f"Current position: {current_zone_name}."
            )
        else:
            raise LoreKitError(
                f"Cannot reach {target_zone}. Cost: {cost} zone(s). "
                f"Movement budget: {movement_budget} zone(s). "
                f"Current position: {current_zone_name}."
            )

    # Remove old zone terrain modifiers
    _remove_zone_terrain(db, character_id, current_zone_name)

    # Update position
    db.execute(
        "UPDATE character_zone SET zone_id = ? WHERE encounter_id = ? AND character_id = ?",
        (target_zid, encounter_id, character_id),
    )

    # Apply new zone terrain modifiers
    terrain = _apply_zone_terrain(db, character_id, target_zid, target_zone, cfg)

    db.commit()

    cname = _char_name(db, character_id)
    lines = [f"MOVED: {cname} → {target_zone} (from {current_zone_name}, cost: {cost} zone(s))"]
    if terrain:
        lines.append(f"  Terrain: {', '.join(terrain)}")

    # Auto-recalc derived stats after terrain modifier change
    from rules_engine import try_rules_calc
    recalc = try_rules_calc(db, character_id)
    if recalc:
        lines.append(recalc)

    return "\n".join(lines)


def advance_turn(db, session_id: int, combat_cfg: dict | None = None) -> str:
    """Advance to the next character in initiative order.

    Automatically calls end_turn on the character whose turn just ended
    (ticks modifier durations, removes expired modifiers, recalcs stats).
    Wraps around at end of initiative, incrementing the round counter.
    """
    enc_id, rnd, init_json, current_turn = _require_active_encounter(db, session_id)
    init_order = json.loads(init_json)
    cfg = combat_cfg or {}
    zone_scale = cfg.get("zone_scale", 1)

    if not init_order:
        raise LoreKitError("Initiative order is empty")

    lines = []

    # Auto end_turn on the character whose turn just ended
    ending_char_id = init_order[current_turn]
    system_path = _resolve_system_path(db, session_id)
    if system_path:
        from combat_engine import end_turn as _end_turn
        end_result = _end_turn(db, ending_char_id, system_path)
        lines.append(end_result)
        lines.append("")

    # Advance
    next_turn = current_turn + 1
    new_round = rnd
    if next_turn >= len(init_order):
        next_turn = 0
        new_round = rnd + 1

    db.execute(
        "UPDATE encounter_state SET current_turn = ?, round = ? WHERE id = ?",
        (next_turn, new_round, enc_id),
    )
    db.commit()

    char_id = init_order[next_turn]
    cname = _char_name(db, char_id)

    lines.append(f"TURN: Round {new_round}, {cname} (character {char_id})")

    # Position info
    zid = _get_character_zone(db, enc_id, char_id)
    if zid is not None:
        zname = _zone_id_to_name(db, zid)
        ztags = _get_zone_tags(db, zid)
        tag_str = f" [{', '.join(ztags)}]" if ztags else ""
        lines.append(f"Position: {zname}{tag_str}")

        # Allies and enemies in zone
        all_in_zone = db.execute(
            "SELECT character_id FROM character_zone WHERE encounter_id = ? AND zone_id = ?",
            (enc_id, zid),
        ).fetchall()
        others = [r[0] for r in all_in_zone if r[0] != char_id]
        if others:
            names = [_char_name(db, c) for c in others]
            lines.append(f"Others in zone: {', '.join(names)}")
        else:
            lines.append("Others in zone: none")

        # Nearest character in a different zone
        adj = _build_adjacency(db, enc_id)
        all_chars = db.execute(
            "SELECT character_id, zone_id FROM character_zone WHERE encounter_id = ?",
            (enc_id,),
        ).fetchall()
        nearest_dist = None
        nearest_name = None
        nearest_zone = None
        for other_cid, other_zid in all_chars:
            if other_cid == char_id or other_zid == zid:
                continue
            d = _shortest_path(adj, zid, other_zid)
            if d is not None and (nearest_dist is None or d < nearest_dist):
                nearest_dist = d
                nearest_name = _char_name(db, other_cid)
                nearest_zone = _zone_id_to_name(db, other_zid)

        if nearest_dist is not None:
            if zone_scale > 1:
                movement_unit = cfg.get("movement_unit", "ft")
                lines.append(
                    f"Nearest other: {nearest_name}, {nearest_dist} zone(s) "
                    f"({nearest_dist * zone_scale}{movement_unit}) in {nearest_zone}"
                )
            else:
                lines.append(
                    f"Nearest other: {nearest_name}, {nearest_dist} zone(s) in {nearest_zone}"
                )

    return "\n".join(lines)


def end_encounter(db, session_id: int) -> str:
    """End the active encounter. Removes zones, positions, and encounter-duration modifiers."""
    enc_id, rnd, _, _ = _require_active_encounter(db, session_id)

    # Get all characters in the encounter for modifier cleanup
    char_ids = [
        r[0] for r in db.execute(
            "SELECT character_id FROM character_zone WHERE encounter_id = ?",
            (enc_id,),
        ).fetchall()
    ]

    # Get zone names for terrain modifier cleanup
    zone_rows = db.execute(
        "SELECT id, name FROM encounter_zones WHERE encounter_id = ?",
        (enc_id,),
    ).fetchall()

    # Remove terrain modifiers for each character
    terrain_removed = 0
    for cid in char_ids:
        for _, zname in zone_rows:
            terrain_removed += _remove_zone_terrain(db, cid, zname)

    # Remove encounter-duration combat_state modifiers
    encounter_removed = 0
    for cid in char_ids:
        encounter_removed += db.execute(
            "DELETE FROM combat_state WHERE character_id = ? "
            "AND duration_type IN ('encounter', 'rounds', 'concentration')",
            (cid,),
        ).rowcount

    # Clean up zone data
    zone_ids = [r[0] for r in zone_rows]
    if zone_ids:
        ph = ",".join("?" * len(zone_ids))
        db.execute(f"DELETE FROM zone_adjacency WHERE zone_a IN ({ph})", zone_ids)
    db.execute("DELETE FROM character_zone WHERE encounter_id = ?", (enc_id,))
    db.execute("DELETE FROM encounter_zones WHERE encounter_id = ?", (enc_id,))

    # Mark encounter as ended
    db.execute(
        "UPDATE encounter_state SET status = 'ended' WHERE id = ?",
        (enc_id,),
    )
    db.commit()

    parts = []
    if terrain_removed:
        parts.append(f"{terrain_removed} terrain modifier(s)")
    if encounter_removed:
        parts.append(f"{encounter_removed} combat modifier(s)")
    cleanup = f" Cleared: {', '.join(parts)}." if parts else ""

    # Auto-recalc derived stats for all participants after modifier cleanup
    recalc_lines = []
    if terrain_removed or encounter_removed:
        from rules_engine import try_rules_calc
        for cid in char_ids:
            recalc = try_rules_calc(db, cid)
            if recalc:
                recalc_lines.append(recalc)

    result = f"ENCOUNTER ENDED (session {session_id}, {rnd} rounds).{cleanup}"
    if recalc_lines:
        result += "\n" + "\n".join(recalc_lines)
    return result


def update_zone_tags(
    db, encounter_id: int, zone_name: str, tags: list[str],
    combat_cfg: dict | None = None,
) -> str:
    """Modify zone tags mid-combat and update terrain modifiers for characters in the zone."""
    cfg = combat_cfg or {}
    zone_id = _zone_name_to_id(db, encounter_id, zone_name)

    old_tags = _get_zone_tags(db, zone_id)

    # Update tags
    db.execute(
        "UPDATE encounter_zones SET tags = ? WHERE id = ?",
        (json.dumps(tags), zone_id),
    )

    # Get characters in this zone
    chars_in_zone = db.execute(
        "SELECT character_id FROM character_zone WHERE encounter_id = ? AND zone_id = ?",
        (encounter_id, zone_id),
    ).fetchall()

    # Remove old terrain modifiers and apply new ones
    modifier_changes = []
    for (cid,) in chars_in_zone:
        removed = _remove_zone_terrain(db, cid, zone_name)
        applied = _apply_zone_terrain(db, cid, zone_id, zone_name, cfg)
        cname = _char_name(db, cid)
        if removed or applied:
            modifier_changes.append(f"  {cname}: {', '.join(applied) if applied else 'modifiers removed'}")

    db.commit()

    lines = [f"ZONE UPDATED: {zone_name}"]
    lines.append(f"  Tags: {old_tags} → {tags}")
    lines.extend(modifier_changes)

    # Auto-recalc derived stats for all characters in the zone
    from rules_engine import try_rules_calc
    for (cid,) in chars_in_zone:
        recalc = try_rules_calc(db, cid)
        if recalc:
            lines.append(recalc)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Range validation (for rules_resolve integration)
# ---------------------------------------------------------------------------

def get_area_targets(db, encounter_id: int, center_zone_id: int,
                     radius: int, exclude_ids: set[int] | None = None) -> list[int]:
    """Return character_ids in all zones within `radius` hops of center.

    Uses BFS on the zone adjacency graph to collect zones, then queries
    character_zone for all characters in those zones minus exclude_ids.
    """
    adj = _build_adjacency(db, encounter_id)

    # BFS to collect zones within radius hops
    visited: set[int] = {center_zone_id}
    frontier = [center_zone_id]
    for _ in range(radius):
        next_frontier = []
        for zid in frontier:
            for neighbor, _weight in adj.get(zid, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    # Query characters in those zones
    ph = ",".join("?" * len(visited))
    rows = db.execute(
        f"SELECT character_id FROM character_zone "
        f"WHERE encounter_id = ? AND zone_id IN ({ph})",
        [encounter_id, *visited],
    ).fetchall()

    exclude = exclude_ids or set()
    return [r[0] for r in rows if r[0] not in exclude]


def check_range(
    db, encounter_id: int, attacker_id: int, defender_id: int,
    action_type: str, weapon_range: int | None, combat_cfg: dict,
) -> str | None:
    """Check if attacker can reach defender for the given action type.

    Returns None if in range, or an error message string if out of range.
    """
    zone_scale = combat_cfg.get("zone_scale", 1)
    melee_range = combat_cfg.get("melee_range", 0)
    movement_unit = combat_cfg.get("movement_unit", "ft")

    atk_zid = _get_character_zone(db, encounter_id, attacker_id)
    def_zid = _get_character_zone(db, encounter_id, defender_id)

    # If either character isn't placed, skip range validation
    if atk_zid is None or def_zid is None:
        return None

    dist = _zone_distance(db, encounter_id, atk_zid, def_zid)
    if dist is None:
        return (
            f"Target out of range. {_char_name(db, defender_id)} is unreachable "
            f"from {_zone_id_to_name(db, atk_zid)}."
        )

    if action_type == "melee":
        if dist > melee_range:
            def_zone = _zone_id_to_name(db, def_zid)
            if zone_scale > 1:
                return (
                    f"Target out of range. {_char_name(db, defender_id)} is in "
                    f"{def_zone} ({dist} zone(s) away, {dist * zone_scale}{movement_unit}). "
                    f"Melee requires same zone."
                )
            else:
                return (
                    f"Target out of range. {_char_name(db, defender_id)} is in "
                    f"{def_zone} ({dist} zone(s) away). Melee requires same zone."
                )

    elif action_type == "ranged" and weapon_range is not None:
        actual_distance = dist * zone_scale
        if actual_distance > weapon_range:
            def_zone = _zone_id_to_name(db, def_zid)
            return (
                f"Target out of range. {_char_name(db, defender_id)} is in "
                f"{def_zone} ({dist} zone(s) away, {actual_distance}{movement_unit}). "
                f"Weapon range: {weapon_range}{movement_unit}."
            )

    return None


def force_move(
    db, encounter_id: int, attacker_id: int, target_id: int,
    push_zones: int, combat_cfg: dict,
) -> str | None:
    """Force-move a target away from the attacker by push_zones hops.

    Finds the neighbor of target's current zone that is farthest from the
    attacker's zone, then repeats for each hop.  If the target is at a
    boundary (no further zones away from attacker), movement stops early.

    Returns a description of the movement, or None if no movement occurred.
    """
    if push_zones <= 0:
        return None

    atk_zid = _get_character_zone(db, encounter_id, attacker_id)
    cur_zid = _get_character_zone(db, encounter_id, target_id)
    if atk_zid is None or cur_zid is None:
        return None

    adj = _build_adjacency(db, encounter_id)
    start_zid = cur_zid
    moved = 0

    for _ in range(push_zones):
        neighbors = adj.get(cur_zid, [])
        if not neighbors:
            break

        # Pick the neighbor that maximizes distance from attacker
        best_zid = None
        best_dist = -1
        for nid, _w in neighbors:
            d = _shortest_path(adj, atk_zid, nid)
            if d is not None and d > best_dist:
                best_dist = d
                best_zid = nid

        # Also check current distance from attacker
        cur_dist = _shortest_path(adj, atk_zid, cur_zid)
        if best_zid is None or best_dist <= (cur_dist or 0):
            break  # No zone farther away — boundary

        cur_zid = best_zid
        moved += 1

    if moved == 0:
        return None

    # Perform the actual zone transition
    start_name = _zone_id_to_name(db, start_zid)
    end_name = _zone_id_to_name(db, cur_zid)
    target_name = _char_name(db, target_id)

    _remove_zone_terrain(db, target_id, start_name)
    db.execute(
        "UPDATE character_zone SET zone_id = ? WHERE encounter_id = ? AND character_id = ?",
        (cur_zid, encounter_id, target_id),
    )
    terrain = _apply_zone_terrain(db, target_id, cur_zid, end_name, combat_cfg)
    db.commit()

    parts = [f"FORCED MOVEMENT: {target_name} pushed {start_name} → {end_name} ({moved} zone(s))"]
    if terrain:
        parts.append(f"  Terrain: {', '.join(terrain)}")
    return "\n".join(parts)
