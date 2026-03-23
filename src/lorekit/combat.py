"""Combat engine — action resolution and turn lifecycle.

Action resolution: reads action definitions and resolution rules from
the system pack, looks up pre-computed stats on attacker/defender, rolls
dice, and applies stat mutations (subtract_from, increment, apply_modifiers,
push). Two hardcoded resolution strategies (threshold and degree), with an
optional contested mode where both sides roll; all stat names, formulas,
and action definitions come from the system pack JSON.

Turn lifecycle: end-of-turn duration ticking reads the system pack's
end_turn config and processes each combat modifier according to its
duration type's declared tick behavior (decrement, check). Recomputes
derived stats when modifiers expire.
"""

from __future__ import annotations

import math
import random
from typing import Any

from cruncher.dice import roll_expr
from cruncher.system_pack import SystemPack, load_system_pack
from cruncher.types import CharacterData
from lorekit.db import LoreKitError
from lorekit.rules import load_character_data

# ---------------------------------------------------------------------------
# Condition checks (shared by PC resolve_action and NPC _validate_sequence)
# ---------------------------------------------------------------------------


def get_active_conditions(db, character_id: int, condition_rules: dict, thresholds: list | None = None) -> set[str]:
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


def is_incapacitated(db, character_id: int, pack: SystemPack) -> tuple[bool, str | None]:
    """Check if a character has an active condition with max_total 0.

    Returns (True, condition_name) if the character cannot act at all,
    or (False, None) otherwise.
    """
    combat_cfg = pack.combat or {}
    condition_rules = combat_cfg.get("condition_rules")
    if not condition_rules:
        return False, None
    thresholds = combat_cfg.get("condition_thresholds")
    active = get_active_conditions(db, character_id, condition_rules, thresholds)
    for cond_name in active:
        cond_def = condition_rules.get(cond_name, {})
        if isinstance(cond_def, dict) and cond_def.get("max_total") == 0:
            return True, cond_name
    return False, None


def _check_condition_action_limit(db, character_id: int, pack: SystemPack) -> None:
    """Raise LoreKitError if active conditions prevent the character from acting.

    Reads condition_rules and condition_thresholds from the system pack's
    combat config.  For each active condition with a ``max_total`` field:
      - max_total 0 → character cannot act at all (stunned, incapacitated)
      - max_total >= 1 → character can act that many times per turn;
        uses a ``_actions_this_turn`` attribute as a counter (reset on
        advance_turn).
    """
    combat_cfg = pack.combat or {}
    condition_rules = combat_cfg.get("condition_rules")
    if not condition_rules:
        return

    thresholds = combat_cfg.get("condition_thresholds")
    active = get_active_conditions(db, character_id, condition_rules, thresholds)
    if not active:
        return

    # Find the most restrictive max_total among active conditions
    effective_max: int | None = None
    blocking_condition: str | None = None
    for cond_name in active:
        cond_def = condition_rules.get(cond_name, {})
        if not isinstance(cond_def, dict):
            continue
        cond_max = cond_def.get("max_total")
        if cond_max is not None:
            if effective_max is None or cond_max < effective_max:
                effective_max = cond_max
                blocking_condition = cond_name

    if effective_max is None:
        return

    if effective_max == 0:
        desc = condition_rules.get(blocking_condition, {}).get("description", "")
        msg = f"BLOCKED: character is {blocking_condition}"
        if desc:
            msg += f" — {desc}"
        raise LoreKitError(msg)

    # max_total >= 1: check per-turn action counter
    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_actions_this_turn'",
        (character_id,),
    ).fetchone()
    actions_used = int(row[0]) if row else 0

    if actions_used >= effective_max:
        desc = condition_rules.get(blocking_condition, {}).get("description", "")
        msg = f"BLOCKED: character is {blocking_condition} — already used {actions_used}/{effective_max} action(s) this turn"
        if desc:
            msg += f" ({desc})"
        raise LoreKitError(msg)


def _increment_turn_actions(db, character_id: int) -> None:
    """Increment the per-turn action counter for a character."""
    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_actions_this_turn'",
        (character_id,),
    ).fetchone()
    new_val = (int(row[0]) if row else 0) + 1
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) "
        "VALUES (?, 'internal', '_actions_this_turn', ?) "
        "ON CONFLICT(character_id, category, key) DO UPDATE SET value = ?",
        (character_id, str(new_val), str(new_val)),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Condition modifier sync (Phases 1+2: additive modifiers + decomposition)
# ---------------------------------------------------------------------------


def expand_conditions(
    active: set[str],
    condition_rules: dict,
    combined_conditions: dict,
) -> tuple[set[str], list[dict]]:
    """Expand combined conditions into base conditions.

    Returns (expanded_set, extra_modifiers) where expanded_set includes both
    the original labels and all component base conditions, and extra_modifiers
    collects any extra_modifiers from combined condition entries in
    condition_rules or combined_conditions.
    """
    expanded = set(active)
    extra_mods: list[dict] = []
    seen: set[str] = set()

    def _expand(cond: str) -> None:
        if cond in seen:
            return
        seen.add(cond)

        # Check condition_rules first (inline components), then combined_conditions
        cdef = condition_rules.get(cond, {})
        components = cdef.get("components") or []
        if not components:
            cdef_combined = combined_conditions.get(cond, {})
            components = cdef_combined.get("components") or []
            if cdef_combined.get("extra_modifiers"):
                extra_mods.extend(cdef_combined["extra_modifiers"])
        else:
            if cdef.get("extra_modifiers"):
                extra_mods.extend(cdef["extra_modifiers"])

        for comp in components:
            expanded.add(comp)
            _expand(comp)

    for cond in list(active):
        _expand(cond)

    return expanded, extra_mods


def sync_condition_modifiers(
    db,
    character_id: int,
    condition_rules: dict,
    combined_conditions: dict,
    thresholds: list | None = None,
) -> bool:
    """Sync combat_state rows for active conditions.

    1. Determine active conditions (via get_active_conditions).
    2. Expand combined conditions into base conditions.
    3. For each base condition with 'modifiers', ensure combat_state has
       matching rows with source = 'cond:<name>'.
    4. For each condition with 'flags', write/delete is_<flag> attributes.
    5. For inactive conditions, delete 'cond:*' rows and flag attributes.
    6. Return True if anything changed (caller should rules_calc).
    """
    active = get_active_conditions(db, character_id, condition_rules, thresholds)
    expanded, extra_mods = expand_conditions(active, condition_rules, combined_conditions)

    changed = False

    # Collect all desired cond:* modifiers from expanded conditions
    desired_mods: dict[tuple[str, str], dict] = {}  # (source, target_stat) → mod
    desired_flags: set[str] = set()

    for cond_name in expanded:
        cdef = condition_rules.get(cond_name, {})
        if not isinstance(cdef, dict):
            continue

        # Additive modifiers
        for mod in cdef.get("modifiers", []):
            source = f"cond:{cond_name}"
            key = (source, mod["target_stat"])
            desired_mods[key] = mod

        # Condition flags
        for flag in cdef.get("flags", []):
            desired_flags.add(flag)

    # Extra modifiers from combined condition entries (e.g. prone → -5 close_attack)
    for mod in extra_mods:
        # Use source from the combined condition that generated it
        source = "cond:extra"
        key = (source, mod["target_stat"])
        desired_mods[key] = mod

    # Get current cond:* rows
    existing_rows = db.execute(
        "SELECT id, source, target_stat FROM combat_state WHERE character_id = ? AND source LIKE 'cond:%'",
        (character_id,),
    ).fetchall()
    existing_keys = {(src, stat): row_id for row_id, src, stat in existing_rows}

    # Insert missing modifier rows
    for (source, target_stat), mod in desired_mods.items():
        if (source, target_stat) not in existing_keys:
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type) "
                "VALUES (?, ?, ?, ?, ?, 'condition')",
                (
                    character_id,
                    source,
                    target_stat,
                    mod.get("modifier_type", "condition"),
                    mod["value"],
                ),
            )
            changed = True

    # Remove stale modifier rows
    for (source, target_stat), row_id in existing_keys.items():
        if (source, target_stat) not in desired_mods:
            db.execute("DELETE FROM combat_state WHERE id = ?", (row_id,))
            changed = True

    # Sync condition flags as character attributes
    existing_flags = db.execute(
        "SELECT key FROM character_attributes WHERE character_id = ? AND category = 'condition_flags'",
        (character_id,),
    ).fetchall()
    existing_flag_set = {row[0] for row in existing_flags}

    for flag in desired_flags:
        if flag not in existing_flag_set:
            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'condition_flags', ?, '1') "
                "ON CONFLICT(character_id, category, key) DO UPDATE SET value = '1'",
                (character_id, flag),
            )
            changed = True

    for flag in existing_flag_set:
        if flag not in desired_flags:
            db.execute(
                "DELETE FROM character_attributes WHERE character_id = ? AND category = 'condition_flags' AND key = ?",
                (character_id, flag),
            )
            changed = True

    # Condition-based cancellation: remove modifiers with duration_types
    # that active conditions cancel (e.g. stunned cancels sustained/concentration)
    cancel_types: set[str] = set()
    for cond_name in expanded:
        cdef = condition_rules.get(cond_name, {})
        if isinstance(cdef, dict):
            for dt in cdef.get("cancels_duration_types", []):
                cancel_types.add(dt)

    if cancel_types:
        placeholders = ",".join("?" for _ in cancel_types)
        cancelled = db.execute(
            f"DELETE FROM combat_state WHERE character_id = ? "
            f"AND duration_type IN ({placeholders}) "
            f"AND source NOT LIKE 'cond:%'",
            (character_id, *cancel_types),
        )
        if cancelled.rowcount > 0:
            changed = True

    if changed:
        db.commit()

    return changed


def _get_defender_resolution_effects(
    db,
    defender_id: int,
    pack: SystemPack,
) -> dict:
    """Collect resolution_effects from active conditions and zone tags.

    Returns a merged dict of resolution effects. Supported keys are
    system-defined; the engine recognises:
      - attacker_routine_check (bool): use routine_value instead of rolling
      - hits_are_critical (bool): any hit becomes a critical
      - attacker_bonus (dict[range_type → int]): bonus to attack by range
      - miss_chance (float 0-1): probability of miss even on a hit
    """
    combat_cfg = pack.combat or {}
    condition_rules = combat_cfg.get("condition_rules", {})
    combined_conditions = combat_cfg.get("combined_conditions", {})
    thresholds = combat_cfg.get("condition_thresholds")

    merged: dict = {}

    # Collect from condition resolution_effects
    if condition_rules:
        active = get_active_conditions(db, defender_id, condition_rules, thresholds)
        expanded, _ = expand_conditions(active, condition_rules, combined_conditions)

        for cond_name in expanded:
            cdef = condition_rules.get(cond_name, {})
            if not isinstance(cdef, dict):
                continue
            effects = cdef.get("resolution_effects", {})
            for key, val in effects.items():
                if key == "attacker_bonus" and isinstance(val, dict):
                    existing = merged.setdefault("attacker_bonus", {})
                    for range_type, bonus in val.items():
                        existing[range_type] = existing.get(range_type, 0) + bonus
                elif key == "miss_chance":
                    merged[key] = max(merged.get(key, 0.0), val)
                else:
                    if val:
                        merged[key] = True

    # Collect miss_chance from defender's zone tags
    zone_tags_cfg = combat_cfg.get("zone_tags", {})
    if zone_tags_cfg:
        zone_row = db.execute(
            "SELECT z.tags FROM encounter_zones z "
            "JOIN character_zone cz ON cz.zone_id = z.id "
            "WHERE cz.character_id = ?",
            (defender_id,),
        ).fetchone()
        if zone_row and zone_row[0]:
            import json as _json

            try:
                tags = _json.loads(zone_row[0]) if isinstance(zone_row[0], str) else zone_row[0]
            except (ValueError, TypeError):
                tags = []
            for tag in tags:
                tag_cfg = zone_tags_cfg.get(tag, {})
                zone_miss = tag_cfg.get("miss_chance")
                if zone_miss is not None:
                    merged["miss_chance"] = max(merged.get("miss_chance", 0.0), zone_miss)

    return merged


def _sync_and_recalc(db, character_id: int, pack: SystemPack, lines: list[str] | None = None) -> None:
    """Run condition modifier sync and recalc if anything changed."""
    combat_cfg = pack.combat or {}
    cr = combat_cfg.get("condition_rules", {})
    cc = combat_cfg.get("combined_conditions", {})
    th = combat_cfg.get("condition_thresholds")
    if cr and sync_condition_modifiers(db, character_id, cr, cc, th):
        from lorekit.rules import rules_calc as _rules_calc

        if pack.pack_dir:
            recalc = _rules_calc(db, character_id, pack.pack_dir)
        else:
            from lorekit.rules import try_rules_calc

            recalc = try_rules_calc(db, character_id)
        if recalc and lines is not None:
            lines.append(recalc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_derived(char: CharacterData, stat: str) -> int:
    """Read a derived stat value. Falls back to build, then any category."""
    derived = char.attributes.get("derived", {})
    val = derived.get(stat)
    if val is not None:
        return int(val)

    # Fall back to build attributes
    build = char.attributes.get("build", {})
    val = build.get(stat)
    if val is not None:
        return int(val)

    # Fall back to any category
    for cat_attrs in char.attributes.values():
        if stat in cat_attrs:
            return int(cat_attrs[stat])

    raise LoreKitError(f"Stat '{stat}' not found on character {char.name}")


def _is_crit(crit_cfg: dict | None, natural: int | None, attacker: CharacterData) -> bool:
    """Check if a natural roll qualifies as a critical hit.

    If the system pack declares a ``threshold_stat`` in its critical config,
    the attacker's value for that stat lowers the critical threshold
    (e.g. 2 ranks → crit on 18-20 instead of only 20).
    """
    if not crit_cfg or natural is None:
        return False
    base_threshold = crit_cfg.get("natural", 20)
    threshold_stat = crit_cfg.get("threshold_stat")
    if threshold_stat:
        try:
            base_threshold -= _get_derived(attacker, threshold_stat)
        except LoreKitError:
            pass
    return natural >= base_threshold


def _get_action_def(pack: SystemPack, char: CharacterData, action: str) -> dict:
    """Look up an action definition: character override first, then system pack."""
    overrides = char.attributes.get("action_override", {})
    if action in overrides:
        raw = overrides[action]
        if isinstance(raw, str):
            import json

            return json.loads(raw)
        return raw

    if action in pack.actions:
        return pack.actions[action]

    # Build combined list of available actions
    available = sorted(set(pack.actions.keys()) | set(overrides.keys()))
    raise LoreKitError(f"Unknown action '{action}'. Available: {', '.join(available)}")


def _get_gm_hints(pack: SystemPack, action: str) -> str | None:
    """Look up gm_hints for a gm_assisted effect from effects.json.

    Returns a formatted hint string, or None if the action is not a
    recognized gm_assisted effect.
    """
    import json as _json
    import os

    effects_path = os.path.join(pack.pack_dir, "effects.json")
    if not os.path.isfile(effects_path):
        return None

    with open(effects_path) as f:
        effects_data = _json.load(f)

    effect_def = effects_data.get(action)
    if not isinstance(effect_def, dict):
        return None
    if effect_def.get("resolution") != "gm_assisted":
        return None

    lines = [f"GM-ASSISTED EFFECT: {effect_def.get('name', action)}"]
    lines.append(f"  Type: {effect_def.get('type', 'unknown')}")
    lines.append(f"  Action: {effect_def.get('action', 'standard')}")
    lines.append(f"  Range: {effect_def.get('range', 'close')}")
    lines.append(f"  Duration: {effect_def.get('duration', 'instant')}")

    if effect_def.get("resistance"):
        lines.append(f"  Resistance: {effect_def['resistance']}")

    note = effect_def.get("note")
    if note:
        lines.append(f"  Note: {note}")

    hints = effect_def.get("gm_hints", {})
    if hints:
        lines.append("  ---")
        if "check_type" in hints:
            lines.append(f"  Check: {hints['check_type']}")
        if "dc_formula" in hints:
            lines.append(f"  DC: {hints['dc_formula']}")
        for rule in hints.get("key_rules", []):
            lines.append(f"  Rule: {rule}")

    return "\n".join(lines)


def _get_attr_str(char: CharacterData, stat: str) -> str:
    """Read a string attribute (e.g., weapon_damage_die). Checks build then all."""
    build = char.attributes.get("build", {})
    val = build.get(stat)
    if val is not None:
        return val

    for cat_attrs in char.attributes.values():
        if stat in cat_attrs:
            return cat_attrs[stat]

    raise LoreKitError(f"Attribute '{stat}' not found on character {char.name}")


def _write_attr(db, character_id: int, key: str, value: Any) -> None:
    """Write/update a combat attribute on a character."""
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) "
        "VALUES (?, 'combat', ?, ?) "
        "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
        (character_id, key, str(value)),
    )
    db.commit()


def _read_resource(db, character_id: int, key: str) -> int:
    """Read a resource value from character_attributes (category='resource')."""
    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'resource' AND key = ?",
        (character_id, key),
    ).fetchone()
    return int(row[0]) if row else 0


def _write_resource(db, character_id: int, key: str, value: int) -> None:
    """Write a resource value to character_attributes (category='resource')."""
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) "
        "VALUES (?, 'resource', ?, ?) "
        "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
        (character_id, key, str(value)),
    )
    db.commit()


def _expand_combat_options(pack: SystemPack, options: dict) -> dict:
    """Expand named combat options into trade dicts.

    Reads ``combat_options`` from the options dict, looks up each name in
    ``pack.combat_options``, resolves the value, and injects trade dicts
    (with optional apply_modifiers) into ``options["trade"]``.

    Returns a new options dict with the expanded trades appended.
    """
    named = options.get("combat_options")
    if not named or not pack.combat_options:
        return options

    options = dict(options)
    trades = list(options.get("trade", []))
    option_warnings = options.get("_option_warnings", [])

    for entry in named:
        # Normalize: bare string "power_attack" → {"name": "power_attack"}
        if isinstance(entry, str):
            entry = {"name": entry}
        name = entry.get("name")
        if not name:
            continue
        defn = pack.combat_options.get(name)
        if defn is None:
            option_warnings.append(f"⚠ UNKNOWN COMBAT OPTION: '{name}' not found in system pack")
            continue

        # Resolve value: fixed from definition, or GM-provided, clamped to max
        requested = entry.get("value")
        value = defn.get("value", requested if requested is not None else 0)
        max_val = defn.get("max")
        if max_val is not None and value > max_val:
            option_warnings.append(f"⚠ CLAMPED: {name} value {value} exceeds max {max_val}, using {max_val}")
            value = max_val
        if requested is None and "value" not in defn:
            option_warnings.append(f"⚠ MISSING VALUE: {name} requires a value (max {max_val}), defaulting to 0")

        # Build trade dict
        trade_def = defn.get("trade", {})
        trade: dict[str, Any] = {"to": trade_def["to"], "value": value}
        if "from" in trade_def:
            trade["from"] = trade_def["from"]

        # Build apply_modifiers with negate support
        apply_mods = defn.get("apply_modifiers")
        if apply_mods:
            resolved_mods = []
            for mod in apply_mods:
                mod = dict(mod)
                if mod.pop("negate", False):
                    mod["value"] = -value
                resolved_mods.append(mod)
            trade["apply_modifiers"] = resolved_mods

        trades.append(trade)

    options["trade"] = trades
    if option_warnings:
        options["_option_warnings"] = option_warnings
    return options


def _apply_trade_modifiers(
    db,
    attacker: CharacterData,
    options: dict,
    lines: list[str],
) -> None:
    """Apply persistent modifiers declared on trade options to the attacker.

    Each trade dict may include an ``apply_modifiers`` list of modifier specs
    that are inserted into combat_state on the attacker regardless of hit/miss
    (they represent the cost of using the option).
    """
    recalc = False
    for trade in options.get("trade", []):
        trade_mods = trade.get("apply_modifiers")
        if not trade_mods or not isinstance(trade_mods, list):
            continue
        for mod in trade_mods:
            source = mod["source"]
            target_stat = mod["target_stat"]
            mod_type = mod.get("modifier_type", "condition")
            dur_type = mod.get("duration_type", "encounter")
            bonus_type = mod.get("bonus_type")
            duration = mod.get("duration")
            value = mod.get("value", 0)

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "bonus_type, duration_type, duration) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET "
                "value = excluded.value, duration = excluded.duration",
                (attacker.character_id, source, target_stat, mod_type, value, bonus_type, dur_type, duration),
            )
            dur_info = f"{dur_type}, {duration} rounds" if duration else dur_type
            lines.append(f"TRADE MODIFIER: {source} → {target_stat} {value:+d} ({dur_info})")
            recalc = True

    if recalc:
        db.commit()
        from lorekit.rules import try_rules_calc

        recomp = try_rules_calc(db, attacker.character_id)
        if recomp:
            for line in recomp.split("\n"):
                if line.startswith("  ") and "→" in line:
                    lines.append(f"  {line.strip()}")


def _ensure_current_hp(db, defender: CharacterData) -> int:
    """Ensure current_hp exists — initialize from max_hp if missing."""
    combat = defender.attributes.get("combat", {})
    val = combat.get("current_hp")
    if val is not None:
        return int(val)

    derived = defender.attributes.get("derived", {})
    max_hp = derived.get("max_hp")
    if max_hp is not None:
        hp = int(max_hp)
        _write_attr(db, defender.character_id, "current_hp", hp)
        defender.attributes.setdefault("combat", {})["current_hp"] = str(hp)
        return hp

    raise LoreKitError(f"No current_hp or max_hp found on {defender.name}. Set combat stats before resolving actions.")


# ---------------------------------------------------------------------------
# Degree-effect application — reusable by degree resolution and tick actions
# ---------------------------------------------------------------------------


def _apply_degree_effect(
    db,
    char: CharacterData,
    effect: dict,
    lines: list[str],
) -> None:
    """Apply a single degree-effect entry (increment, set, set_max, label).

    Used by degree-of-failure resolution and tick actions (auto_save, worsen).
    """
    # Apply increments from degree table
    increment = effect.get("increment")
    if increment and isinstance(increment, dict):
        for stat, value in increment.items():
            try:
                current = _get_derived(char, stat)
            except LoreKitError:
                current = 0
            new_val = current + value
            _write_attr(db, char.character_id, stat, new_val)
            lines.append(f"{stat}: {current} → {new_val}")

    # Apply direct attribute writes
    set_attrs = effect.get("set")
    if set_attrs and isinstance(set_attrs, dict):
        for stat, value in set_attrs.items():
            _write_attr(db, char.character_id, stat, value)

    # Apply set_max: only write if new value exceeds current
    set_max_attrs = effect.get("set_max")
    if set_max_attrs and isinstance(set_max_attrs, dict):
        for stat, value in set_max_attrs.items():
            try:
                current = _get_derived(char, stat)
            except LoreKitError:
                current = 0
            if value > current:
                _write_attr(db, char.character_id, stat, value)

    label = effect.get("label")
    if label:
        lines.append(f"CONDITION: {label}")


# ---------------------------------------------------------------------------
# On-hit effects — shared by all resolution types
# ---------------------------------------------------------------------------


def _char_name_from_id(db, character_id: int) -> str:
    row = db.execute("SELECT name FROM characters WHERE id = ?", (character_id,)).fetchone()
    return row[0] if row else f"#{character_id}"


def _apply_on_hit(
    db,
    pack: SystemPack,
    attacker: CharacterData,
    defender: CharacterData,
    on_hit: dict,
    lines: list[str],
    is_crit: bool = False,
    margin: int = 0,
    options: dict | None = None,
) -> None:
    """Apply all declared on_hit effects from an action definition.

    Supported effects (all optional, composable):
    - damage_roll + subtract_from: roll damage dice, subtract from a stat
    - apply_modifiers: insert combat_state rows (on defender or intent_ally)
    - push + push_direction: force-move defender via zone graph

    When is_crit is True and the system pack declares on_critical.damage_multiplier,
    total damage is multiplied accordingly.
    """
    options = options or {}
    # --- Resource spend ---
    spend = on_hit.get("spend_resource")
    if spend:
        res_key = spend["key"]
        cost = spend.get("cost", 1)
        current = _read_resource(db, attacker.character_id, res_key)
        if current < cost:
            raise LoreKitError(f"Not enough {res_key}: have {current}, need {cost}")
        _write_resource(db, attacker.character_id, res_key, current - cost)
        lines.append(f"RESOURCE: {res_key} {current} → {current - cost}")

    # --- Resource earn ---
    earn = on_hit.get("earn_resource")
    if earn:
        res_key = earn["key"]
        amount = earn.get("amount", 1)
        target = earn.get("target", "attacker")
        char_id = defender.character_id if target == "defender" else attacker.character_id
        current = _read_resource(db, char_id, res_key)
        _write_resource(db, char_id, res_key, current + amount)
        lines.append(f"RESOURCE: {res_key} {current} → {current + amount}")

    # --- Remove conditions ---
    remove_conds = on_hit.get("remove_conditions")
    if remove_conds and isinstance(remove_conds, list):
        for cond in remove_conds:
            source_key = f"cond:{cond}"
            deleted = db.execute(
                "DELETE FROM combat_state WHERE character_id = ? AND source = ?",
                (defender.character_id, source_key),
            )
            if deleted.rowcount > 0:
                lines.append(f"CONDITION REMOVED: {cond}")

        # Also clear threshold attributes that map to removed conditions
        combat_cfg = pack.combat or {}
        thresholds = combat_cfg.get("condition_thresholds", [])
        for thresh in thresholds:
            if thresh.get("condition") in remove_conds:
                attr_key = thresh.get("attribute")
                if attr_key:
                    _write_attr(db, defender.character_id, attr_key, 0)
                    lines.append(f"RESET: {attr_key} → 0")

        db.commit()
        _sync_and_recalc(db, defender.character_id, pack, lines)

    # --- Modify attribute ---
    mod_attr = on_hit.get("modify_attribute")
    if mod_attr and isinstance(mod_attr, dict):
        floor_map = on_hit.get("floor", {})
        ceiling_map = on_hit.get("ceiling", {})
        for attr_key, delta in mod_attr.items():
            try:
                current = _get_derived(defender, attr_key)
            except LoreKitError:
                current = 0
            new_val = current + int(delta)
            if attr_key in floor_map:
                new_val = max(int(floor_map[attr_key]), new_val)
            if attr_key in ceiling_map:
                new_val = min(int(ceiling_map[attr_key]), new_val)
            _write_attr(db, defender.character_id, attr_key, new_val)
            lines.append(f"MODIFIED: {attr_key} {current} → {new_val}")
        db.commit()
        _sync_and_recalc(db, defender.character_id, pack, lines)

    # --- Damage ---
    damage_info = on_hit.get("damage_roll")
    subtract_target = on_hit.get("subtract_from")

    if damage_info and subtract_target:
        dice_attr = damage_info["dice_attr"]
        bonus_stat = damage_info["bonus_stat"]

        dice_expr = _get_attr_str(attacker, dice_attr)
        damage_bonus = _get_derived(attacker, bonus_stat)

        damage_result = roll_expr(dice_expr)
        damage_roll = damage_result["total"]
        total_damage = damage_roll + damage_bonus

        # Apply critical damage multiplier from system pack
        if is_crit:
            on_critical = pack.resolution.get("on_critical", {})
            multiplier = on_critical.get("damage_multiplier")
            if multiplier and multiplier != 1:
                total_damage = total_damage * multiplier
                lines.append(f"CRITICAL! Damage x{multiplier}")

        lines.append(f"DAMAGE: {dice_expr}({damage_roll}) + {damage_bonus} = {total_damage}")

        if subtract_target == "current_hp":
            current = _ensure_current_hp(db, defender)
        else:
            current = _get_derived(defender, subtract_target)

        new_val = current - total_damage
        _write_attr(db, defender.character_id, subtract_target, new_val)
        lines.append(f"{subtract_target}: {current} → {new_val}")

        # Fire on-damage triggers (e.g. concentration break)
        _fire_damage_triggers(db, pack, defender.character_id, total_damage, lines)

    # --- Apply modifiers (combat_state rows) ---
    modifiers = on_hit.get("apply_modifiers")
    if modifiers and isinstance(modifiers, list):
        recalc_ids = set()
        for mod in modifiers:
            source = mod["source"]
            target_stat = mod["target_stat"]
            mod_type = mod.get("modifier_type", "condition")
            dur_type = mod.get("duration_type", "encounter")
            bonus_type = mod.get("bonus_type")
            duration = mod.get("duration")

            # halve: compute penalty = -floor(derived_stat / 2)
            # e.g. bonus_parry with halve reads "parry" and applies -parry//2
            if mod.get("halve"):
                # Derive the base stat name from the bonus stat (bonus_parry → parry)
                base_stat = target_stat.replace("bonus_", "") if target_stat.startswith("bonus_") else target_stat
                try:
                    current_val = _get_derived(defender, base_stat)
                    value = -(current_val // 2)
                except LoreKitError:
                    value = 0
            else:
                value = mod.get("value", 0)

            # value_min_margin: use max(declared value, margin of success)
            if mod.get("value_min_margin") and margin > value:
                value = margin

            # apply_to: who receives the modifier (role name or "defender")
            apply_to = mod.get("apply_to", "defender")
            target_roles = options.get("target_roles", {})
            if apply_to == "defender" or apply_to not in target_roles:
                char_id = defender.character_id
                label = source
            else:
                role_id = target_roles[apply_to]
                char_id = role_id
                role_name = _char_name_from_id(db, role_id)
                label = f"{source} → {role_name}"

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "bonus_type, duration_type, duration, applied_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET "
                "value = excluded.value, duration = excluded.duration, "
                "applied_by = excluded.applied_by",
                (char_id, source, target_stat, mod_type, value, bonus_type, dur_type, duration, attacker.character_id),
            )
            dur_info = f"{dur_type}, {duration} rounds" if duration else dur_type
            lines.append(f"MODIFIER: {label} → {target_stat} {value:+d} ({dur_info})")
            recalc_ids.add(char_id)

        db.commit()

        from lorekit.rules import try_rules_calc

        for cid in recalc_ids:
            recalc = try_rules_calc(db, cid)
            if recalc:
                lines.append(recalc)

        # Sync conditions in case a newly-inserted source matches a condition_rules key
        for cid in recalc_ids:
            _sync_and_recalc(db, cid, pack, lines)

    # --- Forced movement ---
    push = on_hit.get("push")
    if push:
        from lorekit.encounter import _get_active_encounter, force_move

        direction = on_hit.get("push_direction", "away")
        enc = _get_active_encounter(db, attacker.session_id)
        if enc is not None:
            enc_id = enc[0]
            zone_scale = pack.combat.get("zone_scale", 1)
            push_zones = math.ceil(push / zone_scale) if zone_scale > 0 else push

            if direction == "away":
                result = force_move(
                    db,
                    enc_id,
                    attacker.character_id,
                    defender.character_id,
                    push_zones,
                    pack.combat,
                )
            elif direction == "toward":
                result = force_move(
                    db,
                    enc_id,
                    defender.character_id,
                    attacker.character_id,
                    push_zones,
                    pack.combat,
                )
            else:
                result = None

            if result:
                lines.append(result)
            else:
                lines.append(f"PUSH: {defender.name} — no movement (boundary)")

    # --- Relocate (willed move to a named zone) ---
    relocate = on_hit.get("relocate")
    if relocate:
        from lorekit.encounter import _get_active_encounter, move_character

        who = relocate.get("who", "primary")
        zone_field = relocate.get("zone_field")
        target_roles = options.get("target_roles", {})

        # Determine who to relocate
        if who in target_roles:
            relocate_id = target_roles[who]
        elif who == "primary":
            relocate_id = defender.character_id
        else:
            relocate_id = defender.character_id

        # Get zone name from options (passed from intent fields)
        zone_name = options.get(zone_field) if zone_field else None
        if zone_name:
            enc = _get_active_encounter(db, attacker.session_id)
            if enc is not None:
                enc_id = enc[0]
                try:
                    result = move_character(db, enc_id, relocate_id, zone_name, combat_cfg=pack.combat)
                    lines.append(result)
                except LoreKitError as e:
                    lines.append(f"RELOCATE FAILED: {e}")
        else:
            if zone_field:
                lines.append(f"RELOCATE SKIPPED: no zone specified in '{zone_field}'")


# ---------------------------------------------------------------------------
# On-damage triggers — concentration break, etc.
# ---------------------------------------------------------------------------


def _fire_damage_triggers(
    db,
    pack: SystemPack,
    defender_id: int,
    damage_rank: int | None,
    lines: list[str],
) -> None:
    """Check damage_triggers config and fire any matching triggers.

    Called after damage/degree application. For each configured trigger,
    checks if the defender has active modifiers with the matching
    duration_type, then rolls a save. On failure, removes those modifiers.
    """
    triggers = pack.combat.get("damage_triggers")
    if not triggers:
        return

    # Get defender's active duration_types
    active_rows = db.execute(
        "SELECT DISTINCT duration_type FROM combat_state WHERE character_id = ?",
        (defender_id,),
    ).fetchall()
    active_types = {row[0] for row in active_rows}

    for dur_type, trigger_cfg in triggers.items():
        if dur_type not in active_types:
            continue

        save_stat = trigger_cfg.get("save_stat")
        if not save_stat:
            continue

        # Compute DC: either fixed or formula-based
        dc = trigger_cfg.get("dc", 10)
        if damage_rank is not None:
            dc_formula = trigger_cfg.get("dc_formula")
            if dc_formula == "max(10, floor(damage_rank / 2))":
                dc = max(10, damage_rank // 2)
            elif dc_formula:
                # Generic: try simple eval with damage_rank
                try:
                    dc = int(
                        eval(
                            dc_formula,
                            {"__builtins__": {}},
                            {"damage_rank": damage_rank, "max": max, "min": min, "floor": math.floor},
                        )
                    )
                except Exception as e:
                    lines.append(f"⚠ DC_FORMULA: '{dc_formula}' failed — {e}. Using default DC {dc}.")

        char = load_character_data(db, defender_id)
        derived = char.attributes.get("derived", {})
        bonus = int(derived.get(save_stat, 0))
        result = roll_expr(pack.dice)
        total = result["total"] + bonus
        success = total >= dc

        if not success:
            db.execute(
                "DELETE FROM combat_state WHERE character_id = ? AND duration_type = ?",
                (defender_id, dur_type),
            )
            db.commit()
            lines.append(
                f"DAMAGE TRIGGER [{dur_type}] BROKEN: {save_stat} "
                f"{pack.dice}({result['total']}) + {bonus} = {total} vs DC {dc} — FAILED, {dur_type} effects lost"
            )
            _sync_and_recalc(db, defender_id, pack, lines)
        else:
            lines.append(
                f"DAMAGE TRIGGER [{dur_type}] HELD: {save_stat} "
                f"{pack.dice}({result['total']}) + {bonus} = {total} vs DC {dc} — SUCCESS"
            )


# ---------------------------------------------------------------------------
# Reaction system — interrupt hooks in resolution pipeline
# ---------------------------------------------------------------------------


def _check_reactions(
    db,
    pack: SystemPack,
    hook_name: str,
    attacker: CharacterData,
    defender: CharacterData,
    action_def: dict,
    lines: list[str],
) -> dict:
    """Check for reaction combat_state entries matching the named hook.

    Reactions are combat_state rows with ``duration_type`` in
    ('reaction', 'triggered') and a JSON ``metadata`` column declaring
    which hook they respond to and what effect they produce.

    Returns a dict of context modifications:
    - ``new_defender_id``: substitute defender (Interpose)
    - ``defense_override``: replace defense value (Deflect)
    - ``free_attack``: reactor gets a free counter-attack
    """
    import json as _json

    reactions_cfg = pack.combat.get("reactions", {})
    hook_cfg = reactions_cfg.get(hook_name, {})
    if not hook_cfg:
        return {}

    rows = db.execute(
        "SELECT id, character_id, source, duration_type, duration, metadata "
        "FROM combat_state "
        "WHERE duration_type IN ('reaction', 'triggered') AND duration > 0 AND metadata IS NOT NULL",
    ).fetchall()

    if not rows:
        return {}

    modifications = {}

    for row_id, reactor_id, source, dur_type, duration, metadata_str in rows:
        try:
            metadata = _json.loads(metadata_str)
        except (ValueError, TypeError):
            continue

        if metadata.get("hook") != hook_name:
            continue

        effect_name = metadata.get("effect")
        if effect_name not in hook_cfg:
            continue

        effect_cfg = hook_cfg[effect_name]
        scope = effect_cfg.get("scope", "self_targeted")

        # Scope filter
        if scope == "ally_targeted":
            if reactor_id == attacker.character_id or reactor_id == defender.character_id:
                continue
            team_row = db.execute(
                "SELECT cz1.team FROM character_zone cz1 "
                "JOIN character_zone cz2 ON cz1.encounter_id = cz2.encounter_id "
                "WHERE cz1.character_id = ? AND cz2.character_id = ? "
                "AND cz1.team != '' AND cz1.team = cz2.team",
                (reactor_id, defender.character_id),
            ).fetchone()
            if not team_row:
                continue
        elif scope == "self_targeted":
            if reactor_id != defender.character_id:
                continue

        # Range check if required
        if effect_cfg.get("check") == "range":
            from lorekit.encounter import _build_adjacency, _get_active_encounter, _shortest_path

            enc = _get_active_encounter(db, attacker.session_id)
            if enc:
                enc_id = enc[0]
                reactor_zone = db.execute(
                    "SELECT zone_id FROM character_zone WHERE encounter_id = ? AND character_id = ?",
                    (enc_id, reactor_id),
                ).fetchone()
                defender_zone = db.execute(
                    "SELECT zone_id FROM character_zone WHERE encounter_id = ? AND character_id = ?",
                    (enc_id, defender.character_id),
                ).fetchone()
                if reactor_zone and defender_zone:
                    adj = _build_adjacency(db, enc_id)
                    dist = _shortest_path(adj, reactor_zone[0], defender_zone[0])
                    max_range = metadata.get("range_zones", 1)
                    if dist is not None and dist > max_range:
                        continue

        # Dispatch effect
        reactor_name = db.execute("SELECT name FROM characters WHERE id = ?", (reactor_id,)).fetchone()
        reactor_name = reactor_name[0] if reactor_name else f"#{reactor_id}"

        if effect_name == "substitute_defender":
            lines.append(f"REACTION [{source}]: {reactor_name} interposes for {defender.name}!")
            modifications["new_defender_id"] = reactor_id
        elif effect_name == "use_reactor_stat":
            stat_name = metadata.get("stat", "deflect")
            try:
                reactor_char = load_character_data(db, reactor_id)
                stat_val = _get_derived(reactor_char, stat_name)
                lines.append(f"REACTION [{source}]: {reactor_name} deflects! Using {stat_name} ({stat_val}) as defense")
                modifications["defense_override"] = stat_val
            except LoreKitError:
                continue
        elif effect_name == "counter_attack":
            counter_action = metadata.get("counter_action", "close_attack")
            lines.append(f"REACTION [{source}]: {reactor_name} counter-attacks!")
            modifications["free_attack"] = {
                "reactor_id": reactor_id,
                "target_id": attacker.character_id,
                "action": counter_action,
            }

        # Consume
        if dur_type == "triggered":
            db.execute("DELETE FROM combat_state WHERE id = ?", (row_id,))
        else:
            db.execute("UPDATE combat_state SET duration = duration - 1 WHERE id = ?", (row_id,))
        db.commit()

        break  # One reaction per hook per resolution

    return modifications


# ---------------------------------------------------------------------------
# Team/combined attack — assistants boost a single attack
# ---------------------------------------------------------------------------


def _apply_team_bonus(
    db,
    pack: SystemPack,
    attacker: CharacterData,
    options: dict,
    lines: list[str],
) -> tuple[int, int]:
    """Compute team attack bonuses from assistants.

    Returns (attack_bonus, dc_bonus) to add to the attack roll and damage rank.
    Consumes each assistant's action for the turn.
    """
    assistants = options.get("assistants")
    if not assistants:
        return 0, 0

    team_cfg = pack.combat.get("team_attack")
    if not team_cfg:
        return 0, 0

    bonus_per = team_cfg.get("attack_bonus_per", 2)
    max_bonus = team_cfg.get("max_attack_bonus", 5)
    dc_per = team_cfg.get("dc_bonus_per", 1)
    same_zone = team_cfg.get("requires_same_zone", True)

    valid_count = 0
    for aid in assistants:
        if aid == attacker.character_id:
            continue
        # Check that assistant hasn't used their action
        try:
            _check_condition_action_limit(db, aid, pack)
        except LoreKitError:
            lines.append(f"TEAM: assistant #{aid} cannot act — skipped")
            continue

        # Optionally check same zone
        if same_zone:
            from lorekit.encounter import _get_active_encounter

            enc = _get_active_encounter(db, attacker.session_id)
            if enc:
                enc_id = enc[0]
                atk_zone = db.execute(
                    "SELECT zone_id FROM character_zone WHERE encounter_id = ? AND character_id = ?",
                    (enc_id, attacker.character_id),
                ).fetchone()
                ast_zone = db.execute(
                    "SELECT zone_id FROM character_zone WHERE encounter_id = ? AND character_id = ?",
                    (enc_id, aid),
                ).fetchone()
                if atk_zone and ast_zone and atk_zone[0] != ast_zone[0]:
                    lines.append(f"TEAM: assistant #{aid} not in same zone — skipped")
                    continue

        valid_count += 1
        _increment_turn_actions(db, aid)

    if valid_count == 0:
        return 0, 0

    atk_bonus = min(valid_count * bonus_per, max_bonus)
    dc_bonus = valid_count * dc_per
    lines.append(f"TEAM ATTACK: {valid_count} assistant(s) → +{atk_bonus} attack, +{dc_bonus} DC")
    return atk_bonus, dc_bonus


# ---------------------------------------------------------------------------
# Pre-resolution filters — immunity, impervious
# ---------------------------------------------------------------------------


def _check_pre_resolution(
    pack: SystemPack,
    defender: CharacterData,
    action_def: dict,
    damage_rank: int | None,
    lines: list[str],
) -> str | None:
    """Check pre-resolution filters. Returns 'immune'|'impervious'|None.

    Reads ``resolution.pre_resolution`` from the system pack for:
    - immunity_tags: if defender has ``{prefix}{descriptor}`` attribute ≥ 1,
      skip entire resolution.
    - impervious: if defender has ``{prefix}{resistance_stat}`` attribute
      and ``damage_rank ≤ floor(stat / 2)``, skip resistance roll.
    """
    pre_res = pack.resolution.get("pre_resolution")
    if not pre_res:
        return None

    # Immunity check: defender attribute prefix match against action descriptor
    immunity_cfg = pre_res.get("immunity_tags")
    if immunity_cfg:
        prefix = immunity_cfg["attribute_prefix"]
        match_field = immunity_cfg["match_field"]
        descriptor = action_def.get(match_field)
        if descriptor:
            key = f"{prefix}{descriptor}"
            for cat_attrs in defender.attributes.values():
                if key in cat_attrs and int(cat_attrs[key]) > 0:
                    lines.append(f"IMMUNE: {defender.name} is immune to {descriptor}")
                    return "immune"

    # Impervious check: if damage_rank <= floor(stat / 2), auto-succeed
    if damage_rank is not None:
        impervious_cfg = pre_res.get("impervious")
        if impervious_cfg:
            prefix = impervious_cfg["attribute_prefix"]
            resistance_stat = action_def.get("resistance_stat", pack.resolution.get("resistance_stat", ""))
            stat_key = f"{prefix}{resistance_stat}"
            try:
                stat_val = _get_derived(defender, stat_key)
                threshold = stat_val // 2
                if damage_rank <= threshold:
                    lines.append(f"IMPERVIOUS: rank {damage_rank} ≤ {stat_key} {stat_val}÷2 = {threshold}")
                    return "impervious"
            except LoreKitError:
                pass

    return None


# ---------------------------------------------------------------------------
# Contested roll — optional mode for any action
# ---------------------------------------------------------------------------


def _contested_roll(
    pack: SystemPack,
    attacker: CharacterData,
    defender: CharacterData,
    action_def: dict,
) -> tuple[int, int, int, int | None, int, int | None]:
    """Roll a contested check. Returns (atk_roll, atk_total, def_total, def_roll, def_bonus, atk_natural).

    def_roll is None when the defender uses a static DC.
    atk_natural is the raw die face (for crit detection), None for multi-die.
    """
    attack_stat = action_def["attack_stat"]
    defense_stat = action_def["defense_stat"]

    atk_bonus = _get_derived(attacker, attack_stat)
    def_bonus = _get_derived(defender, defense_stat)

    atk_result = roll_expr(pack.dice)
    atk_roll = atk_result["total"]
    atk_natural = atk_result["natural"]

    # Apply die floor (e.g. Skill Mastery: take 10)
    try:
        floor_val = _get_derived(attacker, f"floor_{attack_stat}")
        if floor_val and atk_roll < floor_val:
            atk_roll = floor_val
    except LoreKitError:
        pass

    atk_total = atk_roll + atk_bonus

    if action_def.get("contested"):
        def_result = roll_expr(pack.dice)
        def_roll = def_result["total"]
        def_total = def_roll + def_bonus
    else:
        def_roll = None
        def_total = def_bonus

    return atk_roll, atk_total, def_total, def_roll, def_bonus, atk_natural


# ---------------------------------------------------------------------------
# Threshold resolution (PF2e-style)
# ---------------------------------------------------------------------------


def _resolve_threshold(
    db,
    pack: SystemPack,
    attacker: CharacterData,
    defender: CharacterData,
    action_def: dict,
    options: dict,
) -> str:
    """Resolve an action using threshold (hit if roll >= defense).

    Supports both static defense and contested rolls (both sides roll).
    On hit, applies all declared on_hit effects (damage, modifiers, push).
    """
    attack_stat = action_def["attack_stat"]
    defense_stat = action_def["defense_stat"]

    crit_cfg = pack.resolution.get("critical")

    # Apply trade options
    trade_adj: dict[str, int] = {}
    trade_mod_lines: list[str] = []
    for trade in options.get("trade", []):
        trade_val = trade["value"]
        from_stat = trade.get("from")
        if from_stat:
            trade_adj[from_stat] = trade_adj.get(from_stat, 0) - trade_val
        trade_adj[trade["to"]] = trade_adj.get(trade["to"], 0) + trade_val

    # Apply persistent trade cost modifiers to the attacker (e.g. All-out Attack penalties)
    _apply_trade_modifiers(db, attacker, options, trade_mod_lines)

    # Gather resolution effects from defender's active conditions
    res_effects = _get_defender_resolution_effects(db, defender.character_id, pack)
    range_type = action_def.get("range")
    atk_bonus_map = res_effects.get("attacker_bonus", {})
    cond_atk_bonus = atk_bonus_map.get(range_type, 0) if range_type else 0

    if action_def.get("contested"):
        atk_roll, atk_total, def_total, def_roll, def_bonus, atk_natural = _contested_roll(
            pack,
            attacker,
            defender,
            action_def,
        )
        atk_bonus = _get_derived(attacker, attack_stat)
        if attack_stat in trade_adj:
            atk_total += trade_adj[attack_stat]
            atk_bonus += trade_adj[attack_stat]
        if cond_atk_bonus:
            atk_total += cond_atk_bonus
            atk_bonus += cond_atk_bonus

        lines = [f"ACTION: {attacker.name} → {defender.name}"]
        lines.append(f"ATTACKER: {pack.dice}({atk_roll}) + {atk_bonus} ({attack_stat}) = {atk_total}")
        lines.append(f"DEFENDER: {pack.dice}({def_roll}) + {def_bonus} ({defense_stat}) = {def_total}")

        is_natural_crit = _is_crit(crit_cfg, atk_natural, attacker)
        hit = atk_total >= def_total
        is_crit = False
        if is_natural_crit and crit_cfg.get("degree_shift", 0) > 0:
            if hit:
                is_crit = True
            else:
                hit = True  # miss upgraded to hit
        if hit and res_effects.get("hits_are_critical"):
            is_crit = True

        # Miss chance (e.g. concealment) — percentile roll converts hit to miss
        miss_chance = res_effects.get("miss_chance", 0.0)
        if hit and miss_chance > 0.0:
            miss_roll = random.random()
            if miss_roll < miss_chance:
                hit = False
                is_crit = False
                lines.append(f"MISS CHANCE: {miss_chance * 100:.0f}% — roll {miss_roll * 100:.1f}% — miss!")

        if hit:
            margin = atk_total - def_total
            if is_crit:
                lines.append(f"CRITICAL HIT! (wins by {margin})")
            else:
                lines.append(f"HIT! (wins by {margin})")
            on_hit = action_def.get("on_hit", {})
            _apply_on_hit(db, pack, attacker, defender, on_hit, lines, is_crit=is_crit, margin=margin, options=options)
        else:
            margin = def_total - atk_total
            lines.append(f"MISS! ({defender.name} resists by {margin})")
    elif action_def.get("_auto_hit"):
        # Area auto-hit: skip attack roll entirely
        lines = [
            f"ACTION: {attacker.name} → {defender.name}",
            "ATTACK: auto-hit (area effect)",
        ]
        hit = True
        is_crit = False

        on_hit = action_def.get("on_hit", {})
        _apply_on_hit(db, pack, attacker, defender, on_hit, lines, is_crit=False, margin=0, options=options)
    else:
        attack_bonus = _get_derived(attacker, attack_stat)
        defense_value = _get_derived(defender, defense_stat)
        if attack_stat in trade_adj:
            attack_bonus += trade_adj[attack_stat]
        if cond_atk_bonus:
            attack_bonus += cond_atk_bonus

        roll_result = roll_expr(pack.dice)
        roll_val = roll_result["total"]
        natural = roll_result["natural"]
        attack_total = roll_val + attack_bonus

        lines = [
            f"ACTION: {attacker.name} → {defender.name}",
            f"ATTACK: {pack.dice}({roll_val}) + {attack_bonus} = {attack_total} vs {defense_stat} {defense_value}",
        ]

        is_natural_crit = _is_crit(crit_cfg, natural, attacker)
        hit = attack_total >= defense_value
        is_crit = False
        if is_natural_crit and crit_cfg.get("degree_shift", 0) > 0:
            if hit:
                is_crit = True
            else:
                hit = True  # miss upgraded to hit
        if hit and res_effects.get("hits_are_critical"):
            is_crit = True

        # Miss chance (e.g. concealment) — percentile roll converts hit to miss
        miss_chance = res_effects.get("miss_chance", 0.0)
        if hit and miss_chance > 0.0:
            miss_roll = random.random()
            if miss_roll < miss_chance:
                hit = False
                is_crit = False
                lines.append(f"MISS CHANCE: {miss_chance * 100:.0f}% — roll {miss_roll * 100:.1f}% — miss!")

        if hit:
            margin = attack_total - defense_value
            if is_crit:
                lines.append("CRITICAL HIT!")
            else:
                lines.append("HIT!")
            on_hit = action_def.get("on_hit", {})
            _apply_on_hit(db, pack, attacker, defender, on_hit, lines, is_crit=is_crit, margin=margin, options=options)
        else:
            lines.append("MISS!")
            margin = defense_value - attack_total
            lines.append(f"Missed by {margin}")

    lines.extend(trade_mod_lines)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Degree resolution (mm3e-style)
# ---------------------------------------------------------------------------


def _resolve_degree(
    db,
    pack: SystemPack,
    attacker: CharacterData,
    defender: CharacterData,
    action_def: dict,
    options: dict,
) -> str:
    """Resolve an action using degree of failure system.

    Supports both static defense and contested rolls. On hit, runs a
    resistance check (if damage_rank_stat is set) or applies on_hit
    effects directly.
    """
    resolution = pack.resolution
    attack_stat = action_def["attack_stat"]
    defense_stat = action_def["defense_stat"]
    dc_offset = resolution.get("defense_dc_offset", 10)
    crit_cfg = resolution.get("critical")

    # Pre-resolution: immunity check (before any rolls)
    pre_res_result = _check_pre_resolution(
        pack,
        defender,
        action_def,
        damage_rank=None,
        lines=[],
    )
    if pre_res_result == "immune":
        return f"ACTION: {attacker.name} → {defender.name}\nIMMUNE: {defender.name} is immune to {action_def.get('descriptor', 'this effect')}"

    # Apply trade options (e.g. power_attack: -N attack / +N damage)
    trade_adj: dict[str, int] = {}
    trade_mod_lines: list[str] = []
    for trade in options.get("trade", []):
        trade_val = trade["value"]
        from_stat = trade.get("from")
        if from_stat:
            trade_adj[from_stat] = trade_adj.get(from_stat, 0) - trade_val
        trade_adj[trade["to"]] = trade_adj.get(trade["to"], 0) + trade_val

    # Apply persistent trade cost modifiers to the attacker (e.g. All-out Attack penalties)
    _apply_trade_modifiers(db, attacker, options, trade_mod_lines)

    # Team/combined attack bonus
    team_atk_bonus, team_dc_bonus = _apply_team_bonus(db, pack, attacker, options, trade_mod_lines)

    # Reaction hook: before_attack (e.g. Interpose — substitute defender)
    reaction_mods = _check_reactions(db, pack, "before_attack", attacker, defender, action_def, trade_mod_lines)
    if reaction_mods.get("new_defender_id"):
        defender = load_character_data(db, reaction_mods["new_defender_id"])

    # Gather resolution effects from defender's active conditions
    res_effects = _get_defender_resolution_effects(db, defender.character_id, pack)
    use_routine = res_effects.get("attacker_routine_check", False)
    routine_value = resolution.get("routine_value", 10)

    # Determine range-based attack bonus from defender conditions
    range_type = action_def.get("range")
    atk_bonus_map = res_effects.get("attacker_bonus", {})
    cond_atk_bonus = atk_bonus_map.get(range_type, 0) if range_type else 0

    # Reaction hook: replace_defense (e.g. Deflect — use reactor stat as defense)
    defense_mods = _check_reactions(db, pack, "replace_defense", attacker, defender, action_def, trade_mod_lines)

    if action_def.get("contested"):
        atk_roll, atk_total, def_total, def_roll, def_bonus, atk_natural = _contested_roll(
            pack,
            attacker,
            defender,
            action_def,
        )
        atk_bonus = _get_derived(attacker, attack_stat)
        # Apply trade to attack total
        if attack_stat in trade_adj:
            atk_total += trade_adj[attack_stat]
            atk_bonus += trade_adj[attack_stat]
        # Apply condition-based attack bonus
        if cond_atk_bonus:
            atk_total += cond_atk_bonus
            atk_bonus += cond_atk_bonus
        # Apply team attack bonus
        if team_atk_bonus:
            atk_total += team_atk_bonus
            atk_bonus += team_atk_bonus

        lines = [f"ACTION: {attacker.name} → {defender.name}"]
        lines.append(f"ATTACKER: {pack.dice}({atk_roll}) + {atk_bonus} ({attack_stat}) = {atk_total}")
        lines.append(f"DEFENDER: {pack.dice}({def_roll}) + {def_bonus} ({defense_stat}) = {def_total}")
        hit = atk_total >= def_total
        is_natural_crit = _is_crit(crit_cfg, atk_natural, attacker)
    elif action_def.get("_auto_hit"):
        # Area auto-hit: skip attack roll entirely
        lines = [
            f"ACTION: {attacker.name} → {defender.name}",
            "ATTACK: auto-hit (area effect)",
        ]
        attack_total = 0
        defense_dc = 0
        hit = True
        is_natural_crit = False
    else:
        attack_bonus = _get_derived(attacker, attack_stat)
        defense_value = defense_mods.get("defense_override", _get_derived(defender, defense_stat))

        # Apply trade to attack bonus
        if attack_stat in trade_adj:
            attack_bonus += trade_adj[attack_stat]
        # Apply condition-based attack bonus
        if cond_atk_bonus:
            attack_bonus += cond_atk_bonus
        # Apply team attack bonus
        if team_atk_bonus:
            attack_bonus += team_atk_bonus

        # Routine check: use routine_value instead of rolling (e.g. defenseless target)
        if use_routine:
            roll_val = routine_value
            natural = routine_value
            lines = [
                f"ACTION: {attacker.name} → {defender.name}",
                f"ATTACK: routine({routine_value}) + {attack_bonus} = {routine_value + attack_bonus} vs DC {dc_offset + defense_value}",
            ]
        else:
            roll_result = roll_expr(pack.dice)
            roll_val = roll_result["total"]
            natural = roll_result["natural"]
            lines = [
                f"ACTION: {attacker.name} → {defender.name}",
                f"ATTACK: {pack.dice}({roll_val}) + {attack_bonus} = {roll_val + attack_bonus} vs DC {dc_offset + defense_value}",
            ]
        attack_total = roll_val + attack_bonus
        defense_dc = dc_offset + defense_value

        hit = attack_total >= defense_dc
        is_natural_crit = _is_crit(crit_cfg, natural, attacker)

    # Apply degree_shift from crit config (miss upgraded to hit)
    if is_natural_crit and crit_cfg.get("degree_shift", 0) > 0 and not hit:
        hit = True

    # Resolution effect: hits_are_critical (e.g. defenseless)
    if hit and res_effects.get("hits_are_critical"):
        is_natural_crit = True  # treat as crit for effect rank bonus

    # Miss chance (e.g. concealment) — percentile roll converts hit to miss
    miss_chance = res_effects.get("miss_chance", 0.0)
    if hit and miss_chance > 0.0:
        miss_roll = random.random()
        if miss_roll < miss_chance:
            hit = False
            is_natural_crit = False
            lines.append(f"MISS CHANCE: {miss_chance * 100:.0f}% — roll {miss_roll * 100:.1f}% — miss!")

    if hit:
        # Compute margin for on_hit effects (e.g. value_min_margin)
        if action_def.get("contested"):
            hit_margin = atk_total - def_total
        else:
            hit_margin = attack_total - defense_dc
        lines.append("HIT!")

        # If action has damage_rank_stat or effect_rank, run resistance check
        damage_rank_stat = action_def.get("damage_rank_stat")
        effect_rank_direct = action_def.get("effect_rank")

        if damage_rank_stat or effect_rank_direct is not None:
            # Per-action resistance stat override (e.g. Fortitude for mental powers)
            resistance_stat = action_def.get("resistance_stat", resolution.get("resistance_stat"))
            dc_base = resolution.get("dc_base", 15)

            if effect_rank_direct is not None:
                damage_rank = int(effect_rank_direct)
            else:
                damage_rank = _get_derived(attacker, damage_rank_stat)

            # Data-driven cap check (e.g. attack + effect ≤ pl_limit)
            cap = action_def.get("cap")
            if cap:
                cap_stats = cap["sum"]
                cap_max_stat = cap["max_stat"]
                cap_values = []
                for cs in cap_stats:
                    if cs == "effect_rank" and effect_rank_direct is not None:
                        cap_values.append(damage_rank)
                    elif cs == "attack_stat":
                        cap_values.append(_get_derived(attacker, attack_stat))
                    else:
                        cap_values.append(_get_derived(attacker, cs))
                cap_total = sum(cap_values)
                cap_max = _get_derived(attacker, cap_max_stat)
                if cap_total > cap_max:
                    parts = " + ".join(str(v) for v in cap_values)
                    lines.append(f"WARNING: cap exceeded — {parts} = {cap_total} > {cap_max}")

            # Apply trade to damage rank (e.g. Power Attack)
            if damage_rank_stat and damage_rank_stat in trade_adj:
                damage_rank += trade_adj[damage_rank_stat]

            # Multiattack DC bonus: higher hit margin → higher resistance DC
            multiattack_cfg = action_def.get("multiattack")
            if multiattack_cfg and isinstance(multiattack_cfg, dict):
                thresholds = multiattack_cfg.get("dc_bonus_thresholds", [])
                ma_bonus = 0
                for t in sorted(thresholds, key=lambda x: x["margin"], reverse=True):
                    if hit_margin >= t["margin"]:
                        ma_bonus = t["bonus"]
                        break
                if ma_bonus:
                    damage_rank += ma_bonus
                    lines.append(f"MULTIATTACK: hit margin {hit_margin} → +{ma_bonus} effect rank (now {damage_rank})")

            # Apply team attack DC bonus
            if team_dc_bonus:
                damage_rank += team_dc_bonus
                lines.append(f"TEAM DC BONUS: +{team_dc_bonus} effect rank (now {damage_rank})")

            # Apply critical effect_rank_bonus (e.g. mm3e nat 20 → +5 effect rank)
            if is_natural_crit:
                effect_rank_bonus = crit_cfg.get("effect_rank_bonus", 0)
                if effect_rank_bonus:
                    damage_rank += effect_rank_bonus
                    lines.append(f"CRITICAL! Effect rank +{effect_rank_bonus} (rank {damage_rank})")

            # Pre-resolution: impervious check (after damage_rank is finalized)
            pre_res_result = _check_pre_resolution(
                pack,
                defender,
                action_def,
                damage_rank=damage_rank,
                lines=lines,
            )
            if pre_res_result == "impervious":
                lines.append("RESULT: No effect (impervious)")
                return "\n".join(lines)

            resistance_bonus = _get_derived(defender, resistance_stat)
            resist_result = roll_expr(pack.dice)
            resist_roll = resist_result["total"]
            resistance_total = resist_roll + resistance_bonus
            resist_dc = dc_base + damage_rank

            lines.append(
                f"RESISTANCE: {pack.dice}({resist_roll}) + {resistance_bonus} = {resistance_total} vs DC {resist_dc}"
            )

            if resistance_total >= resist_dc:
                lines.append("RESULT: No effect")
            else:
                margin_fail = resist_dc - resistance_total
                degree_step = resolution.get("degree_step", 5)
                degree = 1 + math.floor(margin_fail / degree_step)
                degree = max(1, min(degree, 4))

                # Character resolution tags (e.g. minion → escalate to max degree)
                char_tags_cfg = resolution.get("character_tags", {})
                for tag_name, tag_rules in char_tags_cfg.items():
                    tag_key = tag_name if tag_name.startswith("is_") else f"is_{tag_name}"
                    for cat_attrs in defender.attributes.values():
                        if tag_key in cat_attrs and int(cat_attrs[tag_key]) > 0:
                            min_deg = tag_rules.get("min_failure_degree")
                            if min_deg is not None and degree < min_deg:
                                lines.append(f"TAG [{tag_name}]: degree escalated {degree} → {min_deg}")
                                degree = min_deg
                            break

                # Cumulative degree tracking: stack degrees across hits
                if action_def.get("cumulative"):
                    action_name = action_def.get("_action_name", "affliction")
                    track_key = f"_cumulative_degree_{action_name}"
                    try:
                        current_degree = _get_derived(defender, track_key)
                    except LoreKitError:
                        current_degree = 0
                    max_degree = action_def.get("max_degree", 4)
                    new_degree = min(current_degree + degree, max_degree)
                    if current_degree > 0:
                        lines.append(f"CUMULATIVE: previous degree {current_degree} + {degree} = {new_degree}")
                    degree = new_degree
                    _write_attr(db, defender.character_id, track_key, degree)

                # Look up per-action outcome table, fall back to global on_failure
                outcome_table_name = action_def.get("outcome_table")
                if outcome_table_name and outcome_table_name in pack.outcome_tables:
                    outcome_table = pack.outcome_tables[outcome_table_name]
                else:
                    outcome_table = resolution.get("on_failure", {})

                effect = dict(outcome_table.get(str(degree), {}))

                # Resolve template variables from action_def.degrees
                # e.g. "{degree_1_condition}" → "dazed" from degrees: {"1": "dazed"}
                degrees_map = action_def.get("degrees", {})
                if degrees_map:
                    for key, val in list(effect.items()):
                        if isinstance(val, str) and "{" in val:
                            for deg_key, choice in degrees_map.items():
                                placeholder = f"{{degree_{deg_key}_condition}}"
                                if placeholder in val:
                                    resolved = choice if isinstance(choice, str) else choice[0]
                                    val = val.replace(placeholder, resolved)
                            effect[key] = val

                lines.append(f"DEGREE OF FAILURE: {degree}")
                _apply_degree_effect(db, defender, effect, lines)

                # Sync condition modifiers after damage/stat changes
                _sync_and_recalc(db, defender.character_id, pack, lines)

                # Fire on-damage triggers (e.g. concentration break)
                _fire_damage_triggers(db, pack, defender.character_id, damage_rank, lines)
        else:
            # No resistance check — apply on_hit effects directly
            on_hit = action_def.get("on_hit", {})
            _apply_on_hit(db, pack, attacker, defender, on_hit, lines, margin=hit_margin, options=options)
        # Reaction hook: after_hit
        after_hit_mods = _check_reactions(db, pack, "after_hit", attacker, defender, action_def, lines)
        if after_hit_mods.get("free_attack"):
            fa = after_hit_mods["free_attack"]
            try:
                counter_result = resolve_action(
                    db,
                    fa["reactor_id"],
                    fa["target_id"],
                    fa["action"],
                    pack.pack_dir,
                    options={"free_action": True},
                )
                lines.append(counter_result)
            except LoreKitError as e:
                lines.append(f"COUNTER FAILED: {e}")
    else:
        lines.append("MISS!")
        if not action_def.get("contested"):
            margin = defense_dc - attack_total
            lines.append(f"Missed by {margin}")
        else:
            margin = def_total - atk_total
            lines.append(f"{defender.name} resists by {margin}")

        # Reaction hook: after_miss
        after_miss_mods = _check_reactions(db, pack, "after_miss", attacker, defender, action_def, lines)
        if after_miss_mods.get("free_attack"):
            fa = after_miss_mods["free_attack"]
            try:
                counter_result = resolve_action(
                    db,
                    fa["reactor_id"],
                    fa["target_id"],
                    fa["action"],
                    pack.pack_dir,
                    options={"free_action": True},
                )
                lines.append(counter_result)
            except LoreKitError as e:
                lines.append(f"COUNTER FAILED: {e}")

    # Homing: on miss, defer re-attack to attacker's next turn
    if not hit and action_def.get("homing"):
        import json as _json

        homing_ranks = action_def.get("homing")
        retries = homing_ranks if isinstance(homing_ranks, int) else 1
        action_name = action_def.get("_action_name", "unknown")
        metadata = _json.dumps(
            {
                "action": action_name,
                "target_id": defender.character_id,
                "retries_left": retries,
            }
        )
        db.execute(
            "INSERT INTO combat_state "
            "(character_id, source, target_stat, modifier_type, value, "
            "duration_type, applied_by, metadata) "
            "VALUES (?, ?, '_deferred', 'deferred', 0, 'deferred_homing', ?, ?) "
            "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET metadata = excluded.metadata",
            (attacker.character_id, f"homing:{action_name}", defender.character_id, metadata),
        )
        db.commit()
        lines.append(f"HOMING: attack will retry on {attacker.name}'s next turn ({retries} attempt(s) left)")

    # Contagious: copy contagious modifiers from defender to attacker on contact
    if hit:
        _check_contagious(db, pack, attacker, defender, action_def, lines)

    lines.extend(trade_mod_lines)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Contagious modifier spreading
# ---------------------------------------------------------------------------


def _check_contagious(
    db,
    pack: SystemPack,
    attacker: CharacterData,
    defender: CharacterData,
    action_def: dict,
    lines: list[str],
) -> None:
    """Copy contagious modifiers from defender to attacker on contact.

    Each contagious modifier declares its own ``spread_range`` in metadata
    (defaults to ``"melee"``). The action's range must match for spreading.
    """
    import json as _json

    action_range = action_def.get("range", "")

    rows = db.execute(
        "SELECT source, target_stat, modifier_type, value, bonus_type, "
        "duration_type, duration, save_stat, save_dc, metadata "
        "FROM combat_state WHERE character_id = ? AND metadata IS NOT NULL",
        (defender.character_id,),
    ).fetchall()

    for source, target_stat, mod_type, value, bonus_type, dur_type, duration, save_stat, save_dc, meta_str in rows:
        try:
            metadata = _json.loads(meta_str)
        except (ValueError, TypeError):
            continue
        if not metadata.get("contagious"):
            continue

        # Check if action range matches the spread requirement
        spread_range = metadata.get("spread_range", "melee")
        if spread_range != "any" and action_range != spread_range:
            continue

        new_source = f"contagious:{source}"
        db.execute(
            "INSERT INTO combat_state "
            "(character_id, source, target_stat, modifier_type, value, bonus_type, "
            "duration_type, duration, save_stat, save_dc, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(character_id, source, target_stat) DO NOTHING",
            (
                attacker.character_id,
                new_source,
                target_stat,
                mod_type,
                value,
                bonus_type,
                dur_type,
                duration,
                save_stat,
                save_dc,
                meta_str,
            ),
        )
        lines.append(f"CONTAGIOUS: {attacker.name} contracted {source} from {defender.name}")

    db.commit()
    if rows:
        _sync_and_recalc(db, attacker.character_id, pack, lines)


# ---------------------------------------------------------------------------
# End-of-turn duration ticking
# ---------------------------------------------------------------------------


def end_turn(db, character_id: int, pack_dir: str) -> str:
    """Tick durations on a character's combat modifiers at end of turn.

    Reads the system pack's end_turn config, processes each active modifier
    according to its duration_type's declared tick behavior, and returns a
    summary of what changed.

    Tick behaviors:
    - decrement: subtract 1 from duration, remove at remove_at (default 0)
    - check: roll a save (save_stat vs save_dc on the modifier row),
      remove on success if remove_on="success"
    """
    from cruncher.dice import roll_expr

    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    if not pack.end_turn:
        return f"END TURN: {char.name} — no end_turn config in system pack"

    # Auto-checkpoint before ticking so turn_revert can undo
    from lorekit.support.checkpoint import create_checkpoint

    create_checkpoint(db, char.session_id)

    # Load all active combat_state rows for this character
    rows = db.execute(
        "SELECT id, source, target_stat, value, duration_type, duration, "
        "save_stat, save_dc, applied_by FROM combat_state WHERE character_id = ?",
        (character_id,),
    ).fetchall()

    if not rows:
        return f"END TURN: {char.name} — no active modifiers"

    lines = [f"END TURN: {char.name}"]
    removed_any = False

    for row_id, source, target_stat, value, dur_type, duration, save_stat, save_dc, applied_by in rows:
        tick_cfg = pack.end_turn.get(dur_type)
        if tick_cfg is None:
            continue  # duration type not configured for ticking

        action = tick_cfg.get("action")

        if action == "decrement":
            remove_at = tick_cfg.get("remove_at", 0)
            if duration is None:
                continue  # no duration set, nothing to decrement
            new_dur = duration - 1
            if new_dur <= remove_at:
                db.execute(
                    "DELETE FROM combat_state WHERE id = ?",
                    (row_id,),
                )
                lines.append(f"  EXPIRED: {source} ({target_stat} {value:+d}) — removed")
                removed_any = True
            else:
                db.execute(
                    "UPDATE combat_state SET duration = ? WHERE id = ?",
                    (new_dur, row_id),
                )
                lines.append(f"  TICKED: {source} ({new_dur} rounds remaining)")

        elif action == "check":
            remove_on = tick_cfg.get("remove_on", "success")
            if not save_stat or save_dc is None:
                lines.append(f"  SKIPPED: {source} — missing save_stat/save_dc")
                continue

            # Read the character's derived stat for the save
            derived = char.attributes.get("derived", {})
            bonus_str = derived.get(save_stat)
            if bonus_str is None:
                lines.append(f"  SKIPPED: {source} — save stat '{save_stat}' not found")
                continue

            bonus = int(bonus_str)
            result = roll_expr(pack.dice)
            roll_val = result["total"]
            total = roll_val + bonus
            success = total >= save_dc

            outcome_str = "SUCCESS" if success else "FAILURE"
            lines.append(
                f"  SAVE: {source} — {save_stat} "
                f"{pack.dice}({roll_val}) + {bonus} = {total} vs DC {save_dc} "
                f"→ {outcome_str}"
            )

            should_remove = (remove_on == "success" and success) or (remove_on == "failure" and not success)
            if should_remove:
                db.execute(
                    "DELETE FROM combat_state WHERE id = ?",
                    (row_id,),
                )
                lines.append(f"    REMOVED: {source} ({target_stat} {value:+d})")
                removed_any = True

        elif action == "escape_check":
            # Roll character's escape stat vs the source's DC stat
            escape_stat = tick_cfg.get("save_stat")
            dc_stat = tick_cfg.get("save_dc_stat")
            if not escape_stat or not dc_stat:
                lines.append(f"  SKIPPED: {source} — missing save_stat/save_dc_stat in end_turn config")
                continue

            derived = char.attributes.get("derived", {})
            bonus_str = derived.get(escape_stat)
            if bonus_str is None:
                lines.append(f"  SKIPPED: {source} — escape stat '{escape_stat}' not found")
                continue

            bonus = int(bonus_str)

            # Look up DC from the applied_by character's derived stats
            dc_val = 0
            if applied_by:
                source_char = load_character_data(db, applied_by)
                source_derived = source_char.attributes.get("derived", {})
                dc_str = source_derived.get(dc_stat)
                if dc_str is not None:
                    dc_val = int(dc_str)

            result = roll_expr(pack.dice)
            roll_val = result["total"]
            total = roll_val + bonus
            success = total >= dc_val

            outcome_str = "ESCAPED" if success else "HELD"
            lines.append(
                f"  ESCAPE: {source} — {escape_stat} "
                f"{pack.dice}({roll_val}) + {bonus} = {total} vs {dc_stat} {dc_val} "
                f"→ {outcome_str}"
            )

            if success:
                db.execute(
                    "DELETE FROM combat_state WHERE id = ?",
                    (row_id,),
                )
                lines.append(f"    FREED: {source} ({target_stat} {value:+d}) — removed")
                removed_any = True

        elif action == "modify_attribute":
            attr_key = tick_cfg.get("attribute")
            if not attr_key:
                continue
            delta = tick_cfg.get("delta", -1)
            floor_val = tick_cfg.get("floor")
            ceiling_val = tick_cfg.get("ceiling")
            try:
                current = _get_derived(char, attr_key)
            except LoreKitError:
                current = 0
            new_val = current + delta
            if floor_val is not None:
                new_val = max(int(floor_val), new_val)
            if ceiling_val is not None:
                new_val = min(int(ceiling_val), new_val)
            if new_val != current:
                _write_attr(db, character_id, attr_key, new_val)
                lines.append(f"  TICK: {source} — {attr_key}: {current} → {new_val}")
                removed_any = True  # trigger recalc

        elif action == "auto_save":
            save_stat_cfg = tick_cfg.get("save_stat")
            dc_cfg = tick_cfg.get("dc", 15)
            if not save_stat_cfg:
                lines.append(f"  SKIPPED: {source} — missing save_stat in auto_save config")
                continue

            derived = char.attributes.get("derived", {})
            bonus = int(derived.get(save_stat_cfg, 0))
            result = roll_expr(pack.dice)
            total = result["total"] + bonus
            success = total >= dc_cfg

            lines.append(
                f"  AUTO-SAVE: {source} — {save_stat_cfg} "
                f"{pack.dice}({result['total']}) + {bonus} = {total} vs DC {dc_cfg} "
                f"→ {'SUCCESS' if success else 'FAILURE'}"
            )

            outcome = tick_cfg.get("on_success", {}) if success else tick_cfg.get("on_failure", {})
            if outcome:
                _apply_degree_effect(db, char, outcome, lines)
                removed_any = True  # trigger recalc

        elif action == "worsen":
            track_attr = tick_cfg.get("attribute", f"{source}_degree")
            max_degree = tick_cfg.get("max_degree", 3)
            try:
                current = _get_derived(char, track_attr)
            except LoreKitError:
                current = 0
            if current < max_degree:
                new_val = current + 1
                _write_attr(db, character_id, track_attr, new_val)
                lines.append(f"  WORSENED: {source} — {track_attr}: {current} → {new_val}")
                removed_any = True  # trigger recalc
            else:
                lines.append(f"  WORSENED: {source} — already at max degree {max_degree}")

    db.commit()

    # Recompute derived stats if any modifiers were removed
    if removed_any:
        from lorekit.rules import rules_calc as _rules_calc

        recomp = _rules_calc(db, character_id, pack_dir)
        # Extract change lines from recompute output
        for line in recomp.split("\n"):
            if line.startswith("  ") and "→" in line:
                lines.append(f"  RECOMPUTED: {line.strip()}")

    # Sync condition modifiers (conditions may have changed after modifier expiry)
    _sync_and_recalc(db, character_id, pack, lines)

    return "\n".join(lines)


def start_turn(db, character_id: int, pack_dir: str) -> str:
    """Process start-of-turn effects on a character's combat modifiers.

    Reads the system pack's start_turn config and processes each active
    modifier whose duration_type has a declared tick behavior.

    Tick behaviors:
    - remove: delete all modifiers with this duration_type
    - warn: emit a reminder listing active modifiers of this duration_type
    """
    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    if not pack.start_turn:
        return ""

    rows = db.execute(
        "SELECT id, source, target_stat, value, duration_type, duration, metadata "
        "FROM combat_state WHERE character_id = ?",
        (character_id,),
    ).fetchall()

    if not rows:
        return ""

    lines: list[str] = [f"START TURN: {char.name}"]
    removed_any = False
    has_output = False

    # Collect warnings by duration_type
    warn_items: dict[str, list[str]] = {}

    for row_id, source, target_stat, value, dur_type, duration, metadata in rows:
        tick_cfg = pack.start_turn.get(dur_type)
        if tick_cfg is None:
            continue

        action = tick_cfg.get("action")

        if action == "remove":
            db.execute("DELETE FROM combat_state WHERE id = ?", (row_id,))
            lines.append(f"  EXPIRED: {source} ({target_stat} {value:+d}) — removed")
            removed_any = True
            has_output = True

        elif action == "warn":
            warn_items.setdefault(dur_type, []).append(f"{source} ({target_stat} {value:+d})")

        elif action == "replenish":
            # Reset reaction uses (e.g. reaction duration back to 1)
            reset_to = tick_cfg.get("reset_to", 1)
            if duration < reset_to:
                db.execute(
                    "UPDATE combat_state SET duration = ? WHERE id = ?",
                    (reset_to, row_id),
                )
                lines.append(f"  REPLENISHED: {source} (reaction ready)")
                has_output = True

        elif action == "retry_action":
            # Homing: retry a deferred attack
            import json as _json

            try:
                meta = _json.loads(metadata) if metadata else None
            except (ValueError, TypeError):
                meta = None
            if not meta:
                continue

            retry_action = meta.get("action")
            retry_target = meta.get("target_id")
            retries_left = meta.get("retries_left", 1)

            if retry_action and retry_target:
                lines.append(f"  HOMING RETRY: {source} → re-attacking")
                try:
                    result = resolve_action(
                        db,
                        character_id,
                        retry_target,
                        retry_action,
                        pack_dir,
                        options={"free_action": True},
                    )
                    lines.append(f"    {result}")
                    hit_retry = "HIT" in result
                except LoreKitError as e:
                    lines.append(f"    RETRY FAILED: {e}")
                    hit_retry = False

                if hit_retry or retries_left <= 1:
                    db.execute("DELETE FROM combat_state WHERE id = ?", (row_id,))
                    removed_any = True
                else:
                    meta["retries_left"] = retries_left - 1
                    db.execute(
                        "UPDATE combat_state SET metadata = ? WHERE id = ?",
                        (_json.dumps(meta), row_id),
                    )
                has_output = True

    # Emit sustain warnings
    for dur_type, items in warn_items.items():
        lines.append(f"  SUSTAINED: {', '.join(items)} — free action required to maintain each")
        has_output = True

    db.commit()

    if removed_any:
        from lorekit.rules import rules_calc as _rules_calc

        recomp = _rules_calc(db, character_id, pack_dir)
        for line in recomp.split("\n"):
            if line.startswith("  ") and "→" in line:
                lines.append(f"  RECOMPUTED: {line.strip()}")

        _sync_and_recalc(db, character_id, pack, lines)

    return "\n".join(lines) if has_output else ""


# ---------------------------------------------------------------------------
# Area avoidance helpers
# ---------------------------------------------------------------------------


def _get_area_effect_rank(attacker: CharacterData, action_def: dict, trade_adj: dict[str, int]) -> int:
    """Determine the effect rank for area avoidance DC calculation.

    Mirrors the logic in _resolve_degree for effect_rank vs damage_rank_stat,
    and applies trade adjustments (e.g. Power Attack) so the DC reflects
    the full rank before any avoidance halving.
    """
    effect_rank_direct = action_def.get("effect_rank")
    if effect_rank_direct is not None:
        return int(effect_rank_direct)
    damage_rank_stat = action_def.get("damage_rank_stat")
    if damage_rank_stat:
        rank = _get_derived(attacker, damage_rank_stat)
        if damage_rank_stat in trade_adj:
            rank += trade_adj[damage_rank_stat]
        return rank
    return 0


def _area_avoidance_check(
    pack: SystemPack,
    attacker: CharacterData,
    defender: CharacterData,
    action_def: dict,
    avoidance_cfg: dict,
    trade_adj: dict[str, int],
) -> dict:
    """Run an area avoidance check for one target.

    Returns {"lines": [...], "action_def": possibly-modified action_def}.
    On success the returned action_def has effect_rank overridden
    (with damage_rank_stat removed to prevent double trade adjustment).
    """
    check_stat = avoidance_cfg["check_stat"]
    dc_base = avoidance_cfg.get("dc_base", 10)

    effect_rank = _get_area_effect_rank(attacker, action_def, trade_adj)
    dc = dc_base + effect_rank

    check_bonus = _get_derived(defender, check_stat)
    roll_result = roll_expr(pack.dice)
    roll_val = roll_result["total"]
    check_total = roll_val + check_bonus

    lines = [
        f"AREA AVOIDANCE ({defender.name}): "
        f"{pack.dice}({roll_val}) + {check_bonus} ({check_stat}) = {check_total} vs DC {dc}",
    ]

    modified_def = dict(action_def)

    if check_total >= dc:
        on_success = avoidance_cfg.get("on_success", {})
        multiplier = on_success.get("rank_multiplier")
        if multiplier is not None:
            minimum = on_success.get("minimum_rank", 1)
            reduced = max(minimum, math.floor(effect_rank * multiplier))
            lines.append(f"  SUCCESS — effect rank {effect_rank} → {reduced}")
            modified_def["effect_rank"] = reduced
            modified_def.pop("damage_rank_stat", None)
        else:
            lines.append("  SUCCESS")
    else:
        lines.append(f"  FAILED — full effect (rank {effect_rank})")

    return {"lines": lines, "action_def": modified_def}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_area_action(
    db,
    attacker_id: int,
    action: str,
    pack_dir: str,
    center_zone: str,
    radius: int,
    exclude_self: bool = True,
    options: dict | None = None,
) -> str:
    """Resolve an action against all targets in an area.

    Finds all characters within `radius` zone hops of `center_zone`,
    then runs the standard resolution against each target.
    """
    from lorekit.encounter import (
        _get_active_encounter,
        _get_character_zone,
        _zone_name_to_id,
        get_area_targets,
    )

    pack = load_system_pack(pack_dir)
    attacker = load_character_data(db, attacker_id)

    # Condition-based action limit (dazed, stunned, incapacitated, etc.)
    _check_condition_action_limit(db, attacker_id, pack)

    # Auto-checkpoint
    from lorekit.support.checkpoint import create_checkpoint

    create_checkpoint(db, attacker.session_id)

    action_def = _get_action_def(pack, attacker, action)
    action_def.setdefault("_action_name", action)

    enc = _get_active_encounter(db, attacker.session_id)
    if enc is None:
        raise LoreKitError("No active encounter — area effects require an encounter")

    enc_id = enc[0]

    # Resolve center zone
    if center_zone == "self":
        center_zid = _get_character_zone(db, enc_id, attacker_id)
        if center_zid is None:
            raise LoreKitError(f"{attacker.name} is not placed in the encounter")
    else:
        center_zid = _zone_name_to_id(db, enc_id, center_zone)

    # Collect targets
    exclude_ids = {attacker_id} if exclude_self else set()
    target_ids = get_area_targets(db, enc_id, center_zid, radius, exclude_ids)

    if not target_ids:
        return f"AREA: {attacker.name} uses {action} — no targets in area"

    opts = _expand_combat_options(pack, options or {})
    resolution_type = pack.resolution.get("type", "threshold")
    area_cfg = pack.resolution.get("area")

    # Pre-compute trade adjustments for area avoidance DC calculation
    trade_adj: dict[str, int] = {}
    for trade in opts.get("trade", []):
        trade_val = trade["value"]
        from_stat = trade.get("from")
        if from_stat:
            trade_adj[from_stat] = trade_adj.get(from_stat, 0) - trade_val
        trade_adj[trade["to"]] = trade_adj.get(trade["to"], 0) + trade_val

    results = []
    for tid in target_ids:
        defender = load_character_data(db, tid)

        effective_action_def = dict(action_def)
        avoidance_lines: list[str] = []

        if area_cfg:
            avoidance = area_cfg.get("avoidance")
            if avoidance:
                av_result = _area_avoidance_check(
                    pack,
                    attacker,
                    defender,
                    effective_action_def,
                    avoidance,
                    trade_adj,
                )
                avoidance_lines = av_result["lines"]
                effective_action_def = av_result["action_def"]

            if area_cfg.get("skip_attack_roll"):
                effective_action_def = dict(effective_action_def)
                effective_action_def["_auto_hit"] = True

        if resolution_type == "threshold":
            result = _resolve_threshold(db, pack, attacker, defender, effective_action_def, opts)
        elif resolution_type == "degree":
            result = _resolve_degree(db, pack, attacker, defender, effective_action_def, opts)
        else:
            raise LoreKitError(f"Unknown resolution type: {resolution_type}")

        if avoidance_lines:
            result = "\n".join(avoidance_lines) + "\n" + result

        results.append(result)

    # Area action counts as one action for condition tracking
    _increment_turn_actions(db, attacker_id)

    return "\n---\n".join(results)


# ---------------------------------------------------------------------------
# Power toggle — activate/deactivate sustained powers
# ---------------------------------------------------------------------------


def activate_power(db, character_id: int, ability_name: str, pack_dir: str) -> str:
    """Activate a sustained power, inserting its declared modifiers.

    Reads the ability's JSON description for ``on_activate.apply_modifiers``,
    inserts them as combat_state rows with ``duration_type = "sustained"``,
    and re-runs rules_calc to recompute derived stats.
    """
    import json as _json

    from lorekit.rules import load_character_data, rules_calc

    char = load_character_data(db, character_id)
    pack = load_system_pack(pack_dir)

    # Find the ability
    row = db.execute(
        "SELECT description FROM character_abilities WHERE character_id = ? AND name = ?",
        (character_id, ability_name),
    ).fetchone()
    if not row:
        raise LoreKitError(f"Ability '{ability_name}' not found on {char.name}")

    try:
        desc = _json.loads(row[0])
    except (ValueError, TypeError):
        raise LoreKitError(f"Ability '{ability_name}' has no structured data")

    on_activate = desc.get("on_activate", {})
    modifiers = on_activate.get("apply_modifiers", [])
    if not modifiers:
        raise LoreKitError(f"Ability '{ability_name}' has no on_activate.apply_modifiers")

    lines = [f"ACTIVATE: {ability_name}"]
    source_prefix = ability_name.lower().replace(" ", "_")

    for mod in modifiers:
        source = mod.get("source", source_prefix)
        target_stat = mod["target_stat"]
        value = mod.get("value", 0)
        mod_type = mod.get("modifier_type", "buff")
        dur_type = mod.get("duration_type", "sustained")
        bonus_type = mod.get("bonus_type")

        db.execute(
            "INSERT INTO combat_state "
            "(character_id, source, target_stat, modifier_type, value, bonus_type, duration_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET "
            "value = excluded.value",
            (character_id, source, target_stat, mod_type, value, bonus_type, dur_type),
        )
        lines.append(f"  {source} → {target_stat} {value:+d} ({dur_type})")

    db.commit()
    recomp = rules_calc(db, character_id, pack_dir)
    for line in recomp.split("\n"):
        if line.startswith("  ") and "→" in line:
            lines.append(f"  RECOMPUTED: {line.strip()}")

    _sync_and_recalc(db, character_id, pack, lines)
    return "\n".join(lines)


def deactivate_power(db, character_id: int, ability_name: str, pack_dir: str) -> str:
    """Deactivate a sustained power, removing its modifiers.

    Deletes combat_state rows whose source matches the ability name pattern,
    then re-runs rules_calc.
    """
    from lorekit.rules import load_character_data, rules_calc

    char = load_character_data(db, character_id)
    pack = load_system_pack(pack_dir)
    source_prefix = ability_name.lower().replace(" ", "_")

    deleted = db.execute(
        "DELETE FROM combat_state WHERE character_id = ? AND source = ?",
        (character_id, source_prefix),
    ).rowcount

    if deleted == 0:
        return f"DEACTIVATE: {ability_name} — no active modifiers found"

    db.commit()
    lines = [f"DEACTIVATE: {ability_name} — {deleted} modifier(s) removed"]

    recomp = rules_calc(db, character_id, pack_dir)
    for line in recomp.split("\n"):
        if line.startswith("  ") and "→" in line:
            lines.append(f"  RECOMPUTED: {line.strip()}")

    _sync_and_recalc(db, character_id, pack, lines)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Alternate effect switching
# ---------------------------------------------------------------------------


def switch_alternate(db, character_id: int, array_name: str, alternate_name: str, pack_dir: str) -> str:
    """Switch the active alternate in a power array.

    Deactivates the current alternate's action_override, activates the new
    one, updates the active_alternate tracker, and re-runs rules_calc.
    """
    import json as _json

    from lorekit.rules import load_character_data, rules_calc

    char = load_character_data(db, character_id)

    # Find all abilities in this array
    rows = db.execute(
        "SELECT name, description FROM character_abilities WHERE character_id = ?",
        (character_id,),
    ).fetchall()

    # Find the primary and all alternates
    alternates = {}
    primary_name = None
    for name, desc_str in rows:
        try:
            desc = _json.loads(desc_str)
        except (ValueError, TypeError):
            continue
        if desc.get("array_of") == array_name:
            alternates[name] = desc
        if name == array_name:
            primary_name = name
            alternates[name] = desc

    if not alternates:
        raise LoreKitError(f"No alternates found for array '{array_name}'")

    if alternate_name not in alternates:
        available = ", ".join(sorted(alternates.keys()))
        raise LoreKitError(f"'{alternate_name}' not in array '{array_name}'. Available: {available}")

    lines = [f"SWITCH ALTERNATE: {array_name} → {alternate_name}"]

    # Deactivate current: remove all action_overrides from array members
    for name in alternates:
        key = name.lower().replace(" ", "_")
        db.execute(
            "DELETE FROM character_attributes WHERE character_id = ? AND category = 'action_override' AND key = ?",
            (character_id, key),
        )

    # Activate new: write its action_override if it has one
    new_desc = alternates[alternate_name]
    action_data = new_desc.get("action")
    if action_data:
        key = action_data.get("key", alternate_name.lower().replace(" ", "_"))
        db.execute(
            "INSERT INTO character_attributes (character_id, category, key, value) "
            "VALUES (?, 'action_override', ?, ?) "
            "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
            (character_id, key, _json.dumps(action_data)),
        )
        lines.append(f"  Action registered: {key}")

    # Track active alternate
    db.execute(
        "INSERT INTO character_attributes (character_id, category, key, value) "
        "VALUES (?, 'active_alternate', ?, ?) "
        "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
        (character_id, array_name, alternate_name),
    )

    db.commit()
    recomp = rules_calc(db, character_id, pack_dir)
    for line in recomp.split("\n"):
        if line.startswith("  ") and "→" in line:
            lines.append(f"  RECOMPUTED: {line.strip()}")

    return "\n".join(lines)


def resolve_action(
    db,
    attacker_id: int,
    defender_id: int,
    action: str,
    pack_dir: str,
    options: dict | None = None,
) -> str:
    """Resolve a combat action between two characters."""
    pack = load_system_pack(pack_dir)
    attacker = load_character_data(db, attacker_id)
    defender = load_character_data(db, defender_id)

    is_free = (options or {}).get("free_action", False)

    # Condition-based action limit (dazed, stunned, incapacitated, etc.)
    if not is_free:
        _check_condition_action_limit(db, attacker_id, pack)

    # Auto-checkpoint before resolution so turn_revert can undo combat actions
    from lorekit.support.checkpoint import create_checkpoint

    create_checkpoint(db, attacker.session_id)

    # Check if action is a gm_assisted effect before looking up action defs
    try:
        action_def = _get_action_def(pack, attacker, action)
        action_def.setdefault("_action_name", action)
    except LoreKitError:
        # Fall back to effects.json for gm_assisted resolution
        hints = _get_gm_hints(pack, action)
        if hints:
            return hints
        raise  # re-raise original error if no hints found

    opts = _expand_combat_options(pack, options or {})

    # Validate defender is in the active encounter
    from lorekit.encounter import _get_active_encounter

    enc = _get_active_encounter(db, attacker.session_id)
    if enc is not None:
        enc_id_check = enc[0]
        in_encounter = db.execute(
            "SELECT 1 FROM character_zone WHERE encounter_id = ? AND character_id = ?",
            (enc_id_check, defender_id),
        ).fetchone()
        if not in_encounter:
            raise LoreKitError(
                f"{defender.name} (id {defender_id}) is not in the active encounter. "
                f"Check the character ID — use names instead of numeric IDs to avoid mistakes."
            )

    # Collect warnings
    warnings: list[str] = opts.pop("_option_warnings", [])

    # Warn if defender is incapacitated
    incap, cond_name = is_incapacitated(db, defender_id, pack)
    if incap:
        warnings.append(f"⚠ WARNING: {defender.name} is {cond_name} — attacking an incapacitated target")

    # Snapshot next_attack_received modifier IDs on defender BEFORE resolution.
    # These will be consumed after resolution (new ones added during this action survive).
    pre_existing_nar = {
        row[0]
        for row in db.execute(
            "SELECT id FROM combat_state WHERE character_id = ? AND duration_type = 'next_attack_received'",
            (defender_id,),
        ).fetchall()
    }

    # Range validation when an encounter is active
    range_type = action_def.get("range")
    if range_type and pack.combat:
        from lorekit.encounter import check_range

        enc = _get_active_encounter(db, attacker.session_id)
        if enc is not None:
            enc_id = enc[0]
            weapon_range = None
            if range_type == "ranged":
                range_stat = action_def.get("range_stat")
                if range_stat:
                    try:
                        weapon_range = _get_derived(attacker, range_stat)
                    except LoreKitError:
                        pass
            err = check_range(
                db,
                enc_id,
                attacker_id,
                defender_id,
                range_type,
                weapon_range,
                pack.combat,
            )
            if err:
                raise LoreKitError(err)

    # --- on_use effects (fire unconditionally before any roll) ---
    on_use = action_def.get("on_use")
    if on_use:
        use_lines = [f"ACTION: {attacker.name} uses {action} → {defender.name}"]
        _apply_on_hit(db, pack, attacker, defender, on_use, use_lines, options=opts)
        on_use_result = "\n".join(use_lines)
    else:
        on_use_result = None

    # --- Utility action (no attack_stat) — on_use only, no roll ---
    if "attack_stat" not in action_def:
        return on_use_result or f"ACTION: {attacker.name} uses {action} → {defender.name} (no effect)"

    resolution_type = pack.resolution.get("type", "threshold")

    if resolution_type == "threshold":
        result = _resolve_threshold(db, pack, attacker, defender, action_def, opts)
    elif resolution_type == "degree":
        result = _resolve_degree(db, pack, attacker, defender, action_def, opts)
    else:
        raise LoreKitError(f"Unknown resolution type: {resolution_type}")

    # Prepend on_use result if both on_use and roll happened
    if on_use_result:
        result = on_use_result + "\n" + result

    # Consume next_attack modifiers on the attacker (e.g. Setup bonus)
    consumed = db.execute(
        "DELETE FROM combat_state WHERE character_id = ? AND duration_type = 'next_attack'",
        (attacker_id,),
    )
    if consumed.rowcount > 0:
        db.commit()
        from lorekit.rules import try_rules_calc

        recalc = try_rules_calc(db, attacker_id)
        if recalc:
            result += f"\n{recalc}"

    # Consume pre-existing next_attack_received modifiers on the defender
    # (new ones added during this resolution survive for future attacks)
    if pre_existing_nar:
        placeholders = ",".join("?" for _ in pre_existing_nar)
        db.execute(f"DELETE FROM combat_state WHERE id IN ({placeholders})", tuple(pre_existing_nar))
        db.commit()
        _sync_and_recalc(db, defender_id, pack, None)
        from lorekit.rules import try_rules_calc

        recalc = try_rules_calc(db, defender_id)
        if recalc:
            result += f"\n{recalc}"

    # Process on_hit_actions (follow-up free actions on hit, e.g. Fast Grab)
    on_hit_actions = action_def.get("on_hit_actions")
    if on_hit_actions and "HIT" in result:
        for oha in on_hit_actions:
            req_ability = oha.get("requires_ability")
            if req_ability:
                has_ability = any(a["name"] == req_ability for a in attacker.abilities)
                if not has_ability:
                    continue
            follow_action = oha["action"]
            follow_opts = {"free_action": True} if oha.get("free") else {}
            try:
                follow_result = resolve_action(
                    db,
                    attacker_id,
                    defender_id,
                    follow_action,
                    pack_dir,
                    options=follow_opts,
                )
                result += f"\nFREE ACTION ({follow_action}):\n{follow_result}"
            except LoreKitError as e:
                result += f"\nFREE ACTION FAILED ({follow_action}): {e}"

    # Track action count for condition-based limits (dazed max_total: 1, etc.)
    if not is_free:
        _increment_turn_actions(db, attacker_id)

    # Prepend warnings if applicable
    if warnings:
        result = "\n".join(warnings) + "\n" + result

    return result
