"""Action resolution — contested rolls, threshold, degree, and the main entry point."""

from __future__ import annotations

import json
import math
import random

from cruncher.dice import roll_expr
from cruncher.system_pack import SystemPack, load_system_pack
from cruncher.types import CharacterData
from lorekit.combat.conditions import (
    _check_condition_action_limit,
    _increment_turn_actions,
    is_incapacitated,
)
from lorekit.combat.effects import _apply_on_hit, _check_contagious, _fire_damage_triggers
from lorekit.combat.helpers import (
    _ensure_current_hp,
    _get_action_def,
    _get_defender_resolution_effects,
    _get_derived,
    _get_gm_hints,
    _is_crit,
    _sync_and_recalc,
    _write_attr,
)
from lorekit.combat.options import (
    _apply_team_bonus,
    _apply_trade_modifiers,
    _check_pre_resolution,
    _expand_combat_options,
)
from lorekit.combat.reactions import _check_reactions
from lorekit.db import LoreKitError
from lorekit.rules import load_character_data


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
    reaction_mods = _check_reactions(
        db, pack, "before_attack", attacker, defender, action_def, trade_mod_lines, options
    )
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
    defense_mods = _check_reactions(
        db, pack, "replace_defense", attacker, defender, action_def, trade_mod_lines, options
    )

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

                from lorekit.combat.effects import _apply_degree_effect

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
        after_hit_mods = _check_reactions(db, pack, "after_hit", attacker, defender, action_def, lines, options)
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
        after_miss_mods = _check_reactions(db, pack, "after_miss", attacker, defender, action_def, lines, options)
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
        homing_ranks = action_def.get("homing")
        retries = homing_ranks if isinstance(homing_ranks, int) else 1
        action_name = action_def.get("_action_name", "unknown")
        metadata = json.dumps(
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
