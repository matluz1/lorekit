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
from typing import Any

from _db import LoreKitError
from rolldice import roll_expr
from system_pack import (
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

    raise LoreKitError(f"No current_hp or max_hp found on {defender.name}. Set combat stats before resolving actions.")


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

            # apply_to: who receives the modifier
            apply_to = mod.get("apply_to", "defender")
            if apply_to == "intent_ally":
                ally_id = options.get("ally_id")
                if not ally_id:
                    lines.append(f"MODIFIER SKIPPED: {source} — no ally specified")
                    continue
                char_id = ally_id
                ally_name = _char_name_from_id(db, ally_id)
                label = f"{source} → {ally_name}"
            else:
                char_id = defender.character_id
                label = source

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "bonus_type, duration_type, duration) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET "
                "value = excluded.value, duration = excluded.duration",
                (char_id, source, target_stat, mod_type, value, bonus_type, dur_type, duration),
            )
            dur_info = f"{dur_type}, {duration} rounds" if duration else dur_type
            lines.append(f"MODIFIER: {label} → {target_stat} {value:+d} ({dur_info})")
            recalc_ids.add(char_id)

        db.commit()

        from rules_engine import try_rules_calc

        for cid in recalc_ids:
            recalc = try_rules_calc(db, cid)
            if recalc:
                lines.append(recalc)

    # --- Forced movement ---
    push = on_hit.get("push")
    if push:
        from encounter import _get_active_encounter, force_move

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
    for trade in options.get("trade", []):
        trade_val = trade["value"]
        trade_adj[trade["from"]] = trade_adj.get(trade["from"], 0) - trade_val
        trade_adj[trade["to"]] = trade_adj.get(trade["to"], 0) + trade_val

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

        lines = [f"ACTION: {attacker.name} → {defender.name}"]
        lines.append(f"ATTACKER: {pack.dice}({atk_roll}) + {atk_bonus} ({attack_stat}) = {atk_total}")
        lines.append(f"DEFENDER: {pack.dice}({def_roll}) + {def_bonus} ({defense_stat}) = {def_total}")

        is_natural_crit = crit_cfg and atk_natural is not None and atk_natural == crit_cfg.get("natural")
        hit = atk_total >= def_total
        is_crit = False
        if is_natural_crit and crit_cfg.get("degree_shift", 0) > 0:
            if hit:
                is_crit = True
            else:
                hit = True  # miss upgraded to hit

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
    else:
        attack_bonus = _get_derived(attacker, attack_stat)
        defense_value = _get_derived(defender, defense_stat)
        if attack_stat in trade_adj:
            attack_bonus += trade_adj[attack_stat]

        roll_result = roll_expr(pack.dice)
        roll_val = roll_result["total"]
        natural = roll_result["natural"]
        attack_total = roll_val + attack_bonus

        lines = [
            f"ACTION: {attacker.name} → {defender.name}",
            f"ATTACK: {pack.dice}({roll_val}) + {attack_bonus} = {attack_total} vs {defense_stat} {defense_value}",
        ]

        is_natural_crit = crit_cfg and natural is not None and natural == crit_cfg.get("natural")
        hit = attack_total >= defense_value
        is_crit = False
        if is_natural_crit and crit_cfg.get("degree_shift", 0) > 0:
            if hit:
                is_crit = True
            else:
                hit = True  # miss upgraded to hit

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

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Degree resolution (M&M3e-style)
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

    # Apply trade options (e.g. power_attack: -N attack / +N damage)
    trade_adj: dict[str, int] = {}
    for trade in options.get("trade", []):
        trade_val = trade["value"]
        trade_adj[trade["from"]] = trade_adj.get(trade["from"], 0) - trade_val
        trade_adj[trade["to"]] = trade_adj.get(trade["to"], 0) + trade_val

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

        lines = [f"ACTION: {attacker.name} → {defender.name}"]
        lines.append(f"ATTACKER: {pack.dice}({atk_roll}) + {atk_bonus} ({attack_stat}) = {atk_total}")
        lines.append(f"DEFENDER: {pack.dice}({def_roll}) + {def_bonus} ({defense_stat}) = {def_total}")
        hit = atk_total >= def_total
        is_natural_crit = crit_cfg and atk_natural is not None and atk_natural == crit_cfg.get("natural")
    else:
        attack_bonus = _get_derived(attacker, attack_stat)
        defense_value = _get_derived(defender, defense_stat)

        # Apply trade to attack bonus
        if attack_stat in trade_adj:
            attack_bonus += trade_adj[attack_stat]

        roll_result = roll_expr(pack.dice)
        roll_val = roll_result["total"]
        natural = roll_result["natural"]
        attack_total = roll_val + attack_bonus
        defense_dc = dc_offset + defense_value

        lines = [
            f"ACTION: {attacker.name} → {defender.name}",
            f"ATTACK: {pack.dice}({roll_val}) + {attack_bonus} = {attack_total} vs DC {defense_dc}",
        ]
        hit = attack_total >= defense_dc
        is_natural_crit = crit_cfg and natural is not None and natural == crit_cfg.get("natural")

    # Apply degree_shift from crit config (miss upgraded to hit)
    if is_natural_crit and crit_cfg.get("degree_shift", 0) > 0 and not hit:
        hit = True

    if hit:
        # Compute margin for on_hit effects (e.g. value_min_margin)
        if action_def.get("contested"):
            hit_margin = atk_total - def_total
        else:
            hit_margin = attack_total - defense_dc
        lines.append("HIT!")

        # If action has damage_rank_stat, run resistance check (standard degree flow)
        damage_rank_stat = action_def.get("damage_rank_stat")
        if damage_rank_stat:
            resistance_stat = resolution.get("resistance_stat", "toughness")
            dc_base = resolution.get("dc_base", 15)
            damage_rank = _get_derived(attacker, damage_rank_stat)

            # Apply trade to damage rank (e.g. Power Attack)
            if damage_rank_stat in trade_adj:
                damage_rank += trade_adj[damage_rank_stat]

            # Apply critical effect_rank_bonus (e.g. M&M3e nat 20 → +5 effect rank)
            if is_natural_crit:
                effect_rank_bonus = crit_cfg.get("effect_rank_bonus", 0)
                if effect_rank_bonus:
                    damage_rank += effect_rank_bonus
                    lines.append(f"CRITICAL! Effect rank +{effect_rank_bonus} (rank {damage_rank})")

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

                on_failure = resolution.get("on_failure", {})
                effect = on_failure.get(str(degree), {})

                lines.append(f"DEGREE OF FAILURE: {degree}")

                # Apply increments from degree table
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

                label = effect.get("label")
                if label:
                    lines.append(f"CONDITION: {label}")
        else:
            # No resistance check — apply on_hit effects directly
            on_hit = action_def.get("on_hit", {})
            _apply_on_hit(db, pack, attacker, defender, on_hit, lines, margin=hit_margin, options=options)
    else:
        lines.append("MISS!")
        if not action_def.get("contested"):
            margin = defense_dc - attack_total
            lines.append(f"Missed by {margin}")
        else:
            margin = def_total - atk_total
            lines.append(f"{defender.name} resists by {margin}")

    return "\n".join(lines)


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
    from rolldice import roll_expr

    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    if not pack.end_turn:
        return f"END TURN: {char.name} — no end_turn config in system pack"

    # Auto-checkpoint before ticking so turn_revert can undo
    from checkpoint import create_checkpoint

    create_checkpoint(db, char.session_id)

    # Load all active combat_state rows for this character
    rows = db.execute(
        "SELECT id, source, target_stat, value, duration_type, duration, "
        "save_stat, save_dc FROM combat_state WHERE character_id = ?",
        (character_id,),
    ).fetchall()

    if not rows:
        return f"END TURN: {char.name} — no active modifiers"

    lines = [f"END TURN: {char.name}"]
    removed_any = False

    for row_id, source, target_stat, value, dur_type, duration, save_stat, save_dc in rows:
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

    db.commit()

    # Recompute derived stats if any modifiers were removed
    if removed_any:
        from rules_engine import rules_calc as _rules_calc

        recomp = _rules_calc(db, character_id, pack_dir)
        # Extract change lines from recompute output
        for line in recomp.split("\n"):
            if line.startswith("  ") and "→" in line:
                lines.append(f"  RECOMPUTED: {line.strip()}")

    return "\n".join(lines)


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
    from encounter import (
        _get_active_encounter,
        _get_character_zone,
        _zone_name_to_id,
        get_area_targets,
    )

    pack = load_system_pack(pack_dir)
    attacker = load_character_data(db, attacker_id)

    # Auto-checkpoint
    from checkpoint import create_checkpoint

    create_checkpoint(db, attacker.session_id)

    if action not in pack.actions:
        raise LoreKitError(f"Unknown action '{action}'. Available: {', '.join(pack.actions.keys())}")

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

    action_def = pack.actions[action]
    opts = options or {}
    resolution_type = pack.resolution.get("type", "threshold")

    results = []
    for tid in target_ids:
        defender = load_character_data(db, tid)
        if resolution_type == "threshold":
            result = _resolve_threshold(db, pack, attacker, defender, action_def, opts)
        elif resolution_type == "degree":
            result = _resolve_degree(db, pack, attacker, defender, action_def, opts)
        else:
            raise LoreKitError(f"Unknown resolution type: {resolution_type}")
        results.append(result)

    return "\n---\n".join(results)


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

    # Auto-checkpoint before resolution so turn_revert can undo combat actions
    from checkpoint import create_checkpoint

    create_checkpoint(db, attacker.session_id)

    if action not in pack.actions:
        raise LoreKitError(f"Unknown action '{action}'. Available: {', '.join(pack.actions.keys())}")

    action_def = pack.actions[action]
    opts = options or {}

    # Range validation when an encounter is active
    range_type = action_def.get("range")
    if range_type and pack.combat:
        from encounter import _get_active_encounter, check_range

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

    resolution_type = pack.resolution.get("type", "threshold")

    if resolution_type == "threshold":
        result = _resolve_threshold(db, pack, attacker, defender, action_def, opts)
    elif resolution_type == "degree":
        result = _resolve_degree(db, pack, attacker, defender, action_def, opts)
    else:
        raise LoreKitError(f"Unknown resolution type: {resolution_type}")

    # Consume next_attack modifiers on the attacker (e.g. Setup bonus)
    consumed = db.execute(
        "DELETE FROM combat_state WHERE character_id = ? AND duration_type = 'next_attack'",
        (attacker_id,),
    )
    if consumed.rowcount > 0:
        db.commit()
        from rules_engine import try_rules_calc

        recalc = try_rules_calc(db, attacker_id)
        if recalc:
            result += f"\n{recalc}"

    return result
