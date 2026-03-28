"""On-hit effects, damage triggers, degree-effect application, contagious spreading."""

from __future__ import annotations

import json
import math

from cruncher.dice import roll_expr
from cruncher.system_pack import SystemPack
from cruncher.types import CharacterData
from lorekit.combat.helpers import (
    _char_name_from_id,
    _ensure_current_hp,
    _get_attr_str,
    _get_derived,
    _read_resource,
    _sync_and_recalc,
    _write_attr,
    _write_resource,
)
from lorekit.db import LoreKitError
from lorekit.rules import load_character_data


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


def _check_on_hit_resist(
    db,
    pack: SystemPack,
    attacker: CharacterData,
    defender: CharacterData,
    resist: dict,
    lines: list[str],
) -> bool:
    """Roll an immediate resistance check for the defender before on_hit effects.

    resist config (from action's on_hit.resist):
        defender_stat: str or list[str] — stat(s) for the defender's roll (best of, if list)
        dc_stat: str — attacker stat used as the DC
        dc_offset: int — added to the DC stat (default from pack.resolution.defense_dc_offset)

    Returns True if the defender resisted (effects should be skipped).
    """
    resolution = pack.resolution or {}
    dc_offset = resist.get("dc_offset", resolution.get("defense_dc_offset", 10))

    # Defender's bonus: best of the listed stats
    defender_stats = resist.get("defender_stat", [])
    if isinstance(defender_stats, str):
        defender_stats = [defender_stats]

    best_bonus = None
    best_stat = None
    for stat in defender_stats:
        try:
            val = _get_derived(defender, stat)
            if best_bonus is None or val > best_bonus:
                best_bonus = val
                best_stat = stat
        except LoreKitError:
            continue

    if best_bonus is None:
        lines.append("RESIST: no valid defender stat — skipping resistance check")
        return False

    # Attacker's DC
    dc_stat = resist.get("dc_stat", "")
    try:
        dc_base = _get_derived(attacker, dc_stat) if dc_stat else 0
    except LoreKitError:
        dc_base = 0
    dc = dc_base + dc_offset

    # Roll
    roll_result = roll_expr(pack.dice)
    roll_val = roll_result["total"]
    total = roll_val + best_bonus
    success = total >= dc

    stat_label = best_stat
    if len(defender_stats) > 1:
        stat_label = f"best of {'/'.join(defender_stats)} = {best_stat}"

    outcome = "RESISTED" if success else "FAILED"
    lines.append(
        f"RESIST: {defender.name} — {stat_label} "
        f"{pack.dice}({roll_val}) + {best_bonus} = {total} vs DC {dc} ({dc_stat}+{dc_offset}) "
        f"→ {outcome}"
    )

    return success


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
    - resist: immediate resistance check; if defender passes, skip remaining effects
    - damage_roll + subtract_from: roll damage dice, subtract from a stat
    - apply_modifiers: insert combat_state rows (on defender or intent_ally)
    - push + push_direction: force-move defender via zone graph

    When is_crit is True and the system pack declares on_critical.damage_multiplier,
    total damage is multiplied accordingly.
    """
    options = options or {}

    # --- Immediate resistance check (e.g. grab: defender resists before modifiers apply) ---
    resist = on_hit.get("resist")
    if resist:
        resisted = _check_on_hit_resist(db, pack, attacker, defender, resist, lines)
        if resisted:
            return

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
    add_target = on_hit.get("add_to")
    target_stat = subtract_target or add_target

    if damage_info and target_stat:
        # Normalize to component list
        components = damage_info if isinstance(damage_info, list) else [damage_info]

        total_damage = 0
        damage_parts = []

        for comp in components:
            comp_dice = 0
            comp_bonus = 0

            # Resolve dice expression
            dice_expr = None
            if "dice_attr" in comp:
                dice_expr = _get_attr_str(attacker, comp["dice_attr"])
            elif "dice" in comp:
                dice_expr = comp["dice"]

            # Resolve count (multiplier for dice)
            count = 1
            if "count_stat" in comp:
                count = max(1, _get_derived(attacker, comp["count_stat"]))

            # Roll dice
            if dice_expr:
                for _ in range(count):
                    result = roll_expr(dice_expr)
                    comp_dice += result["total"]
                if count > 1:
                    damage_parts.append(f"{count}x{dice_expr}({comp_dice})")
                else:
                    damage_parts.append(f"{dice_expr}({comp_dice})")

            # Resolve bonus
            if "bonus_stat" in comp:
                comp_bonus = _get_derived(attacker, comp["bonus_stat"])
                damage_parts.append(str(comp_bonus))
            elif "bonus" in comp:
                comp_bonus = comp["bonus"]
                damage_parts.append(str(comp_bonus))

            total_damage += comp_dice + comp_bonus

        # Apply critical damage multiplier from system pack
        if is_crit:
            on_critical = pack.resolution.get("on_critical", {})
            multiplier = on_critical.get("damage_multiplier")
            if multiplier and multiplier != 1:
                total_damage = int(total_damage * multiplier)
                lines.append(f"CRITICAL! Damage x{multiplier}")

        lines.append(f"DAMAGE: {' + '.join(damage_parts)} = {total_damage}")

        if target_stat == "current_hp":
            current = _ensure_current_hp(db, defender)
        else:
            current = _get_derived(defender, target_stat)

        if subtract_target:
            new_val = current - total_damage
        else:
            new_val = current + total_damage

        _write_attr(db, defender.character_id, target_stat, new_val)
        lines.append(f"{target_stat}: {current} → {new_val}")

        # Fire on-damage triggers (e.g. concentration break)
        if subtract_target:
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
                except (ValueError, ZeroDivisionError, NameError, TypeError) as e:
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
    action_range = action_def.get("range", "")

    rows = db.execute(
        "SELECT source, target_stat, modifier_type, value, bonus_type, "
        "duration_type, duration, save_stat, save_dc, metadata "
        "FROM combat_state WHERE character_id = ? AND metadata IS NOT NULL",
        (defender.character_id,),
    ).fetchall()

    for source, target_stat, mod_type, value, bonus_type, dur_type, duration, save_stat, save_dc, meta_str in rows:
        try:
            metadata = json.loads(meta_str)
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
