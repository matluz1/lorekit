"""Condition checks — shared by PC resolve_action and NPC _validate_sequence."""

from __future__ import annotations

from typing import Any

from cruncher.system_pack import SystemPack
from cruncher.types import CharacterData
from lorekit.db import LoreKitError


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
        from lorekit.queries import get_attribute_by_key

        val = get_attribute_by_key(db, character_id, attr_key)
        if val is not None and float(val) >= min_val:
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
    from lorekit.queries import get_attribute, upsert_attribute

    row = get_attribute(db, character_id, "internal", "_actions_this_turn")
    new_val = (int(row) if row else 0) + 1
    upsert_attribute(db, character_id, "internal", "_actions_this_turn", str(new_val))
    db.commit()


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
            from lorekit.queries import upsert_attribute

            upsert_attribute(db, character_id, "condition_flags", flag, "1")
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
