"""npc_combat.py — NPC combat turn orchestration.

Builds combat context for the NPC agent, parses structured intent
from the response, and orchestrates the sequence of steps declared
in the system pack's ``intent`` schema.

The orchestration layer is zero-knowledge: step types, field schemas,
and sequence rules all come from system.json. A system with no
``intent`` section cannot run NPC combat turns.
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

    The JSON template and rules are generated from the system pack's
    ``intent`` schema. If no schema is present, falls back to a minimal
    default.
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
    npc_gender = db.execute("SELECT gender FROM characters WHERE id = ?", (npc_id,)).fetchone()
    npc_gender = npc_gender[0] if npc_gender and npc_gender[0] else ""

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
        cgender = db.execute("SELECT gender FROM characters WHERE id = ?", (cid,)).fetchone()
        cgender = cgender[0] if cgender and cgender[0] else ""
        if cgender:
            cname = f"{cname} ({cgender})"
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

    # Available actions from system pack (with range annotations)
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
                action_labels = []
                for aname, adef in actions.items():
                    arange = adef.get("range", "")
                    if arange:
                        action_labels.append(f"{aname} ({arange})")
                    else:
                        action_labels.append(aname)
                actions_section = f"Available actions: {', '.join(action_labels)}\n"

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

    # Load intent schema and condition rules for JSON template and rules
    intent_schema = None
    condition_rules = {}
    sdata = None
    if system_path:
        import os

        system_json = os.path.join(system_path, "system.json")
        if os.path.isfile(system_json):
            with open(system_json) as f:
                sdata = json.load(f)
            intent_schema = sdata.get("intent")
            condition_rules = sdata.get("combat", {}).get("condition_rules", {})

    json_block, rules_block = _build_intent_prompt(intent_schema)

    # Active conditions with mechanical effects
    condition_section = ""
    active_labels = set()
    mod_rows = db.execute(
        "SELECT source, target_stat, value, duration_type, duration FROM combat_state WHERE character_id = ?",
        (npc_id,),
    ).fetchall()
    if mod_rows:
        mod_lines = []
        for source, stat, value, dur_type, duration in mod_rows:
            line = f"  {source}: {value:+d} to {stat}"
            if dur_type == "rounds" and duration is not None:
                line += f" [{duration}r left]"
            mod_lines.append(line)
            active_labels.add(source)
        condition_section = "Your active conditions:\n" + "\n".join(mod_lines) + "\n"

        # Add mechanical descriptions for recognized conditions
        cond_notes = []
        for label in active_labels:
            cdef = condition_rules.get(label)
            desc = cdef.get("description") if isinstance(cdef, dict) else cdef
            if desc:
                cond_notes.append(f"  ⚠ {label}: {desc}")
        if cond_notes:
            condition_section += "\n".join(cond_notes) + "\n"

    # Also check attribute-based condition thresholds
    cond_thresholds = sdata.get("combat", {}).get("condition_thresholds", []) if sdata else []
    for thresh in cond_thresholds:
        attr_key = thresh.get("attribute")
        min_val = thresh.get("min")
        cond_name = thresh.get("condition")
        if not (attr_key and min_val is not None and cond_name and cond_name in condition_rules):
            continue
        row = db.execute(
            "SELECT value FROM character_attributes WHERE character_id = ? AND key = ?",
            (npc_id, attr_key),
        ).fetchone()
        if row and float(row[0]) >= min_val and cond_name not in active_labels:
            cdef = condition_rules[cond_name]
            desc = cdef.get("description") if isinstance(cdef, dict) else cdef
            condition_section += f"  ⚠ {cond_name}: {desc}\n"
            active_labels.add(cond_name)

    gender_note = f" [{npc_gender}]" if npc_gender else ""
    context = f"""COMBAT — Round {rnd}
It is your turn ({npc_name}{gender_note}).

Your position: {npc_zone_str}
{_get_relative_health(db, npc_id, hud_cfg) or ""}

Enemies:
{chr(10).join(f"  {e}" for e in enemies) if enemies else "  (none)"}

Allies:
{chr(10).join(f"  {a}" for a in allies) if allies else "  (none)"}

Zones: {", ".join(zone_list)}
{actions_section}{abilities_section}{condition_section}
Decide what to do. Respond with a JSON block followed by optional in-character narration.

```json
{json_block}
```

Rules:
{rules_block}"""

    return context


def _build_intent_prompt(schema: dict | None) -> tuple[str, str]:
    """Generate JSON example and rules text from intent schema.

    Returns (json_block, rules_block) strings for the NPC prompt.
    """
    if not schema:
        # Minimal fallback for systems without intent schema
        json_block = """{
  "sequence": ["move", "action"],
  "action": "action_name or null",
  "targets": ["character name or null"],
  "move_to": "zone name or null",
  "narration": "Brief in-character line (optional)"
}"""
        rules_block = """- sequence defines execution order — reorder steps as tactics demand
- Most turns use at most one move and one action
- action MUST be one of the available actions listed above — NOT an ability name
- action/targets/move_to can all be null (narrative-only turn)
- Keep narration brief (1-2 sentences)"""
        return json_block, rules_block

    steps = schema.get("steps", {})
    default_seq = schema.get("default_sequence", list(steps.keys()))
    extra_fields = schema.get("extra_fields", {})
    rules = schema.get("rules", [])

    # Build JSON example
    example = {}
    example["sequence"] = default_seq

    for step_name, step_def in steps.items():
        if "fields" in step_def:
            for fname, fdef in step_def["fields"].items():
                ftype = fdef.get("type", "text")
                if ftype == "characters":
                    example[fname] = ["character name or null"]
                elif ftype == "action_name":
                    example[fname] = "action_name or null"
                else:
                    example[fname] = f"{ftype} or null"
        elif "field" in step_def:
            field_name = step_def["field"]
            ftype = step_def.get("field_type", "text")
            if step_def.get("multi"):
                example[field_name] = 'zone name, or ["zone1", "zone2"] for multi-move, or null'
            elif ftype == "zone":
                example[field_name] = "zone name or null"
            else:
                example[field_name] = f"{ftype} or null"

    for fname, fdef in extra_fields.items():
        ftype = fdef.get("type", "text")
        example[fname] = f"{ftype} (optional)" if fdef.get("nullable") else ftype

    json_block = json.dumps(example, indent=2)

    # Build rules block
    rules_lines = []
    for rule in rules:
        rules_lines.append(f"- {rule}")

    # Add step-specific context
    seq_rules = schema.get("sequence_rules", {})
    max_per_step = seq_rules.get("max_per_step", {})
    max_total = seq_rules.get("max_total")
    if max_per_step or max_total:
        limits = []
        for step, max_count in max_per_step.items():
            limits.append(f"{step}: max {max_count}")
        if max_total:
            limits.append(f"total: max {max_total}")
        rules_lines.append(f"- Step limits: {', '.join(limits)}")

    rules_lines.append("- Keep narration brief (1-2 sentences)")

    rules_block = "\n".join(rules_lines)
    return json_block, rules_block


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


def parse_combat_intent(response: str, schema: dict | None = None) -> dict:
    """Extract structured combat intent from NPC response.

    Looks for a JSON block in the response. Returns dict with
    schema-declared fields. ``target`` is normalized to ``targets`` (list).

    When schema is provided, only schema-declared step names are valid
    in the sequence. Otherwise falls back to a default set.
    """
    # Determine valid step names from schema
    if schema:
        valid_steps = set(schema.get("steps", {}).keys())
        default_sequence = schema.get("default_sequence", list(valid_steps))
    else:
        valid_steps = {"move", "action"}
        default_sequence = ["move", "action"]

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
            sequence = [s for s in raw_seq if s in valid_steps] if isinstance(raw_seq, list) else None

            # Normalize target → targets (always a list)
            targets = intent.get("targets") or intent.get("target") or None
            if targets is not None and isinstance(targets, str):
                targets = [targets]

            result = {
                "sequence": sequence or list(default_sequence),
                "action": intent.get("action") or None,
                "targets": targets,
                "move_to": intent.get("move_to") or None,
                "narration": intent.get("narration") or None,
            }

            # Copy extra fields from schema
            if schema:
                for fname in schema.get("extra_fields", {}):
                    if fname not in result:
                        result[fname] = intent.get(fname) or None

            return result
        except json.JSONDecodeError:
            pass

    # Fallback: narrative-only turn (couldn't parse intent)
    return {
        "sequence": list(default_sequence),
        "action": None,
        "targets": None,
        "move_to": None,
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


def _validate_sequence(
    sequence: list[str],
    schema: dict | None,
    db,
    npc_id: int,
    *,
    condition_rules: dict | None = None,
    condition_thresholds: list | None = None,
) -> list[str]:
    """Validate and trim sequence against system + character limits.

    Checks schema limits, character attribute overrides, and active
    condition restrictions (e.g. staggered → max_total 1).

    Returns the validated sequence (excess steps dropped with warning logged).
    """
    if not schema:
        return sequence

    seq_rules = schema.get("sequence_rules", {})
    max_per_step = dict(seq_rules.get("max_per_step", {}))
    max_total = seq_rules.get("max_total")

    # Character-level overrides: max_{step}_steps attribute
    # When a per-step limit increases, expand max_total by the same delta
    for step_name in max_per_step:
        override_key = f"max_{step_name}_steps"
        row = db.execute(
            "SELECT value FROM character_attributes WHERE character_id = ? AND key = ?",
            (npc_id, override_key),
        ).fetchone()
        if row:
            new_val = int(row[0])
            old_val = max_per_step[step_name]
            if max_total is not None and new_val > old_val:
                max_total += new_val - old_val
            max_per_step[step_name] = new_val

    # Condition-based overrides (e.g. staggered → max_total: 1)
    if condition_rules:
        active_conditions = _get_active_conditions(db, npc_id, condition_rules, condition_thresholds)
        for cond_name in active_conditions:
            cond_def = condition_rules.get(cond_name, {})
            if not isinstance(cond_def, dict):
                continue
            cond_max_total = cond_def.get("max_total")
            if cond_max_total is not None:
                if max_total is None or cond_max_total < max_total:
                    max_total = cond_max_total
            cond_max_move = cond_def.get("max_move")
            if cond_max_move is not None:
                cur = max_per_step.get("move")
                if cur is None or cond_max_move < cur:
                    max_per_step["move"] = cond_max_move

    # Validate per-step counts
    step_counts: dict[str, int] = {}
    validated = []
    for step in sequence:
        step_counts[step] = step_counts.get(step, 0) + 1
        max_for_step = max_per_step.get(step)
        if max_for_step is not None and step_counts[step] > max_for_step:
            continue  # drop excess step
        validated.append(step)

    # Validate max_total
    if max_total is not None and len(validated) > max_total:
        validated = validated[:max_total]

    return validated


def _get_active_conditions(db, character_id: int, condition_rules: dict, thresholds: list | None = None) -> set[str]:
    """Determine which condition_rules are active on a character.

    Checks combat_state modifier sources and attribute-based thresholds
    from the system pack's ``condition_thresholds`` list.
    """
    active = set()

    # Check combat_state sources
    sources = db.execute(
        "SELECT DISTINCT source FROM combat_state WHERE character_id = ?",
        (character_id,),
    ).fetchall()
    for (source,) in sources:
        if source in condition_rules:
            active.add(source)

    # Check attribute-based condition thresholds
    for thresh in thresholds or []:
        attr_key = thresh.get("attribute")
        min_val = thresh.get("min")
        cond_name = thresh.get("condition")
        if not (attr_key and min_val is not None and cond_name):
            continue
        row = db.execute(
            "SELECT value FROM character_attributes WHERE character_id = ? AND key = ?",
            (character_id, attr_key),
        ).fetchone()
        if row and float(row[0]) >= min_val:
            active.add(cond_name)

    return active


def execute_combat_turn(
    db,
    session_id: int,
    npc_id: int,
    intent: dict,
    combat_cfg: dict,
    system_path: str,
) -> list[str]:
    """Execute the mechanical part of an NPC combat turn.

    Dispatches steps by executor type from the intent schema.
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
    from system_pack import load_system_pack

    lines = []
    enc_id = _require_active_encounter(db, session_id)[0]

    # Load intent schema and condition rules
    pack = load_system_pack(system_path)
    schema = pack.intent or None
    steps_def = schema.get("steps", {}) if schema else {}
    cond_rules = pack.combat.get("condition_rules", {})
    cond_thresholds = pack.combat.get("condition_thresholds", [])

    sequence = intent.get("sequence", ["move", "action"])

    # Validate sequence against schema + character overrides + conditions
    sequence = _validate_sequence(
        sequence, schema, db, npc_id, condition_rules=cond_rules, condition_thresholds=cond_thresholds
    )

    # Normalize move_to into a queue (supports string or list for multi-move)
    raw_move_to = intent.get("move_to")
    if isinstance(raw_move_to, list):
        move_queue = list(raw_move_to)
    elif raw_move_to:
        move_queue = [raw_move_to]
    else:
        move_queue = []

    for step in sequence:
        step_def = steps_def.get(step, {})
        executor = step_def.get("executor", step)

        if executor == "resolve_action":
            action = intent.get("action")
            # Get targets — normalized to list
            targets = intent.get("targets")
            target_name = targets[0] if targets else None

            if action and target_name:
                target_row = db.execute(
                    "SELECT id FROM characters WHERE session_id = ? AND LOWER(name) = LOWER(?)",
                    (session_id, target_name.strip()),
                ).fetchone()
                if target_row:
                    # Build target_roles from action definition targets map
                    action_opts = {}
                    action_def = pack.actions.get(action, {})
                    targets_map = action_def.get("targets")
                    if targets_map and targets:
                        target_roles = {}
                        role_names = list(targets_map.keys())
                        for i, role_name in enumerate(role_names):
                            if i < len(targets):
                                t_name = targets[i]
                                t_row = db.execute(
                                    "SELECT id FROM characters WHERE session_id = ? AND LOWER(name) = LOWER(?)",
                                    (session_id, t_name.strip()),
                                ).fetchone()
                                if t_row:
                                    target_roles[role_name] = t_row[0]
                        if target_roles:
                            action_opts["target_roles"] = target_roles

                    # Pass intent fields declared on the action
                    intent_fields = action_def.get("intent_fields", {})
                    for field_name in intent_fields:
                        val = intent.get(field_name)
                        if val is not None:
                            action_opts[field_name] = val

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

        elif executor == "movement":
            move_to = move_queue.pop(0) if move_queue else None
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

        # Unknown executor: skip silently (schema may define future executors)

    # --- Advance turn (auto-calls end_turn on NPC) ---
    try:
        advance_result = advance_turn(db, session_id, combat_cfg=combat_cfg)
        lines.append(advance_result)
    except LoreKitError as e:
        lines.append(f"ADVANCE FAILED: {e}")

    return lines
