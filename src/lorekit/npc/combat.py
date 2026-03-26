"""npc_combat.py — NPC combat turn orchestration.

Builds combat context for the NPC agent, parses structured intent
from the response, and orchestrates the sequence of steps declared
in the system pack's ``intent`` schema.

The orchestration layer is domain-agnostic: step types, field schemas,
and sequence rules all come from system.json. A system with no
``intent`` section cannot run NPC combat turns.
"""

from __future__ import annotations

import json
import re

from lorekit.db import LoreKitError


def query_npc_reaction(
    db,
    reactor_id: int,
    source: str,
    hook: str,
    effect: str,
    attacker,
    defender,
) -> bool:
    """Ask an NPC whether to use a reaction via a lightweight Claude call.

    Builds a minimal prompt with the combat situation and the reaction
    choice, parses a YES/NO response. Returns True to use, False to decline.

    Falls back to True (use reaction) if the query fails or times out.
    """
    import subprocess

    from lorekit.encounter import _char_name

    reactor_name = _char_name(db, reactor_id)
    attacker_name = attacker.name if hasattr(attacker, "name") else str(attacker)
    defender_name = defender.name if hasattr(defender, "name") else str(defender)

    # Read NPC model from character_attributes (same as _build_npc_prompt)
    model_row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'system' AND key = 'model'",
        (reactor_id,),
    ).fetchone()
    if not model_row:
        raise LoreKitError(f"No model configured for character {reactor_id} — set category='system', key='model'")
    model = model_row[0]

    # Build a minimal prompt
    prompt = (
        f"You are {reactor_name} in combat. Quick decision — respond with only YES or NO.\n\n"
        f"{attacker_name} is attacking {defender_name}.\n"
        f"You have the reaction '{source}' available ({effect}).\n"
        f"Do you use it? Consider your own health, the ally's situation, and tactical value.\n"
        f"Respond with ONLY 'YES' or 'NO'."
    )

    try:
        proc = subprocess.run(
            [
                "claude",
                "-p",
                "--no-session-persistence",
                "--permission-mode",
                "bypassPermissions",
                "--tools",
                "",
                "--disable-slash-commands",
                "--model",
                model,
                "--output-format",
                "text",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            return True  # fallback: use reaction

        answer = proc.stdout.strip().upper()
        return "NO" not in answer
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True  # fallback: use reaction


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
    from lorekit.encounter import (
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

    # Available actions from system pack + character action overrides
    actions_section = ""
    combat_options_section = ""
    sdata = None
    system_path = _resolve_system_path_internal(db, session_id)
    if system_path:
        import os

        system_json = os.path.join(system_path, "system.json")
        if os.path.isfile(system_json):
            with open(system_json) as f:
                sdata = json.load(f)
            actions = dict(sdata.get("actions", {}))

            # Merge character-specific action overrides (e.g. powers that grant actions)
            char_overrides = db.execute(
                "SELECT key, value FROM character_attributes WHERE character_id = ? AND category = 'action_override'",
                (npc_id,),
            ).fetchall()
            for key, val in char_overrides:
                try:
                    actions[key] = json.loads(val) if isinstance(val, str) else val
                except json.JSONDecodeError:
                    pass

            if actions:
                action_labels = []
                for aname, adef in actions.items():
                    if isinstance(adef, dict):
                        arange = adef.get("range", "")
                        if arange:
                            action_labels.append(f"{aname} ({arange})")
                        else:
                            action_labels.append(aname)
                    else:
                        action_labels.append(aname)
                actions_section = f"Available actions: {', '.join(action_labels)}\n"

            # Available combat options (e.g. power_attack, all_out_attack)
            combat_opts = sdata.get("combat_options", {})
            if combat_opts:
                opt_lines = []
                for oname, odef in combat_opts.items():
                    desc = odef.get("description", "")
                    max_val = odef.get("max")
                    label = oname
                    if desc:
                        label += f" — {desc}"
                    if max_val:
                        label += f" (max {max_val})"
                    opt_lines.append(label)
                combat_options_section = "Combat options: " + ", ".join(opt_lines) + "\n"

    # NPC's own abilities (powers, feats, advantages) — with action/movement hints
    # Load active alternate state for array awareness
    active_alternates = {}
    alt_rows = db.execute(
        "SELECT key, value FROM character_attributes WHERE character_id = ? AND category = 'active_alternate'",
        (npc_id,),
    ).fetchall()
    for akey, aval in alt_rows:
        active_alternates[akey] = aval  # {array_name: active_alternate_name}

    abilities_section = ""
    ability_rows = db.execute(
        "SELECT name, uses, description FROM character_abilities WHERE character_id = ?",
        (npc_id,),
    ).fetchall()
    if ability_rows:
        ab_lines = []
        for ab_name, ab_uses, ab_desc in ability_rows:
            try:
                desc_data = json.loads(ab_desc)
            except (json.JSONDecodeError, TypeError, AttributeError):
                desc_data = None

            # Skip inactive array alternates
            if desc_data and active_alternates:
                array_of = desc_data.get("array_of")
                if array_of and active_alternates.get(array_of) != ab_name:
                    continue  # inactive alternate — don't show
                # Also skip the primary if an alternate is active
                if ab_name in active_alternates and active_alternates[ab_name] != ab_name:
                    continue

            line = f"  {ab_name} ({ab_uses}): "
            if desc_data:
                display_desc = desc_data.get("desc", ab_desc)
                uses_action = desc_data.get("uses_action")
                line += display_desc
                if uses_action:
                    line += f" [uses action: {uses_action}]"
                array_of = desc_data.get("array_of")
                if array_of:
                    line += f" [array: {array_of}, active]"
            else:
                line += ab_desc
            ab_lines.append(line)

        # Add array switching note if NPC has arrays
        if active_alternates and sdata:
            combat_data = sdata.get("combat", {})
            switching_cfg = combat_data.get("alternate_switching", {})
            action_cost = switching_cfg.get("action_cost", "free")
            max_per_turn = switching_cfg.get("max_per_turn")
            if max_per_turn:
                switch_row = db.execute(
                    "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_switches_this_turn'",
                    (npc_id,),
                ).fetchone()
                switches_used = int(switch_row[0]) if switch_row else 0
                remaining = max(0, max_per_turn - switches_used)
                if remaining > 0:
                    ab_lines.append(
                        f"  [You may switch arrays {remaining} more time(s) this turn ({action_cost} action)]"
                    )
                else:
                    ab_lines.append("  [No array switches remaining this turn]")

        abilities_section = "Your abilities:\n" + "\n".join(ab_lines) + "\n"

    # Movement modes (e.g. teleport)
    movement_section = ""
    move_mode_rows = db.execute(
        "SELECT key, value FROM character_attributes WHERE character_id = ? AND category = 'movement_mode'",
        (npc_id,),
    ).fetchall()
    if move_mode_rows:
        mode_labels = []
        for mkey, mval in move_mode_rows:
            try:
                mdata = json.loads(mval)
                if mdata.get("skip_adjacency"):
                    mode_labels.append(f"{mkey} (skip adjacency)")
                else:
                    mode_labels.append(mkey)
            except (json.JSONDecodeError, TypeError):
                mode_labels.append(mkey)
        movement_section = f"Movement modes: {', '.join(mode_labels)}\n"

    # NPC's own zone tags
    npc_ztags = _get_zone_tags(db, npc_zid) if npc_zid else []
    npc_zone_str = npc_zone
    if npc_ztags:
        npc_zone_str += f" [{', '.join(npc_ztags)}]"

    # Load intent schema and condition rules for JSON template and rules
    intent_schema = None
    condition_rules = {}
    if sdata:
        intent_schema = sdata.get("intent")
        condition_rules = sdata.get("combat", {}).get("condition_rules", {})

    json_block, rules_block = _build_intent_prompt(intent_schema)

    # Tactical options from intent schema (e.g. ready, delay)
    tactical_section = ""
    if intent_schema:
        tactical_lines = []
        steps_def = intent_schema.get("steps", {})
        for step_name, step_def in steps_def.items():
            if step_def.get("replaces_turn"):
                desc = step_def.get("description", "")
                if desc:
                    tactical_lines.append(f"  {step_name}: {desc}")
                else:
                    tactical_lines.append(f"  {step_name}")
        if tactical_lines:
            tactical_section = "Tactical options (replace your entire turn):\n" + "\n".join(tactical_lines) + "\n"

    # Available reactions (registered reaction abilities)
    reactions_section = ""
    reaction_rows = db.execute(
        "SELECT source, duration_type, duration, metadata FROM combat_state "
        "WHERE character_id = ? AND duration_type IN ('reaction', 'triggered') "
        "AND target_stat = '_reaction'",
        (npc_id,),
    ).fetchall()
    if reaction_rows:
        react_lines = []
        for rsource, rdur_type, rduration, rmeta_json in reaction_rows:
            try:
                rmeta = json.loads(rmeta_json) if rmeta_json else {}
            except (json.JSONDecodeError, TypeError):
                rmeta = {}
            hook = rmeta.get("hook", "")
            effect = rmeta.get("effect", "")
            uses = f"{rduration} use(s)" if rduration else "spent"
            # Show current policy
            policy_row = db.execute(
                "SELECT value FROM character_attributes "
                "WHERE character_id = ? AND category = 'reaction_policy' AND key = ?",
                (npc_id, rsource),
            ).fetchone()
            policy = policy_row[0] if policy_row else "active"
            react_lines.append(f"  {rsource} — triggers on {hook}, {effect} [{uses}] (policy: {policy})")
        reactions_section = (
            "Your reactions:\n" + "\n".join(react_lines) + "\n"
            "  You may set reaction_policy in your response to change how each reaction fires:\n"
            "    active  — auto-fire whenever triggered (default; use for most reactions)\n"
            "    inactive — suppress for the rest of this encounter\n"
            "    ask     — you will be consulted before it fires (only use this when the\n"
            "              situation is complex enough to warrant a deliberate choice)\n"
        )

    # Active sustained powers (can be deactivated)
    sustained_section = ""
    sustained_rows = db.execute(
        "SELECT DISTINCT source FROM combat_state WHERE character_id = ? AND duration_type = 'sustained'",
        (npc_id,),
    ).fetchall()
    if sustained_rows:
        sustained_names = [r[0] for r in sustained_rows]
        sustained_section = (
            "Active sustained powers: " + ", ".join(sustained_names) + " (you may deactivate these as a free action)\n"
        )

    # Team attack availability (same-zone allies who could assist)
    team_section = ""
    if sdata:
        team_cfg = sdata.get("combat", {}).get("team_attack", {})
        if team_cfg:
            bonus_per = team_cfg.get("attack_bonus_per", 2)
            max_bonus = team_cfg.get("max_attack_bonus", 5)
            same_zone = team_cfg.get("requires_same_zone", True)
            eligible = []
            for cid, zid, team in char_zones:
                if cid == npc_id:
                    continue
                if npc_team and team and team == npc_team:
                    if not same_zone or zid == npc_zid:
                        eligible.append(_char_name(db, cid))
            if eligible:
                team_section = (
                    f"Team attack: {', '.join(eligible)} can assist your attack "
                    f"(+{bonus_per} per ally, max +{max_bonus})\n"
                )

    # Active conditions with mechanical effects
    condition_section = ""
    active_labels = set()
    mod_rows = db.execute(
        "SELECT source, target_stat, value, duration_type, duration, applied_by "
        "FROM combat_state WHERE character_id = ? "
        "AND duration_type NOT IN ('reaction', 'triggered')",
        (npc_id,),
    ).fetchall()
    if mod_rows:
        mod_lines = []
        for source, stat, value, dur_type, duration, applied_by in mod_rows:
            line = f"  {source}: {value:+d} to {stat}"
            if applied_by:
                applier_name = db.execute("SELECT name FROM characters WHERE id = ?", (applied_by,)).fetchone()
                if applier_name:
                    line += f" (by {applier_name[0]})"
            if dur_type == "rounds" and duration is not None:
                line += f" [{duration}r left]"
            if dur_type == "sustained":
                line += " [sustained]"
            mod_lines.append(line)
            active_labels.add(source)
        condition_section = "Your active conditions:\n" + "\n".join(mod_lines) + "\n"

        # Add mechanical descriptions and NPC behavioral instructions
        cond_notes = []
        for label in active_labels:
            cdef = condition_rules.get(label)
            if isinstance(cdef, dict):
                desc = cdef.get("description")
                if desc:
                    cond_notes.append(f"  ⚠ {label}: {desc}")
                npc_instr = cdef.get("npc_instruction")
                if npc_instr:
                    cond_notes.append(f"    → {npc_instr}")
            elif cdef:
                cond_notes.append(f"  ⚠ {label}: {cdef}")
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
            if isinstance(cdef, dict):
                npc_instr = cdef.get("npc_instruction")
                if npc_instr:
                    condition_section += f"    → {npc_instr}\n"
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
{actions_section}{combat_options_section}{abilities_section}{movement_section}{reactions_section}{sustained_section}{team_section}{tactical_section}{condition_section}
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
        nullable = fdef.get("nullable", False)
        item_schema = fdef.get("item_schema")

        if ftype == "list" and item_schema:
            # Generate a structured example from item_schema
            item_example = {}
            for field_key, field_type in item_schema.items():
                if field_type == "number":
                    item_example[field_key] = 0
                elif field_type == "boolean":
                    item_example[field_key] = False
                else:
                    item_example[field_key] = "..."
            example[fname] = [item_example]
        elif nullable:
            example[fname] = f"{ftype} or null"
        else:
            example[fname] = ftype

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
        # Single-value vital (like mm3e damage condition)
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
    from lorekit.rules import resolve_system_path

    meta_row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'rules_system'",
        (session_id,),
    ).fetchone()
    if meta_row is None:
        return None
    return resolve_system_path(meta_row[0])


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
        from lorekit.combat import get_active_conditions

        active_conditions = get_active_conditions(db, npc_id, condition_rules, condition_thresholds)
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

    # Check for turn-replacing steps (e.g. ready, delay)
    # If present, only the turn-replacing step runs
    steps_def = schema.get("steps", {}) if schema else {}
    for step in sequence:
        step_def = steps_def.get(step, {})
        if step_def.get("replaces_turn"):
            return [step]

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
    from cruncher.system_pack import load_system_pack
    from lorekit.combat import resolve_action
    from lorekit.encounter import (
        _get_character_zone,
        _require_active_encounter,
        advance_turn,
        move_character,
    )

    lines = []
    skip_advance = False
    enc_id = _require_active_encounter(db, session_id)[0]

    # Load intent schema and condition rules
    pack = load_system_pack(system_path)
    schema = pack.intent or None
    steps_def = schema.get("steps", {}) if schema else {}
    cond_rules = pack.combat.get("condition_rules", {})
    cond_thresholds = pack.combat.get("condition_thresholds", [])

    sequence = intent.get("sequence", ["move", "action"])

    # Store reaction policies from NPC intent
    reaction_policy = intent.get("reaction_policy")
    if reaction_policy and isinstance(reaction_policy, dict):
        for rsource, rmode in reaction_policy.items():
            if rmode in ("active", "inactive", "ask"):
                db.execute(
                    "INSERT INTO character_attributes (character_id, category, key, value) "
                    "VALUES (?, 'reaction_policy', ?, ?) "
                    "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
                    (npc_id, rsource, rmode),
                )
        db.commit()

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

                    # Pass combat_options from NPC intent
                    npc_combat_opts = intent.get("combat_options")
                    if npc_combat_opts:
                        action_opts["combat_options"] = npc_combat_opts

                    # Wire reaction query callback for "ask" mode reactions
                    action_opts["reaction_query"] = query_npc_reaction

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

                    # Check for movement modes that bypass adjacency (e.g. teleport)
                    mode_rows = db.execute(
                        "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'movement_mode'",
                        (npc_id,),
                    ).fetchall()
                    skip_adj = any(json.loads(v).get("skip_adjacency") for (v,) in mode_rows) if mode_rows else False

                    lines.append(
                        move_character(
                            db,
                            enc_id,
                            npc_id,
                            move_to,
                            combat_cfg=combat_cfg,
                            movement_budget=movement_budget,
                            skip_adjacency=skip_adj,
                        )
                    )
                except LoreKitError as e:
                    lines.append(f"MOVEMENT FAILED: {e}")

        elif executor == "ready":
            action = intent.get("action")
            targets = intent.get("targets")
            target_name = targets[0] if targets else ""
            trigger = intent.get("trigger", "")
            if action and trigger:
                try:
                    from lorekit.encounter import ready_action

                    lines.append(
                        ready_action(
                            db,
                            session_id,
                            npc_id,
                            action,
                            trigger,
                            targets=target_name,
                            pack_dir=system_path,
                        )
                    )
                except LoreKitError as e:
                    lines.append(f"READY FAILED: {e}")
            else:
                lines.append("READY SKIPPED: requires action and trigger")

        elif executor == "delay":
            try:
                from lorekit.encounter import delay_turn

                lines.append(delay_turn(db, session_id, npc_id))
                skip_advance = True
            except LoreKitError as e:
                lines.append(f"DELAY FAILED: {e}")

        # Unknown executor: skip silently (schema may define future executors)

    # --- Advance turn (auto-calls end_turn on NPC) ---
    if not skip_advance:
        try:
            advance_result = advance_turn(db, session_id, combat_cfg=combat_cfg)
            lines.append(advance_result)
        except LoreKitError as e:
            lines.append(f"ADVANCE FAILED: {e}")

    return lines
