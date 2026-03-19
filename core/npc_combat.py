"""npc_combat.py — NPC combat turn orchestration.

Builds combat context for the NPC agent, parses structured intent
from the response, and orchestrates move → resolve → advance_turn.
"""

from __future__ import annotations

import json
import re

from _db import LoreKitError


def build_combat_context(
    db,
    npc_id: int,
    session_id: int,
    combat_cfg: dict,
) -> str:
    """Build a situation description for the NPC's combat decision.

    Uses relative health descriptions instead of exact numbers.
    Lists available actions, zone names, and character positions.
    Uses the ``team`` column in character_zone for ally/enemy classification.
    Same team = ally, different team = enemy, no team = everyone is enemy.
    """
    from encounter import (
        _build_adjacency,
        _char_name,
        _get_character_zone,
        _get_zone_tags,
        _require_active_encounter,
        _shortest_path,
        _zone_id_to_name,
    )

    enc_id, rnd, init_json, current_turn = _require_active_encounter(db, session_id)
    init_order = json.loads(init_json)
    hud_cfg = combat_cfg.get("hud", {})
    zone_scale = combat_cfg.get("zone_scale", 1)
    movement_unit = combat_cfg.get("movement_unit", "zone")

    npc_name = _char_name(db, npc_id)

    # NPC's current zone
    npc_zid = _get_character_zone(db, enc_id, npc_id)
    npc_zone = _zone_id_to_name(db, npc_zid) if npc_zid else "unknown"

    # All characters and their positions + team
    char_zones = db.execute(
        "SELECT character_id, zone_id, team FROM character_zone WHERE encounter_id = ?",
        (enc_id,),
    ).fetchall()

    # NPC's own team
    npc_team = ""
    for cid, _, team in char_zones:
        if cid == npc_id:
            npc_team = team
            break

    adj = _build_adjacency(db, enc_id)

    # Build character descriptions with relative health
    allies = []
    enemies = []
    for cid, zid, team in char_zones:
        if cid == npc_id:
            continue
        cname = _char_name(db, cid)
        zone_name = _zone_id_to_name(db, zid)

        # Distance
        dist = _shortest_path(adj, npc_zid, zid) if npc_zid else None
        if dist is not None and zone_scale > 1:
            dist_str = f"{dist} zone(s) ({dist * zone_scale}{movement_unit})"
        elif dist is not None:
            dist_str = f"{dist} zone(s)"
        else:
            dist_str = "unreachable"

        # Relative health
        health_desc = _get_relative_health(db, cid, hud_cfg)

        # Zone tags
        ztags = _get_zone_tags(db, zid)
        tag_str = f" [{', '.join(ztags)}]" if ztags else ""

        entry = f"{cname} — {zone_name}{tag_str}, {dist_str}"
        if health_desc:
            entry += f", {health_desc}"

        if npc_team and team and team == npc_team:
            allies.append(entry)
        else:
            enemies.append(entry)

    # Available zones
    zone_rows = db.execute(
        "SELECT id, name, tags FROM encounter_zones WHERE encounter_id = ? ORDER BY id",
        (enc_id,),
    ).fetchall()
    zone_list = []
    for zid, zname, ztags_json in zone_rows:
        ztags = json.loads(ztags_json)
        tag_str = f" [{', '.join(ztags)}]" if ztags else ""
        zone_list.append(f"{zname}{tag_str}")

    # Available actions from system pack
    actions_section = ""
    system_path = _resolve_system_path_internal(db, session_id)
    if system_path:
        import os

        system_json = os.path.join(system_path, "system.json")
        if os.path.isfile(system_json):
            with open(system_json) as f:
                data = json.load(f)
            actions = data.get("actions", {})
            if actions:
                action_names = list(actions.keys())
                actions_section = f"Available actions: {', '.join(action_names)}\n"

    # NPC's own abilities (powers, feats, advantages)
    abilities_section = ""
    ability_rows = db.execute(
        "SELECT name, uses, description FROM character_abilities WHERE character_id = ?",
        (npc_id,),
    ).fetchall()
    if ability_rows:
        lines = [f"  {ab[0]} ({ab[1]}): {ab[2]}" for ab in ability_rows]
        abilities_section = "Your abilities:\n" + "\n".join(lines) + "\n"

    # NPC's own zone tags
    npc_ztags = _get_zone_tags(db, npc_zid) if npc_zid else []
    npc_zone_str = npc_zone
    if npc_ztags:
        npc_zone_str += f" [{', '.join(npc_ztags)}]"

    context = f"""COMBAT — Round {rnd}
It is your turn ({npc_name}).

Your position: {npc_zone_str}
{_get_relative_health(db, npc_id, hud_cfg) or ""}

Enemies:
{chr(10).join(f"  {e}" for e in enemies) if enemies else "  (none)"}

Allies:
{chr(10).join(f"  {a}" for a in allies) if allies else "  (none)"}

Zones: {", ".join(zone_list)}
{actions_section}{abilities_section}
Decide what to do. Respond with a JSON block followed by optional in-character narration.

```json
{{
  "sequence": ["move", "action"],
  "action": "action_name or null",
  "target": "character name or null",
  "ally": "ally name (for actions that grant a bonus to an ally)",
  "move_to": "zone name or null",
  "move_others": [{{"character": "name", "zone": "zone name"}}],
  "narration": "Brief in-character line (optional)"
}}
```

Rules:
- sequence defines execution order. Valid steps: "move", "action", "move_others". Default: ["move", "action"]
  Examples: ["action", "move"] to attack then reposition, ["move_others", "action"] to teleport allies then act
- action MUST be one of the available actions listed above — NOT an ability name. Your abilities describe what you
  can do narratively, but the engine resolves them through system actions (e.g. use close_attack for a melee power,
  ranged_attack for a ranged power, setup_deception for a feint). Use move_others for abilities that move other characters.
- action/target/move_to can all be null (narrative-only turn)
- target must be a character name from the lists above
- move_to must be a zone name from the list above
- move_others is optional — use it when an ability moves allies or enemies (e.g. mass teleport, teleport attack)
- Keep narration brief (1-2 sentences)"""

    return context


def _get_relative_health(db, cid: int, hud_cfg: dict) -> str:
    """Convert vital stats to relative description (unhurt/wounded/critical)."""
    vital = hud_cfg.get("vital_stat")
    if not vital:
        return ""

    current_key = vital.get("current")
    max_key = vital.get("max")

    if not current_key:
        return ""

    current_row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND key = ?",
        (cid, current_key),
    ).fetchone()
    if not current_row:
        return ""
    current = float(current_row[0])

    if not max_key:
        # Single-value vital (like M&M3e damage condition)
        if current <= 0:
            return "unhurt"
        return f"condition {int(current)}"

    max_row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND key = ?",
        (cid, max_key),
    ).fetchone()
    if not max_row:
        return ""
    max_val = float(max_row[0])

    if max_val <= 0:
        return ""

    ratio = current / max_val
    if ratio >= 1.0:
        return "unhurt"
    elif ratio >= 0.75:
        return "lightly wounded"
    elif ratio >= 0.5:
        return "wounded"
    elif ratio >= 0.25:
        return "badly wounded"
    elif current > 0:
        return "critical"
    else:
        return "down"


def parse_combat_intent(response: str) -> dict:
    """Extract structured combat intent from NPC response.

    Looks for a JSON block in the response. Returns dict with
    action, target, move_to, move_others, narration — all nullable.
    """
    # Try to find JSON block (```json ... ``` or bare { ... })
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
    if not json_match:
        # Fallback: find outermost { ... } containing "action"
        json_match = re.search(r"(\{(?:[^{}]|\{[^{}]*\}|\[.*?\])*\})", response, re.DOTALL)
        if json_match and '"action"' not in json_match.group(1):
            json_match = None

    if json_match:
        try:
            intent = json.loads(json_match.group(1))
            raw_seq = intent.get("sequence")
            valid_steps = {"move", "action", "move_others"}
            sequence = [s for s in raw_seq if s in valid_steps] if isinstance(raw_seq, list) else None
            return {
                "sequence": sequence or ["move", "action", "move_others"],
                "action": intent.get("action") or None,
                "target": intent.get("target") or None,
                "ally": intent.get("ally") or None,
                "move_to": intent.get("move_to") or None,
                "move_others": intent.get("move_others") or None,
                "narration": intent.get("narration") or None,
            }
        except json.JSONDecodeError:
            pass

    # Fallback: narrative-only turn (couldn't parse intent)
    return {
        "sequence": ["move", "action", "move_others"],
        "action": None,
        "target": None,
        "ally": None,
        "move_to": None,
        "move_others": None,
        "narration": response.strip() or None,
    }


def _resolve_system_path_internal(db, session_id: int) -> str | None:
    """Resolve system pack path from session metadata."""
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


def execute_combat_turn(
    db,
    session_id: int,
    npc_id: int,
    intent: dict,
    combat_cfg: dict,
    system_path: str,
) -> list[str]:
    """Execute the mechanical part of an NPC combat turn.

    Orchestrates: move (if move_to) → resolve (if action) → advance_turn.
    advance_turn auto-calls end_turn on the NPC.

    Returns list of result lines.
    """
    from combat_engine import resolve_action
    from encounter import (
        _get_character_zone,
        _require_active_encounter,
        advance_turn,
        move_character,
    )

    lines = []
    enc_id = _require_active_encounter(db, session_id)[0]

    sequence = intent.get("sequence", ["move", "action", "move_others"])

    for step in sequence:
        if step == "action":
            action = intent.get("action")
            target_name = intent.get("target")
            if action and target_name:
                target_row = db.execute(
                    "SELECT id FROM characters WHERE session_id = ? AND LOWER(name) = LOWER(?)",
                    (session_id, target_name.strip()),
                ).fetchone()
                if target_row:
                    # Build options (e.g. ally_id for setup actions)
                    action_opts = {}
                    ally_name = intent.get("ally")
                    if ally_name:
                        ally_row = db.execute(
                            "SELECT id FROM characters WHERE session_id = ? AND LOWER(name) = LOWER(?)",
                            (session_id, ally_name.strip()),
                        ).fetchone()
                        if ally_row:
                            action_opts["ally_id"] = ally_row[0]
                    try:
                        lines.append(
                            resolve_action(
                                db,
                                npc_id,
                                target_row[0],
                                action,
                                system_path,
                                options=action_opts if action_opts else None,
                            )
                        )
                    except LoreKitError as e:
                        err_msg = str(e)
                        # Fallback: NPC used ability name instead of system action
                        if "Unknown action" in err_msg and "close_attack" in err_msg:
                            try:
                                lines.append(f"NOTE: '{action}' resolved as close_attack")
                                lines.append(
                                    resolve_action(
                                        db,
                                        npc_id,
                                        target_row[0],
                                        "close_attack",
                                        system_path,
                                        options=action_opts if action_opts else None,
                                    )
                                )
                            except LoreKitError as e2:
                                lines.append(f"ACTION FAILED: {e2}")
                        else:
                            lines.append(f"ACTION FAILED: {e}")
                else:
                    lines.append(f"ACTION FAILED: Target '{target_name}' not found")
            elif action and not target_name:
                lines.append(f"ACTION SKIPPED: {action} — no target specified")

        elif step == "move":
            move_to = intent.get("move_to")
            if move_to:
                try:
                    mv_row = db.execute(
                        "SELECT value FROM character_attributes WHERE character_id = ? AND key = 'movement_zones'",
                        (npc_id,),
                    ).fetchone()
                    movement_budget = int(mv_row[0]) if mv_row else None
                    lines.append(
                        move_character(
                            db,
                            enc_id,
                            npc_id,
                            move_to,
                            combat_cfg=combat_cfg,
                            movement_budget=movement_budget,
                        )
                    )
                except LoreKitError as e:
                    lines.append(f"MOVEMENT FAILED: {e}")

        elif step == "move_others":
            move_others = intent.get("move_others")
            if move_others:
                for entry in move_others:
                    char_name = entry.get("character")
                    target_zone = entry.get("zone")
                    if not char_name or not target_zone:
                        continue
                    char_row = db.execute(
                        "SELECT id FROM characters WHERE session_id = ? AND LOWER(name) = LOWER(?)",
                        (session_id, char_name.strip()),
                    ).fetchone()
                    if not char_row:
                        lines.append(f"MOVE_OTHERS FAILED: '{char_name}' not found")
                        continue
                    try:
                        lines.append(move_character(db, enc_id, char_row[0], target_zone, combat_cfg=combat_cfg))
                    except LoreKitError as e:
                        lines.append(f"MOVE_OTHERS FAILED ({char_name}): {e}")

    # --- Advance turn (auto-calls end_turn on NPC) ---
    try:
        advance_result = advance_turn(db, session_id, combat_cfg=combat_cfg)
        lines.append(advance_result)
    except LoreKitError as e:
        lines.append(f"ADVANCE FAILED: {e}")

    return lines
