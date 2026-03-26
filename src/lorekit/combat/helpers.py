"""Combat helper utilities — stat access, attribute I/O, resource management."""

from __future__ import annotations

import json
import os
from typing import Any

from cruncher.system_pack import SystemPack
from cruncher.types import CharacterData
from lorekit.db import LoreKitError


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
    from lorekit.combat.conditions import expand_conditions, get_active_conditions

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
            try:
                tags = json.loads(zone_row[0]) if isinstance(zone_row[0], str) else zone_row[0]
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
    from lorekit.combat.conditions import sync_condition_modifiers

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
    effects_path = os.path.join(pack.pack_dir, "effects.json")
    if not os.path.isfile(effects_path):
        return None

    with open(effects_path) as f:
        effects_data = json.load(f)

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
    from lorekit.queries import upsert_attribute

    upsert_attribute(db, character_id, "combat", key, str(value))
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
    from lorekit.queries import upsert_attribute

    upsert_attribute(db, character_id, "resource", key, str(value))
    db.commit()


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


def _char_name_from_id(db, character_id: int) -> str:
    from lorekit.queries import get_character_name

    return get_character_name(db, character_id) or f"#{character_id}"
