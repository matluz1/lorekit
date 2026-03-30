"""Area avoidance helpers and area action resolution."""

from __future__ import annotations

import math

from cruncher.dice import roll_expr
from cruncher.system_pack import SystemPack, load_system_pack
from cruncher.types import CharacterData
from lorekit.combat.conditions import _check_condition_action_limit, _increment_turn_actions
from lorekit.combat.helpers import _get_action_def, _get_derived
from lorekit.combat.options import _expand_combat_options
from lorekit.db import LoreKitError
from lorekit.rules import load_character_data


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

        from lorekit.combat.resolve import _resolve

        result = _resolve(db, pack, attacker, defender, effective_action_def, opts)

        if avoidance_lines:
            result = "\n".join(avoidance_lines) + "\n" + result

        results.append(result)

    # Area action counts as one action for condition tracking
    _increment_turn_actions(db, attacker_id)

    return "\n---\n".join(results)
