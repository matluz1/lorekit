"""Power toggle — activate/deactivate sustained powers, alternate switching."""

from __future__ import annotations

import json

from cruncher.system_pack import SystemPack, load_system_pack
from cruncher.types import CharacterData
from lorekit.combat.helpers import _sync_and_recalc
from lorekit.db import LoreKitError


def _check_switch_limit(db, char, pack) -> None:
    """Raise LoreKitError if the character has exhausted their switches this turn.

    Only enforced during an active encounter. Reads max_per_turn from the
    system pack's combat.alternate_switching config.
    """
    combat_cfg = pack.combat or {}
    switching_cfg = combat_cfg.get("alternate_switching", {})
    max_per_turn = switching_cfg.get("max_per_turn")
    if max_per_turn is None:
        return  # no limit configured

    # Only enforce during active encounters
    from lorekit.encounter import _get_active_encounter

    enc = _get_active_encounter(db, char.session_id)
    if enc is None:
        return

    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND key = '_switches_this_turn'",
        (char.character_id,),
    ).fetchone()
    switches_used = int(row[0]) if row else 0

    if switches_used >= max_per_turn:
        action_cost = switching_cfg.get("action_cost", "free")
        raise LoreKitError(
            f"BLOCKED: already switched arrays {switches_used}/{max_per_turn} time(s) this turn "
            f"(switching costs a {action_cost} action, {max_per_turn}/turn)"
        )


def _increment_switches(db, char) -> None:
    """Increment the per-turn switch counter during an active encounter."""
    from lorekit.encounter import _get_active_encounter

    enc = _get_active_encounter(db, char.session_id)
    if enc is None:
        return

    from lorekit.queries import get_attribute, upsert_attribute

    row = get_attribute(db, char.character_id, "internal", "_switches_this_turn")
    new_val = (int(row) if row else 0) + 1
    upsert_attribute(db, char.character_id, "internal", "_switches_this_turn", str(new_val))


def activate_power(db, character_id: int, ability_name: str, pack_dir: str) -> str:
    """Activate a sustained power, inserting its declared modifiers.

    Reads the ability's JSON description for ``on_activate.apply_modifiers``,
    inserts them as combat_state rows with ``duration_type = "sustained"``,
    and re-runs rules_calc to recompute derived stats.
    """
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
        desc = json.loads(row[0])
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


def switch_alternate(
    db,
    character_id: int,
    array_name: str,
    alternate_name: str,
    pack_dir: str,
    *,
    _bypass_limit: bool = False,
) -> str:
    """Switch the active alternate in a power array.

    Deactivates the current alternate's action_override, activates the new
    one, updates the active_alternate tracker, and re-runs rules_calc.

    During an active encounter, enforces the per-turn switch limit from the
    system pack's combat.alternate_switching.max_per_turn config (if set).
    Set _bypass_limit=True for internal resets (e.g. encounter_end cleanup).
    """

    from lorekit.rules import load_character_data, rules_calc

    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    # Enforce per-turn switch limit during active encounters
    if not _bypass_limit:
        _check_switch_limit(db, char, pack)

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
            desc = json.loads(desc_str)
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
        from lorekit.queries import upsert_attribute

        key = action_data.get("key", alternate_name.lower().replace(" ", "_"))
        upsert_attribute(db, character_id, "action_override", key, json.dumps(action_data))
        lines.append(f"  Action registered: {key}")

    # Track active alternate
    from lorekit.queries import upsert_attribute as _upsert

    _upsert(db, character_id, "active_alternate", array_name, alternate_name)

    # Increment per-turn switch counter (only during active encounters)
    if not _bypass_limit:
        _increment_switches(db, char)

    db.commit()
    recomp = rules_calc(db, character_id, pack_dir)
    for line in recomp.split("\n"):
        if line.startswith("  ") and "→" in line:
            lines.append(f"  RECOMPUTED: {line.strip()}")

    return "\n".join(lines)
