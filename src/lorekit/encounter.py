"""encounter.py — Zone-based combat positioning and encounter state.

Manages encounter lifecycle (start, status, advance turn, end) and
zone-based positioning (movement validation, range checks, terrain
modifiers). Zone graph uses weighted adjacency with Dijkstra shortest
path for distance calculations.

All system-specific values (zone_scale, terrain effects, movement
formulas) come from the system pack's `combat` section. The module
is domain-agnostic — it knows nothing about what zones or tags mean.
"""

from __future__ import annotations

import heapq
import json

from lorekit.db import LoreKitError


def _resolve_system_path(db, session_id: int) -> str | None:
    """Resolve the system pack directory from session metadata.

    Returns the full path, or None if no rules_system is configured.
    """
    from lorekit.queries import get_session_meta
    from lorekit.rules import resolve_system_path

    system_name = get_session_meta(db, session_id, "rules_system")
    if system_name is None:
        return None
    return resolve_system_path(system_name)


def _load_encounter_end_cfg(pack_dir: str | None) -> dict:
    """Load encounter_end config from system.json.

    Returns the encounter_end section, or an empty dict if not configured.
    """
    if not pack_dir:
        return {}
    import os

    system_json_path = os.path.join(pack_dir, "system.json")
    try:
        with open(system_json_path) as f:
            system_data = json.load(f)
        return system_data.get("encounter_end", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _reset_encounter_attributes(db, char_ids: list[int], reset_attrs: list[dict], pack_dir: str | None) -> list[str]:
    """Process reset_attributes from encounter_end config.

    Dispatches on the 'action' field:
    - reset_to_base: set value = key for all rows in the category
    - switch_to_base: call switch_alternate() to atomically reset arrays
      (handles action_override cleanup that a plain value reset cannot)
    - delete: remove all rows in the category
    - (with 'value'): set a specific key to a fixed value

    Returns summary lines for the combat report.
    """
    lines = []
    for ra in reset_attrs:
        cat = ra.get("category", "")
        action = ra.get("action", "")

        if action == "reset_to_base":
            for cid in char_ids:
                db.execute(
                    "UPDATE character_attributes SET value = key WHERE character_id = ? AND category = ?",
                    (cid, cat),
                )
        elif action == "switch_to_base":
            lines.extend(_switch_to_base(db, char_ids, cat, pack_dir))
        elif action == "delete":
            for cid in char_ids:
                db.execute(
                    "DELETE FROM character_attributes WHERE character_id = ? AND category = ?",
                    (cid, cat),
                )
        elif "value" in ra:
            key = ra.get("key", "")
            val = str(ra["value"])
            from lorekit.queries import upsert_attribute

            for cid in char_ids:
                upsert_attribute(db, cid, cat, key, val)
    return lines


def _switch_to_base(db, char_ids: list[int], category: str, pack_dir: str | None) -> list[str]:
    """Switch tracked alternates back to base via switch_alternate().

    Reads rows from the given category (key = group name, value = current
    selection) and calls switch_alternate(value → key) for each that is
    not already at base. This atomically handles action_override cleanup
    that a plain value reset cannot.

    Returns summary lines for the combat report.
    """
    if not pack_dir:
        return []

    from lorekit.combat.powers import switch_alternate

    lines = []
    for cid in char_ids:
        rows = db.execute(
            "SELECT key, value FROM character_attributes WHERE character_id = ? AND category = ?",
            (cid, category),
        ).fetchall()
        for group_name, current in rows:
            if current == group_name:
                continue
            try:
                switch_alternate(db, cid, group_name, group_name, pack_dir, _bypass_limit=True)
                char_name = _char_name(db, cid)
                lines.append(f"  {char_name}: {group_name} reset to base")
            except Exception:
                pass  # best-effort — don't fail encounter end
    return lines


# ---------------------------------------------------------------------------
# Zone graph — shortest path
# ---------------------------------------------------------------------------


def _build_adjacency(db, encounter_id: int) -> dict[int, list[tuple[int, int]]]:
    """Build adjacency list from zone_adjacency rows.

    Returns {zone_id: [(neighbor_id, weight), ...]} with bidirectional edges.
    """
    zone_ids = [
        r[0]
        for r in db.execute(
            "SELECT id FROM encounter_zones WHERE encounter_id = ?",
            (encounter_id,),
        ).fetchall()
    ]
    adj: dict[int, list[tuple[int, int]]] = {z: [] for z in zone_ids}

    if not zone_ids:
        return adj

    ph = ",".join("?" * len(zone_ids))
    rows = db.execute(
        f"SELECT zone_a, zone_b, weight FROM zone_adjacency WHERE zone_a IN ({ph})",
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


def _movement_cost(db, adj: dict[int, list[tuple[int, int]]], start: int, end: int, combat_cfg: dict) -> int | None:
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


def _apply_zone_terrain(db, character_id: int, zone_id: int, zone_name: str, combat_cfg: dict) -> list[str]:
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


def _load_encounter_template(
    session_id: int, template_name: str, pack_dir: str | None
) -> tuple[list[dict], list[dict] | None]:
    """Load zones and adjacency from a system pack encounter template.

    Returns (zones, adjacency) or raises LoreKitError if template not found.
    """
    import os

    if not pack_dir:
        raise LoreKitError("Templates require a system pack (rules_system)")

    system_json_path = os.path.join(pack_dir, "system.json")
    if not os.path.isfile(system_json_path):
        raise LoreKitError(f"System pack not found: {pack_dir}")

    with open(system_json_path) as f:
        data = json.load(f)

    templates = data.get("encounter_templates", {})
    if not templates:
        raise LoreKitError("No encounter_templates defined in system pack")

    tmpl = templates.get(template_name)
    if tmpl is None:
        available = ", ".join(templates.keys())
        raise LoreKitError(f"Unknown template '{template_name}'. Available: {available}")

    zones = tmpl.get("zones", [])
    if not zones:
        raise LoreKitError(f"Template '{template_name}' has no zones")

    # Convert adjacency from compact [A, B, weight] to [{"from": A, "to": B, "weight": W}]
    raw_adj = tmpl.get("adjacency")
    adjacency = None
    if raw_adj:
        adjacency = [{"from": edge[0], "to": edge[1], "weight": edge[2] if len(edge) > 2 else 1} for edge in raw_adj]

    return zones, adjacency


def start_encounter(
    db,
    session_id: int,
    zones: list[dict] | None = None,
    initiative: list[dict] | str = "auto",
    adjacency: list[dict] | None = None,
    placements: list[dict] | None = None,
    combat_cfg: dict | None = None,
    template: str = "",
    pack_dir: str | None = None,
) -> str:
    """Start a combat encounter with zones, initiative, and optional placements.

    Parameters:
    - zones: [{"name": "...", "tags": ["cover", ...]}, ...] or None if using template
    - initiative: [{"character_id": N, "roll": M}, ...] or "auto"
      When "auto", rolls d20 + initiative_stat for each placed character.
    - adjacency: [{"from": "A", "to": "B", "weight": 1}, ...] or None for linear chain
    - placements: [{"character_id": N, "zone": "name"}, ...] or None
    - combat_cfg: system pack's combat section (for terrain modifiers)
    - template: encounter template name from system pack (loads zones + adjacency)
    - pack_dir: system pack directory (needed for template resolution)
    """
    # Resolve template if specified
    if template:
        tmpl_zones, tmpl_adj = _load_encounter_template(session_id, template, pack_dir)
        if zones is None:
            zones = tmpl_zones
            # Only use template adjacency when using template zones
            if adjacency is None and tmpl_adj is not None:
                adjacency = tmpl_adj

    # Check no active encounter already
    existing = _get_active_encounter(db, session_id)
    if existing is not None:
        raise LoreKitError("An encounter is already active in this session. End it first.")

    if not zones:
        raise LoreKitError("At least one zone is required")

    cfg = combat_cfg or {}

    # Auto-roll initiative if requested
    if initiative == "auto":
        if not placements:
            raise LoreKitError("initiative='auto' requires placements to know which characters to roll for")
        init_stat = cfg.get("initiative_stat")
        if not init_stat:
            raise LoreKitError("initiative='auto' requires combat.initiative_stat in system pack")

        from random import random

        from cruncher.dice import roll_expr

        initiative = []
        for p in placements:
            cid = p["character_id"]
            # Read derived stat
            row = db.execute(
                "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'derived' AND key = ?",
                (cid, init_stat),
            ).fetchone()
            bonus = int(row[0]) if row else 0
            roll_result = roll_expr("d20")
            roll_val = roll_result["total"]
            # Add tiny random tiebreaker (0-0.99) so ties resolve randomly
            initiative.append(
                {
                    "character_id": cid,
                    "roll": roll_val + bonus,
                    "_tiebreak": random(),
                    "_detail": f"d20({roll_val}) + {bonus}",
                }
            )

    # Sort initiative descending (with tiebreaker if present)
    sorted_init = sorted(
        initiative,
        key=lambda x: (x["roll"], x.get("_tiebreak", 0)),
        reverse=True,
    )
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
                raise LoreKitError(f"Adjacency references unknown zone: {edge['from']} or {edge['to']}")
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
    terrain_lines = []
    if placements:
        for p in placements:
            cid = p["character_id"]
            zone_name = p["zone"]
            zid = zone_id_map.get(zone_name)
            if zid is None:
                raise LoreKitError(f"Placement references unknown zone: {zone_name}")
            team = p.get("team", "")
            db.execute(
                "INSERT INTO character_zone (encounter_id, character_id, zone_id, team) VALUES (?, ?, ?, ?)",
                (enc_id, cid, zid, team),
            )
            # Apply terrain modifiers
            mods = _apply_zone_terrain(db, cid, zid, zone_name, cfg)
            if mods:
                terrain_lines.append(f"  Terrain on {_char_name(db, cid)}: {', '.join(mods)}")

    db.commit()

    # Auto-recalc derived stats for placed characters with terrain modifiers
    if placements:
        from lorekit.rules import try_rules_calc

        for p in placements:
            recalc = try_rules_calc(db, p["character_id"])
            if recalc:
                terrain_lines.append(recalc)

    # Format output
    lines = [f"ENCOUNTER STARTED (session {session_id})"]
    lines.append("Round: 1")

    # Initiative display
    init_names = []
    for entry in sorted_init:
        cname = _char_name(db, entry["character_id"])
        detail = entry.get("_detail")
        if detail:
            init_names.append(f"{cname} ({detail} = {entry['roll']})")
        else:
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
    from lorekit.queries import get_character_name

    return get_character_name(db, character_id) or f"character {character_id}"


def _get_char_vital(db, cid: int, hud_cfg: dict) -> str:
    """Build vital stat string from HUD config (e.g. 'HP 45/62')."""
    vital = hud_cfg.get("vital_stat")
    if not vital:
        return ""
    current_key = vital.get("current")
    max_key = vital.get("max")
    label = vital.get("label", "")

    from lorekit.queries import get_attribute_by_key

    current_val = get_attribute_by_key(db, cid, current_key) if current_key else None
    max_val = get_attribute_by_key(db, cid, max_key) if max_key else None

    if current_val is None:
        return ""
    if max_val is not None:
        return f"{label} {current_val}/{max_val}" if label else f"{current_val}/{max_val}"
    return f"{label} {current_val}" if label else str(current_val)


def _get_char_modifiers_summary(db, cid: int) -> list[str]:
    """Get compact modifier summaries for a character."""
    rows = db.execute(
        "SELECT source, target_stat, value, duration_type, duration "
        "FROM combat_state WHERE character_id = ? ORDER BY created_at",
        (cid,),
    ).fetchall()
    parts = []
    for source, _stat, value, dur_type, duration in rows:
        dur_str = ""
        if dur_type == "rounds" and duration is not None:
            dur_str = f" {duration}r"
        parts.append(f"{source} {value:+d}{dur_str}")
    return parts


def _get_condition_reminders(db, cid: int, session_id: int) -> list[str]:
    """Return condition reminder lines for a character based on system pack rules.

    Checks both active combat_state modifiers and damage_condition thresholds
    from the system's on_failure table.
    """
    system_path = _resolve_system_path(db, session_id)
    if not system_path:
        return []

    import os

    sys_json = os.path.join(system_path, "system.json")
    if not os.path.isfile(sys_json):
        return []

    with open(sys_json) as f:
        sdata = json.load(f)
    condition_rules = sdata.get("combat", {}).get("condition_rules", {})
    if not condition_rules:
        return []

    cname = _char_name(db, cid)
    seen = set()
    reminders = []

    def _desc(cdef):
        return cdef.get("description") if isinstance(cdef, dict) else cdef

    def _gm_instr(cdef):
        return cdef.get("gm_instruction") if isinstance(cdef, dict) else None

    # Check active modifier sources
    sources = db.execute(
        "SELECT DISTINCT source, applied_by FROM combat_state WHERE character_id = ?",
        (cid,),
    ).fetchall()
    for source, applied_by in sources:
        if source in condition_rules and source not in seen:
            by_note = ""
            if applied_by:
                applier_name = _char_name(db, applied_by)
                if applier_name:
                    by_note = f" (by {applier_name})"
            desc = _desc(condition_rules[source])
            if desc:
                reminders.append(f"⚠ {cname} is {source}{by_note}: {desc}")
            gm_instr = _gm_instr(condition_rules[source])
            if gm_instr:
                reminders.append(f"   → {gm_instr}")
            seen.add(source)

    # Check attribute-based condition thresholds
    for thresh in sdata.get("combat", {}).get("condition_thresholds", []):
        attr_key = thresh.get("attribute")
        min_val = thresh.get("min")
        cond_name = thresh.get("condition")
        if not (attr_key and min_val is not None and cond_name):
            continue
        if cond_name in condition_rules and cond_name not in seen:
            from lorekit.queries import get_attribute_by_key

            val = get_attribute_by_key(db, cid, attr_key)
            if val is not None and float(val) >= min_val:
                desc = _desc(condition_rules[cond_name])
                if desc:
                    reminders.append(f"⚠ {cname} is {cond_name}: {desc}")
                gm_instr = _gm_instr(condition_rules[cond_name])
                if gm_instr:
                    reminders.append(f"   → {gm_instr}")
                seen.add(cond_name)

    return reminders


def get_status(db, session_id: int, combat_cfg: dict | None = None) -> str:
    """Return the current encounter state as a formatted HUD string.

    Shows zone-grouped layout with per-character vital stats and active
    modifiers. Falls back to basic output when HUD config is absent.
    """
    enc_id, rnd, init_json, current_turn = _require_active_encounter(db, session_id)
    init_order = json.loads(init_json)
    cfg = combat_cfg or {}
    zone_scale = cfg.get("zone_scale", 1)
    movement_unit = cfg.get("movement_unit", "zone")
    hud_cfg = cfg.get("hud", {})

    # Current turn character
    current_char_id = init_order[current_turn] if init_order else None
    current_name = _char_name(db, current_char_id) if current_char_id else "none"

    lines = [f"Round {rnd} — Turn: {current_name}"]
    lines.append("")

    # Initiative (including delayed characters)
    init_names = [_char_name(db, cid) for cid in init_order]
    lines.append(f"Initiative: {', '.join(init_names)}")

    # Show delayed characters not in initiative
    delayed_rows = db.execute(
        "SELECT ca.character_id FROM character_attributes ca "
        "JOIN character_zone cz ON ca.character_id = cz.character_id "
        "WHERE cz.encounter_id = ? AND ca.key = '_delayed' AND ca.value = '1'",
        (enc_id,),
    ).fetchall()
    if delayed_rows:
        delayed_names = [_char_name(db, r[0]) for r in delayed_rows]
        lines.append(f"Delayed: {', '.join(delayed_names)}")

    lines.append("")

    # Zone-grouped positions with HUD
    zones_rows = db.execute(
        "SELECT id, name, tags FROM encounter_zones WHERE encounter_id = ? ORDER BY id",
        (enc_id,),
    ).fetchall()
    zone_map = {r[0]: (r[1], json.loads(r[2])) for r in zones_rows}
    zone_order = [r[0] for r in zones_rows]

    char_zones = db.execute(
        "SELECT character_id, zone_id FROM character_zone WHERE encounter_id = ?",
        (enc_id,),
    ).fetchall()

    # Group characters by zone
    zone_chars: dict[int, list[int]] = {zid: [] for zid in zone_order}
    char_zone_map: dict[int, int] = {}
    for cid, zid in char_zones:
        zone_chars.setdefault(zid, []).append(cid)
        char_zone_map[cid] = zid

    # Build zone blocks
    adj = _build_adjacency(db, enc_id) if len(zones_rows) > 1 else {}
    prev_zid = None
    for zid in zone_order:
        zname, ztags = zone_map[zid]
        tag_str = f" [{', '.join(ztags)}]" if ztags else ""

        # Zone separator with distance
        if prev_zid is not None and adj:
            dist = _shortest_path(adj, prev_zid, zid)
            if dist is not None:
                if zone_scale > 1:
                    lines.append(f"       ↕ {dist} zone(s) ({dist * zone_scale}{movement_unit})")
                else:
                    lines.append(f"       ↕ {dist} zone(s)")

        header = f"┌─ {zname}{tag_str} "
        lines.append(f"{header}{'─' * max(1, 48 - len(header))}┐")

        chars_in_zone = zone_chars.get(zid, [])
        if chars_in_zone:
            for cid in chars_in_zone:
                cname = _char_name(db, cid)
                # Get character type
                type_row = db.execute(
                    "SELECT type FROM characters WHERE id = ?",
                    (cid,),
                ).fetchone()
                ctype = f" ({type_row[0].upper()})" if type_row else ""

                # Vital stat
                vital = _get_char_vital(db, cid, hud_cfg)
                vital_str = f"  {vital}" if vital else ""

                # Active modifiers
                mods = _get_char_modifiers_summary(db, cid)
                mod_str = f"  [{', '.join(mods)}]" if mods else ""

                # Marker for current turn
                marker = " ►" if cid == current_char_id else ""

                lines.append(f"│  {cname}{ctype}{vital_str}{mod_str}{marker}")
        else:
            lines.append("│  (empty)")

        lines.append(f"└{'─' * 48}┘")
        prev_zid = zid

    # Condition reminders for current turn character
    if current_char_id:
        cond_reminders = _get_condition_reminders(db, current_char_id, session_id)
        if cond_reminders:
            lines.append("")
            lines.extend(cond_reminders)

    return "\n".join(lines)


def move_character(
    db,
    encounter_id: int,
    character_id: int,
    target_zone: str,
    combat_cfg: dict | None = None,
    movement_budget: int | None = None,
    skip_adjacency: bool = False,
) -> str:
    """Move a character to a different zone with validation.

    Parameters:
    - movement_budget: max zones the character can traverse (from derived stat
      or system default). If None, movement is unrestricted.
    - combat_cfg: system pack's combat section (for terrain costs)
    - skip_adjacency: bypass adjacency/path validation (e.g. teleport).
      Still validates target zone exists and condition-based movement restrictions.
    """
    cfg = combat_cfg or {}
    zone_scale = cfg.get("zone_scale", 1)
    movement_unit = cfg.get("movement_unit", "zone")

    # Check if active conditions prevent movement (e.g. immobile, grab → max_move: 0)
    condition_rules = cfg.get("condition_rules", {})
    if condition_rules:
        from lorekit.combat.conditions import expand_conditions, get_active_conditions

        thresholds = cfg.get("condition_thresholds")
        combined = cfg.get("combined_conditions", {})
        active = get_active_conditions(db, character_id, condition_rules, thresholds)
        expanded, _ = expand_conditions(active, condition_rules, combined)
        for cond_name in expanded:
            cdef = condition_rules.get(cond_name, {})
            if isinstance(cdef, dict) and cdef.get("max_move") == 0:
                cname = _char_name(db, character_id)
                raise LoreKitError(f"Cannot move: {cname} is {cond_name} (max_move: 0)")

    # Resolve target zone
    target_zid = _zone_name_to_id(db, encounter_id, target_zone)

    # Get current zone
    current_zid = _get_character_zone(db, encounter_id, character_id)
    if current_zid is None:
        raise LoreKitError(f"Character {_char_name(db, character_id)} is not placed in the encounter")

    if current_zid == target_zid:
        return f"{_char_name(db, character_id)} is already in {target_zone}"

    current_zone_name = _zone_id_to_name(db, current_zid)

    if skip_adjacency:
        cost = 0
    else:
        # Validate movement cost
        adj = _build_adjacency(db, encounter_id)
        cost = _movement_cost(db, adj, current_zid, target_zid, cfg)

        if cost is None:
            raise LoreKitError(f"Cannot reach {target_zone} from {current_zone_name} — no path exists")

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
    from lorekit.rules import try_rules_calc

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
        from lorekit.combat.turns import end_turn as _end_turn

        end_result = _end_turn(db, ending_char_id, system_path)
        lines.append(end_result)
        lines.append("")

    # Reset per-turn counters for the ending character
    db.execute(
        "DELETE FROM character_attributes WHERE character_id = ? AND key IN ('_actions_this_turn', '_switches_this_turn')",
        (ending_char_id,),
    )
    db.commit()

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

    # Auto-skip characters that cannot act (incapacitated, stunned, etc.)
    if system_path:
        from cruncher.system_pack import load_system_pack as _load_pack
        from lorekit.combat.conditions import is_incapacitated

        _pack = _load_pack(system_path)
        incap, cond_name = is_incapacitated(db, char_id, _pack)
        if incap:
            lines.append(f"SKIP: {cname} is {cond_name} — cannot act")
            # Recurse to advance to the next character
            db.execute(
                "UPDATE encounter_state SET current_turn = ?, round = ? WHERE id = ?",
                (next_turn, new_round, enc_id),
            )
            db.commit()
            return "\n".join(lines) + "\n\n" + advance_turn(db, session_id, combat_cfg=combat_cfg)

    # Start-of-turn processing for the character whose turn is beginning
    if system_path:
        from lorekit.combat.turns import start_turn as _start_turn

        start_result = _start_turn(db, char_id, system_path)
        if start_result:
            lines.append(start_result)
            lines.append("")

    # Remind GM to save before yielding to the player
    char_type = db.execute("SELECT type FROM characters WHERE id = ?", (char_id,)).fetchone()
    is_pc = char_type and char_type[0] == "pc"

    lines.append(f"TURN: Round {new_round}, {cname} (character {char_id})")

    if is_pc:
        lines.append("⚠ PC TURN — call turn_save with narration before player acts")

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
                lines.append(f"Nearest other: {nearest_name}, {nearest_dist} zone(s) in {nearest_zone}")

    # Condition reminders for the character whose turn is starting
    cond_reminders = _get_condition_reminders(db, char_id, session_id)
    if cond_reminders:
        lines.extend(cond_reminders)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ready / Delay actions
# ---------------------------------------------------------------------------


def ready_action(
    db,
    session_id: int,
    character_id: int,
    action: str,
    trigger: str,
    targets: str = "",
    pack_dir: str | None = None,
) -> str:
    """Declare a readied action and end the character's turn.

    The character gives up their turn to hold a specified action until a
    trigger condition occurs. The GM calls execute_ready when the trigger
    fires during another character's turn.

    The readied action is stored as a combat_state row with
    duration_type='readied' and cleaned up at the start of the character's
    next turn if unused.

    Reads ready_delay config from the system pack's combat section (if set)
    for action_cost validation. Without config, readying is always allowed.
    """
    enc_id, rnd, init_json, current_turn = _require_active_encounter(db, session_id)
    init_order = json.loads(init_json)

    if character_id not in init_order:
        raise LoreKitError(f"Character {character_id} is not in this encounter")

    # Must be this character's turn
    if init_order[current_turn] != character_id:
        current_name = _char_name(db, init_order[current_turn])
        raise LoreKitError(f"Not this character's turn (current: {current_name})")

    char_name = _char_name(db, character_id)

    # Store the readied action
    metadata = json.dumps(
        {
            "action": action,
            "targets": targets,
            "trigger": trigger,
        }
    )
    db.execute(
        "INSERT INTO combat_state "
        "(character_id, source, target_stat, modifier_type, value, "
        "duration_type, metadata, created_at) "
        "VALUES (?, ?, '_readied', 'deferred', 0, 'readied', ?, datetime('now')) "
        "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET "
        "metadata = excluded.metadata",
        (character_id, f"readied:{action}", metadata),
    )
    db.commit()

    lines = [
        f"READY: {char_name} readies {action}",
        f"  Trigger: {trigger}",
    ]
    if targets:
        lines.append(f"  Target: {targets}")
    lines.append("  (use encounter_execute_ready when trigger fires)")

    return "\n".join(lines)


def execute_ready(
    db,
    session_id: int,
    character_id: int,
    pack_dir: str | None = None,
) -> str:
    """Fire a character's readied action.

    Called by the GM when the trigger condition occurs during another
    character's turn. Resolves the readied action as a free action,
    then removes the readied combat_state row.
    """
    _require_active_encounter(db, session_id)

    char_name = _char_name(db, character_id)

    # Find the readied action
    row = db.execute(
        "SELECT id, source, metadata FROM combat_state WHERE character_id = ? AND duration_type = 'readied' LIMIT 1",
        (character_id,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"{char_name} has no readied action")

    row_id, source, meta_json = row
    meta = json.loads(meta_json)
    action = meta.get("action", "")
    targets_str = meta.get("targets", "")

    if not action:
        raise LoreKitError(f"{char_name}'s readied action has no action defined")

    # Resolve target
    target_id = None
    if targets_str:
        # Try to resolve by name
        target_row = db.execute(
            "SELECT id FROM characters WHERE session_id = ? AND name = ?",
            (session_id, targets_str),
        ).fetchone()
        if target_row:
            target_id = target_row[0]
        else:
            # Try as numeric ID
            try:
                target_id = int(targets_str)
            except ValueError:
                raise LoreKitError(f"Cannot resolve target '{targets_str}' for readied action")

    # Consume the readied row before resolution
    db.execute("DELETE FROM combat_state WHERE id = ?", (row_id,))
    db.commit()

    lines = [f"READIED ACTION: {char_name} fires {action}"]

    # Resolve the action
    if target_id and pack_dir:
        from lorekit.combat.resolve import resolve_action

        result = resolve_action(
            db,
            character_id,
            target_id,
            action,
            pack_dir,
            options={"free_action": True},
        )
        lines.append(result)
    else:
        lines.append("  (no target or system pack — GM resolves manually)")

    return "\n".join(lines)


def delay_turn(db, session_id: int, character_id: int) -> str:
    """Delay the current character's turn.

    Removes the character from initiative order temporarily and starts
    the next character's turn. The character can re-enter initiative
    later via undelay. Their zone position is preserved.

    Unlike advance_turn, this does NOT call end_turn on the delaying
    character (they didn't act) or on the next character (they haven't
    started). It only runs start_turn on the next character.
    """
    enc_id, rnd, init_json, current_turn = _require_active_encounter(db, session_id)
    init_order = json.loads(init_json)

    if character_id not in init_order:
        raise LoreKitError(f"Character {character_id} is not in this encounter")

    # Must be this character's turn
    if init_order[current_turn] != character_id:
        current_name = _char_name(db, init_order[current_turn])
        raise LoreKitError(f"Not this character's turn (current: {current_name})")

    char_name = _char_name(db, character_id)

    # Mark as delayed
    from lorekit.queries import upsert_attribute

    upsert_attribute(db, character_id, "internal", "_delayed", "1")

    # Remove from initiative order
    char_index = init_order.index(character_id)
    init_order.remove(character_id)

    if not init_order:
        raise LoreKitError("Cannot delay — only character in initiative")

    # After removal, current_turn points to the next character.
    # Handle round wrap if the delayed character was last in order.
    new_turn = current_turn
    new_round = rnd
    if new_turn >= len(init_order):
        new_turn = 0
        new_round = rnd + 1

    db.execute(
        "UPDATE encounter_state SET initiative_order = ?, current_turn = ?, round = ? WHERE id = ?",
        (json.dumps(init_order), new_turn, new_round, enc_id),
    )
    db.commit()

    # Start the next character's turn
    next_char_id = init_order[new_turn]
    next_name = _char_name(db, next_char_id)
    lines = [
        f"DELAY: {char_name} delays their turn",
        f"TURN: Round {new_round}, {next_name} (character {next_char_id})",
    ]

    system_path = _resolve_system_path(db, session_id)
    if system_path:
        from lorekit.combat.turns import start_turn as _start_turn

        start_result = _start_turn(db, next_char_id, system_path)
        if start_result:
            lines.append(start_result)

    char_type = db.execute("SELECT type FROM characters WHERE id = ?", (next_char_id,)).fetchone()
    if char_type and char_type[0] == "pc":
        lines.append("⚠ PC TURN — call turn_save with narration before player acts")

    return "\n".join(lines)


def undelay(db, session_id: int, character_id: int, combat_cfg: dict | None = None) -> str:
    """Insert a delayed character back into initiative and start their turn.

    The character is inserted just before the current character in
    initiative order. Their new position persists for subsequent rounds.
    """
    enc_id, rnd, init_json, current_turn = _require_active_encounter(db, session_id)
    init_order = json.loads(init_json)

    char_name = _char_name(db, character_id)

    # Verify the character is actually delayed
    delayed_row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_delayed'",
        (character_id,),
    ).fetchone()
    if not delayed_row or delayed_row[0] != "1":
        raise LoreKitError(f"{char_name} is not delaying")

    if character_id in init_order:
        raise LoreKitError(f"{char_name} is already in initiative order")

    # Clear delayed marker
    db.execute(
        "DELETE FROM character_attributes WHERE character_id = ? AND key = '_delayed'",
        (character_id,),
    )

    # Insert just before the current character
    init_order.insert(current_turn, character_id)

    # current_turn now points to the delayed character (they act now),
    # and after advance_turn the original current character gets their turn
    db.execute(
        "UPDATE encounter_state SET initiative_order = ? WHERE id = ?",
        (json.dumps(init_order), enc_id),
    )
    db.commit()

    # Start-of-turn processing
    lines = [f"UNDELAY: {char_name} acts now (inserted before current turn)"]

    system_path = _resolve_system_path(db, session_id)
    if system_path:
        from lorekit.combat.turns import start_turn as _start_turn

        start_result = _start_turn(db, character_id, system_path)
        if start_result:
            lines.append(start_result)

    return "\n".join(lines)


def join_encounter(
    db,
    session_id: int,
    character_id: int,
    zone_name: str,
    team: str = "",
    initiative_roll: int = 0,
    combat_cfg: dict | None = None,
) -> str:
    """Add a character to an active encounter mid-combat.

    Inserts the character into the initiative order (sorted by roll),
    places them in the specified zone, and applies terrain modifiers.
    Used for summoned creatures, reinforcements, etc.
    """
    from lorekit.rules import try_rules_calc

    enc = _require_active_encounter(db, session_id)
    enc_id, current_round, init_order_json, current_turn = enc
    init_order = json.loads(init_order_json)

    if character_id in init_order:
        raise LoreKitError(f"Character {character_id} is already in this encounter")

    # Find the zone
    zone_row = db.execute(
        "SELECT id FROM encounter_zones WHERE encounter_id = ? AND name = ?",
        (enc_id, zone_name),
    ).fetchone()
    if not zone_row:
        available = [
            r[0] for r in db.execute("SELECT name FROM encounter_zones WHERE encounter_id = ?", (enc_id,)).fetchall()
        ]
        raise LoreKitError(f"Zone '{zone_name}' not found. Available: {', '.join(available)}")

    zone_id = zone_row[0]

    # Insert into character_zone
    db.execute(
        "INSERT INTO character_zone (encounter_id, character_id, zone_id, team) VALUES (?, ?, ?, ?)",
        (enc_id, character_id, zone_id, team),
    )

    # Insert into initiative order (after current turn position)
    insert_pos = current_turn + 1
    init_order.insert(insert_pos, character_id)
    db.execute(
        "UPDATE encounter_state SET initiative_order = ? WHERE id = ?",
        (json.dumps(init_order), enc_id),
    )

    db.commit()

    # Apply zone terrain modifiers
    if combat_cfg:
        _apply_zone_terrain(db, character_id, zone_id, zone_name, combat_cfg)
        db.commit()

    try_rules_calc(db, character_id)

    char_name = _char_name(db, character_id)
    return f"JOINED ENCOUNTER: {char_name} placed in {zone_name} (team: {team or 'none'})"


def leave_encounter(
    db,
    session_id: int,
    character_id: int,
    combat_cfg: dict | None = None,
    pack_dir: str | None = None,
) -> str:
    """Remove a character from an active encounter.

    Removes from initiative order, clears zone placement, removes
    encounter-duration combat modifiers and terrain modifiers.
    If it's the character's turn, auto-advances.
    """
    from lorekit.rules import try_rules_calc

    enc = _require_active_encounter(db, session_id)
    enc_id, current_round, init_order_json, current_turn = enc
    init_order = json.loads(init_order_json)

    if character_id not in init_order:
        raise LoreKitError(f"Character {character_id} is not in this encounter")

    char_name = _char_name(db, character_id)

    # Check if it's this character's turn
    is_current = init_order[current_turn] == character_id
    char_index = init_order.index(character_id)

    # Remove zone terrain modifiers
    zone_row = db.execute(
        "SELECT ez.name FROM character_zone cz "
        "JOIN encounter_zones ez ON cz.zone_id = ez.id "
        "WHERE cz.encounter_id = ? AND cz.character_id = ?",
        (enc_id, character_id),
    ).fetchone()
    if zone_row:
        _remove_zone_terrain(db, character_id, zone_row[0])

    # Remove from character_zone
    db.execute(
        "DELETE FROM character_zone WHERE encounter_id = ? AND character_id = ?",
        (enc_id, character_id),
    )

    # Remove encounter-duration combat_state rows
    enc_cfg = _load_encounter_end_cfg(pack_dir)
    clear_types = enc_cfg.get("clear_duration_types", ["encounter", "rounds", "concentration", "reaction"])
    ph = ",".join("?" * len(clear_types))
    db.execute(
        f"DELETE FROM combat_state WHERE character_id = ? AND duration_type IN ({ph})",
        (character_id, *clear_types),
    )

    # Process attribute resets (e.g. active_alternate → base)
    reset_attrs = enc_cfg.get("reset_attributes", [])
    if reset_attrs:
        _reset_encounter_attributes(db, [character_id], reset_attrs, pack_dir)

    # Remove from initiative order
    init_order.remove(character_id)

    # Adjust current_turn if needed
    new_turn = current_turn
    if char_index < current_turn:
        new_turn = current_turn - 1
    elif is_current and init_order:
        new_turn = min(current_turn, len(init_order) - 1)

    db.execute(
        "UPDATE encounter_state SET initiative_order = ?, current_turn = ? WHERE id = ?",
        (json.dumps(init_order), new_turn, enc_id),
    )

    db.commit()
    try_rules_calc(db, character_id)

    result = f"LEFT ENCOUNTER: {char_name} removed"
    if is_current and init_order:
        result += " (was current turn — auto-advancing)"
        # Auto-advance will happen on next encounter_advance_turn call

    return result


def end_encounter(db, session_id: int, combat_cfg: dict | None = None, pack_dir: str | None = None) -> str:
    """End the active encounter with combat summary.

    Collects participant stats before cleanup, removes zones/positions/modifiers,
    generates a combat summary, and auto-saves it as a journal entry.
    """
    enc_id, rnd, _, _ = _require_active_encounter(db, session_id)
    cfg = combat_cfg or {}
    hud_cfg = cfg.get("hud", {})

    # Get all characters in the encounter for modifier cleanup
    char_ids = [
        r[0]
        for r in db.execute(
            "SELECT character_id FROM character_zone WHERE encounter_id = ?",
            (enc_id,),
        ).fetchall()
    ]

    # --- Collect combat summary data BEFORE cleanup ---
    participants = []
    defeated = []
    vital_lines = []
    for cid in char_ids:
        row = db.execute(
            "SELECT name, type, status FROM characters WHERE id = ?",
            (cid,),
        ).fetchone()
        if not row:
            continue
        cname, ctype, cstatus = row
        participants.append(f"{cname} ({ctype})")

        if cstatus in ("defeated", "dead", "unconscious"):
            defeated.append(cname)

        # Vital stats
        vital = _get_char_vital(db, cid, hud_cfg)
        if vital:
            vital_lines.append(f"  {cname}: {vital}")

    # --- Cleanup ---
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

    # Remove encounter-duration combat_state modifiers (data-driven)
    enc_cfg = _load_encounter_end_cfg(pack_dir)
    clear_types = enc_cfg.get("clear_duration_types", ["encounter", "rounds", "concentration"])
    encounter_removed = 0
    ph = ",".join("?" * len(clear_types))
    for cid in char_ids:
        encounter_removed += db.execute(
            f"DELETE FROM combat_state WHERE character_id = ? AND duration_type IN ({ph})",
            (cid, *clear_types),
        ).rowcount

    # Process attribute resets (e.g. active_alternate → base)
    reset_attrs = enc_cfg.get("reset_attributes", [])
    reset_lines = []
    if reset_attrs:
        reset_lines = _reset_encounter_attributes(db, char_ids, reset_attrs, pack_dir)

    # Clean up encounter-specific attributes (delayed markers, reaction policies)
    for cid in char_ids:
        db.execute(
            "DELETE FROM character_attributes WHERE character_id = ? AND key = '_delayed'",
            (cid,),
        )
        db.execute(
            "DELETE FROM character_attributes WHERE character_id = ? AND category = 'reaction_policy'",
            (cid,),
        )

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

    # Auto-recalc derived stats for all participants after modifier cleanup
    if terrain_removed or encounter_removed or reset_lines:
        from lorekit.rules import try_rules_calc

        for cid in char_ids:
            try_rules_calc(db, cid)

    # --- Format combat summary ---
    lines = [f"COMBAT ENDED ({rnd} rounds)"]
    if participants:
        lines.append(f"Participants: {', '.join(participants)}")
    if defeated:
        lines.append(f"Defeated: {', '.join(defeated)}")
    lines.extend(vital_lines)

    parts = []
    if terrain_removed:
        parts.append(f"{terrain_removed} terrain modifier(s)")
    if encounter_removed:
        parts.append(f"{encounter_removed} combat modifier(s)")
    if parts:
        lines.append(f"Cleared: {', '.join(parts)}")
    if reset_lines:
        lines.extend(reset_lines)

    # Auto-save combat summary to journal (scoped to participants)
    summary_text = "\n".join(lines)
    try:
        from lorekit.narrative.journal import add as journal_add

        journal_result = journal_add(db, session_id, "combat", summary_text, scope="participants")

        # Auto-tag all participants as entities on the journal entry
        try:
            journal_id = int(journal_result.split(": ")[1])
            for cid in char_ids:
                db.execute(
                    "INSERT OR IGNORE INTO entry_entities (source, source_id, entity_type, entity_id) "
                    "VALUES (?, ?, ?, ?)",
                    ("journal", journal_id, "character", cid),
                )
            db.commit()
        except (IndexError, ValueError):
            pass

        lines.append(f"Journal saved: {journal_result}")
    except Exception:
        pass  # journal save is best-effort

    return "\n".join(lines)


def add_zone(
    db,
    encounter_id: int,
    name: str,
    tags: list[str] | None = None,
    adjacent_to: list[dict] | None = None,
) -> str:
    """Add a new zone to an active encounter mid-combat.

    Creates the zone, establishes adjacency edges, and returns a summary.
    Used for dynamically created terrain (collapsing floor reveals basement,
    teleporting characters to a pocket dimension, aerial combat, etc.).

    adjacent_to: list of ``{"zone": "name", "weight": 1}`` dicts declaring
      which existing zones the new zone connects to. Defaults to no connections
      (isolated zone — useful for pocket dimensions or aerial).
    """
    # Verify zone name doesn't already exist
    existing = db.execute(
        "SELECT id FROM encounter_zones WHERE encounter_id = ? AND name = ?",
        (encounter_id, name),
    ).fetchone()
    if existing:
        raise LoreKitError(f"Zone '{name}' already exists in this encounter")

    tag_list = tags or []
    zcur = db.execute(
        "INSERT INTO encounter_zones (encounter_id, name, tags) VALUES (?, ?, ?)",
        (encounter_id, name, json.dumps(tag_list)),
    )
    new_zone_id = zcur.lastrowid

    # Establish adjacency
    edges_created = 0
    for edge in adjacent_to or []:
        neighbor_name = edge.get("zone")
        weight = edge.get("weight", 1)
        if not neighbor_name:
            continue
        try:
            neighbor_id = _zone_name_to_id(db, encounter_id, neighbor_name)
        except LoreKitError:
            continue
        db.execute(
            "INSERT INTO zone_adjacency (zone_a, zone_b, weight) VALUES (?, ?, ?)",
            (new_zone_id, neighbor_id, weight),
        )
        edges_created += 1

    db.commit()

    lines = [f"ZONE CREATED: {name}"]
    if tag_list:
        lines.append(f"  Tags: {tag_list}")
    if edges_created:
        neighbors = [e["zone"] for e in (adjacent_to or []) if e.get("zone")]
        lines.append(f"  Adjacent to: {', '.join(neighbors)}")
    else:
        lines.append("  Isolated (no adjacency)")

    return "\n".join(lines)


def remove_zone(
    db,
    encounter_id: int,
    zone_name: str,
    evacuate_to: str | None = None,
    combat_cfg: dict | None = None,
) -> str:
    """Remove a zone from an active encounter mid-combat.

    Moves any characters in the zone to ``evacuate_to`` (required if zone
    has occupants), removes adjacency edges, terrain modifiers, and the
    zone itself.

    Used for collapsing terrain, closing portals, etc.
    """
    zone_id = _zone_name_to_id(db, encounter_id, zone_name)
    cfg = combat_cfg or {}

    # Check for occupants
    occupants = db.execute(
        "SELECT character_id FROM character_zone WHERE encounter_id = ? AND zone_id = ?",
        (encounter_id, zone_id),
    ).fetchall()

    lines = [f"ZONE REMOVED: {zone_name}"]

    if occupants:
        if not evacuate_to:
            raise LoreKitError(f"Zone '{zone_name}' has {len(occupants)} character(s) — specify evacuate_to zone name")

        evac_id = _zone_name_to_id(db, encounter_id, evacuate_to)

        for (cid,) in occupants:
            # Remove old terrain modifiers
            _remove_zone_terrain(db, cid, zone_name)
            # Move to evacuation zone
            db.execute(
                "UPDATE character_zone SET zone_id = ? WHERE encounter_id = ? AND character_id = ?",
                (evac_id, encounter_id, cid),
            )
            # Apply new terrain modifiers
            _apply_zone_terrain(db, cid, evac_id, evacuate_to, cfg)

        cnames = [_char_name(db, c[0]) for c in occupants]
        lines.append(f"  Evacuated to {evacuate_to}: {', '.join(cnames)}")

    # Remove adjacency edges
    db.execute(
        "DELETE FROM zone_adjacency WHERE zone_a = ? OR zone_b = ?",
        (zone_id, zone_id),
    )

    # Remove the zone
    db.execute("DELETE FROM encounter_zones WHERE id = ?", (zone_id,))
    db.commit()

    # Recalc evacuated characters
    if occupants:
        from lorekit.rules import try_rules_calc

        for (cid,) in occupants:
            try_rules_calc(db, cid)

    return "\n".join(lines)


def update_zone_tags(
    db,
    encounter_id: int,
    zone_name: str,
    tags: list[str],
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
    from lorekit.rules import try_rules_calc

    for (cid,) in chars_in_zone:
        recalc = try_rules_calc(db, cid)
        if recalc:
            lines.append(recalc)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Range validation (for rules_resolve integration)
# ---------------------------------------------------------------------------


def get_area_targets(
    db, encounter_id: int, center_zone_id: int, radius: int, exclude_ids: set[int] | None = None
) -> list[int]:
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
        f"SELECT character_id FROM character_zone WHERE encounter_id = ? AND zone_id IN ({ph})",
        [encounter_id, *visited],
    ).fetchall()

    exclude = exclude_ids or set()
    return [r[0] for r in rows if r[0] not in exclude]


def check_range(
    db,
    encounter_id: int,
    attacker_id: int,
    defender_id: int,
    action_type: str,
    weapon_range: int | None,
    combat_cfg: dict,
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
            f"Target out of range. {_char_name(db, defender_id)} is unreachable from {_zone_id_to_name(db, atk_zid)}."
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
    db,
    encounter_id: int,
    attacker_id: int,
    target_id: int,
    push_zones: int,
    combat_cfg: dict,
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
