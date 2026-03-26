"""Combat options — trade expansion, team bonuses, pre-resolution filters."""

from __future__ import annotations

import json
from typing import Any

from cruncher.system_pack import SystemPack
from cruncher.types import CharacterData
from lorekit.combat.conditions import _check_condition_action_limit, _increment_turn_actions
from lorekit.combat.helpers import _get_derived
from lorekit.db import LoreKitError
from lorekit.rules import load_character_data


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
