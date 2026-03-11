"""Combat resolution engine — zero-knowledge action resolver.

Reads action definitions and resolution rules from the system pack,
looks up pre-computed stats on attacker/defender, rolls dice, and
applies stat mutations (subtract_from, increment) to the defender.

The engine knows nothing about RPG concepts — it just applies the
operations declared in the system pack JSON.
"""

from __future__ import annotations

import math
from typing import Any

from _db import LoreKitError
from rolldice import roll_expr
from rules_engine import (
    CharacterData,
    SystemPack,
    load_character_data,
    load_system_pack,
)


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

    raise LoreKitError(
        f"No current_hp or max_hp found on {defender.name}. "
        f"Set combat stats before resolving actions."
    )


# ---------------------------------------------------------------------------
# Threshold resolution (PF2e-style)
# ---------------------------------------------------------------------------

def _resolve_threshold(
    db, pack: SystemPack, attacker: CharacterData,
    defender: CharacterData, action_def: dict, options: dict,
) -> str:
    """Resolve an action using threshold (hit if roll >= defense)."""
    attack_stat = action_def["attack_stat"]
    defense_stat = action_def["defense_stat"]

    attack_bonus = _get_derived(attacker, attack_stat)
    defense_value = _get_derived(defender, defense_stat)

    roll_result = roll_expr(pack.dice)
    roll_val = roll_result["total"]
    attack_total = roll_val + attack_bonus

    lines = [
        f"ACTION: {attacker.name} → {defender.name}",
        f"ATTACK: {pack.dice}({roll_val}) + {attack_bonus} = {attack_total} vs {defense_stat} {defense_value}",
    ]

    if attack_total >= defense_value:
        lines.append("HIT!")

        on_hit = action_def.get("on_hit", {})
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

            lines.append(
                f"DAMAGE: {dice_expr}({damage_roll}) + {damage_bonus} = {total_damage}"
            )

            # Apply damage
            if subtract_target == "current_hp":
                current = _ensure_current_hp(db, defender)
            else:
                current = _get_derived(defender, subtract_target)

            new_val = current - total_damage
            _write_attr(db, defender.character_id, subtract_target, new_val)
            lines.append(f"{subtract_target}: {current} → {new_val}")
    else:
        lines.append("MISS!")
        margin = defense_value - attack_total
        lines.append(f"Missed by {margin}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Degree resolution (M&M3e-style)
# ---------------------------------------------------------------------------

def _resolve_degree(
    db, pack: SystemPack, attacker: CharacterData,
    defender: CharacterData, action_def: dict, options: dict,
) -> str:
    """Resolve an action using degree of failure system."""
    resolution = pack.resolution
    attack_stat = action_def["attack_stat"]
    defense_stat = action_def["defense_stat"]

    attack_bonus = _get_derived(attacker, attack_stat)
    defense_value = _get_derived(defender, defense_stat)
    dc_offset = resolution.get("defense_dc_offset", 10)

    roll_result = roll_expr(pack.dice)
    roll_val = roll_result["total"]
    attack_total = roll_val + attack_bonus
    defense_dc = dc_offset + defense_value

    lines = [
        f"ACTION: {attacker.name} → {defender.name}",
        f"ATTACK: {pack.dice}({roll_val}) + {attack_bonus} = {attack_total} vs DC {defense_dc}",
    ]

    if attack_total >= defense_dc:
        lines.append("HIT!")

        # Defender resistance roll
        resistance_stat = resolution.get("resistance_stat", "toughness")
        dc_base = resolution.get("dc_base", 15)
        damage_rank_stat = action_def.get("damage_rank_stat")

        if damage_rank_stat:
            damage_rank = _get_derived(attacker, damage_rank_stat)
        else:
            damage_rank = 0

        resistance_bonus = _get_derived(defender, resistance_stat)
        resist_result = roll_expr(pack.dice)
        resist_roll = resist_result["total"]
        resistance_total = resist_roll + resistance_bonus

        resist_dc = dc_base + damage_rank

        lines.append(
            f"RESISTANCE: {pack.dice}({resist_roll}) + {resistance_bonus} = "
            f"{resistance_total} vs DC {resist_dc}"
        )

        if resistance_total >= resist_dc:
            lines.append("RESULT: No effect")
        else:
            degree = math.floor((resist_dc - resistance_total) / 5)
            degree = max(1, min(degree, 4))

            on_failure = resolution.get("on_failure", {})
            effect = on_failure.get(str(degree), {})

            lines.append(f"DEGREE OF FAILURE: {degree}")

            # Apply increments
            increment = effect.get("increment")
            if increment and isinstance(increment, dict):
                for stat, value in increment.items():
                    try:
                        current = _get_derived(defender, stat)
                    except LoreKitError:
                        current = 0
                    new_val = current + value
                    _write_attr(db, defender.character_id, stat, new_val)
                    lines.append(f"{stat}: {current} → {new_val}")

            # Labels
            label = effect.get("label")
            if label:
                lines.append(f"CONDITION: {label}")
    else:
        lines.append("MISS!")
        margin = defense_dc - attack_total
        lines.append(f"Missed by {margin}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_action(
    db, attacker_id: int, defender_id: int, action: str,
    pack_dir: str, options: dict | None = None,
) -> str:
    """Resolve a combat action between two characters."""
    pack = load_system_pack(pack_dir)
    attacker = load_character_data(db, attacker_id)
    defender = load_character_data(db, defender_id)

    if action not in pack.actions:
        raise LoreKitError(
            f"Unknown action '{action}'. Available: {', '.join(pack.actions.keys())}"
        )

    action_def = pack.actions[action]
    opts = options or {}

    resolution_type = pack.resolution.get("type", "threshold")

    if resolution_type == "threshold":
        return _resolve_threshold(db, pack, attacker, defender, action_def, opts)
    elif resolution_type == "degree":
        return _resolve_degree(db, pack, attacker, defender, action_def, opts)
    else:
        raise LoreKitError(f"Unknown resolution type: {resolution_type}")
