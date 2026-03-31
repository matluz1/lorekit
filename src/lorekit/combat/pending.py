"""Pending resolution storage — two-phase resolution for PC reaction choice."""

from __future__ import annotations

import json

from lorekit.db import LoreKitError


def store_pending(
    db,
    session_id: int,
    attacker_id: int,
    defender_id: int,
    action_name: str,
    pack_dir: str,
    calculated_state: dict,
    available_reactions: list[dict],
    options: dict | None = None,
) -> int:
    """Store a pending resolution. Returns the pending ID.

    Replaces any existing pending resolution for the session.
    """
    db.execute("DELETE FROM pending_resolutions WHERE session_id = ?", (session_id,))

    cursor = db.execute(
        "INSERT INTO pending_resolutions "
        "(session_id, attacker_id, defender_id, action_name, pack_dir, "
        "calculated_state, available_reactions, options) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            attacker_id,
            defender_id,
            action_name,
            pack_dir,
            json.dumps(calculated_state),
            json.dumps(available_reactions),
            json.dumps(options or {}),
        ),
    )
    db.commit()
    return cursor.lastrowid


def load_pending(db, pending_id: int) -> dict:
    """Load a pending resolution by ID. Raises LoreKitError if not found."""
    row = db.execute(
        "SELECT id, session_id, attacker_id, defender_id, action_name, pack_dir, "
        "calculated_state, available_reactions, options "
        "FROM pending_resolutions WHERE id = ?",
        (pending_id,),
    ).fetchone()

    if not row:
        raise LoreKitError(f"No pending resolution with id {pending_id}")

    return {
        "id": row[0],
        "session_id": row[1],
        "attacker_id": row[2],
        "defender_id": row[3],
        "action_name": row[4],
        "pack_dir": row[5],
        "calculated_state": json.loads(row[6]),
        "available_reactions": json.loads(row[7]),
        "options": json.loads(row[8]),
    }


def delete_pending(db, pending_id: int) -> None:
    """Delete a pending resolution after confirmation."""
    db.execute("DELETE FROM pending_resolutions WHERE id = ?", (pending_id,))
    db.commit()


def confirm_pending(
    db,
    pending_id: int,
    reactions: list[str] | None = None,
) -> str:
    """Confirm a pending resolution, applying chosen reactions.

    reactions: list of reaction source names to activate (e.g. ["shield_block"]).
               Empty list or None means decline all reactions.
    """
    from cruncher.system_pack import load_system_pack
    from lorekit.combat.effects import _fire_damage_triggers
    from lorekit.combat.helpers import _ensure_current_hp, _get_derived, _sync_and_recalc, _write_attr
    from lorekit.db import LoreKitError
    from lorekit.rules import load_character_data

    pending = load_pending(db, pending_id)
    state = pending["calculated_state"]
    available = pending["available_reactions"]
    reactions = reactions or []

    pack = load_system_pack(pending["pack_dir"])
    defender = load_character_data(db, pending["defender_id"])

    total_damage = state["total_damage"]
    lines = list(state["lines"])

    # Apply chosen reactions
    total_reduction = 0
    for rxn in available:
        if rxn["source"] not in reactions:
            continue

        for eff in rxn.get("effects", []):
            eff_type = eff.get("type")
            if eff_type == "reduce_damage":
                stat = eff.get("stat")
                if stat:
                    try:
                        reduction = _get_derived(defender, stat)
                    except LoreKitError:
                        reduction = 0
                else:
                    reduction = eff.get("value", 0)
                total_reduction += reduction
                lines.append(f"SHIELD BLOCK [{rxn['source']}]: {rxn['reactor_name']} reduces damage by {reduction}")
            elif eff_type == "damage_item":
                item_stat = eff.get("item_stat")
                if item_stat:
                    overflow = max(0, total_damage - total_reduction)
                    try:
                        current_item_hp = _get_derived(defender, item_stat)
                    except LoreKitError:
                        current_item_hp = 0
                    new_item_hp = current_item_hp - overflow
                    _write_attr(db, defender.character_id, item_stat, new_item_hp)
                    lines.append(f"  {item_stat}: {current_item_hp} → {new_item_hp}")

        # Consume the reaction combat_state row
        row_id = rxn.get("row_id")
        dur_type = rxn.get("dur_type", "reaction")
        if row_id:
            if dur_type == "triggered":
                db.execute("DELETE FROM combat_state WHERE id = ?", (row_id,))
            else:
                db.execute("UPDATE combat_state SET duration = duration - 1 WHERE id = ?", (row_id,))
            db.commit()

    # Apply final damage
    final_damage = max(0, total_damage - total_reduction)
    current = _ensure_current_hp(db, defender)
    new_val = current - final_damage
    _write_attr(db, defender.character_id, "current_hp", new_val)
    lines.append(f"current_hp: {current} → {new_val}")

    # Fire on-damage triggers with final damage
    _fire_damage_triggers(db, pack, defender.character_id, final_damage, lines)

    # Sync conditions
    _sync_and_recalc(db, defender.character_id, pack, lines)

    # Delete pending
    delete_pending(db, pending_id)

    return "\n".join(lines)
