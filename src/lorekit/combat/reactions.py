"""Reaction system — interrupt hooks in resolution pipeline."""

from __future__ import annotations

import json

from cruncher.system_pack import SystemPack
from cruncher.types import CharacterData
from lorekit.combat.helpers import _char_name_from_id, _get_derived
from lorekit.db import LoreKitError
from lorekit.rules import load_character_data


def _get_reaction_policy(db, reactor_id: int, source: str) -> str:
    """Read the reaction policy for a specific reaction.

    Returns:
        'active'  — auto-fire (NPC default, simple behavior)
        'inactive' — skip this reaction
        'ask'     — NPC per-attack decision via callback
        'pending' — PC: pause resolution, return options for player choice
    """
    row = db.execute(
        "SELECT value FROM character_attributes WHERE character_id = ? AND category = 'reaction_policy' AND key = ?",
        (reactor_id, source),
    ).fetchone()
    return row[0] if row else "active"


def _check_reactions(
    db,
    pack: SystemPack,
    hook_name: str,
    attacker: CharacterData,
    defender: CharacterData,
    action_def: dict,
    lines: list[str],
    options: dict | None = None,
) -> dict:
    """Check for reaction combat_state entries matching the named hook.

    Reactions are combat_state rows with ``duration_type`` in
    ('reaction', 'triggered') and a JSON ``metadata`` column declaring
    which hook they respond to and what effect they produce.

    Respects per-character reaction policies:
    - 'active': fire automatically (default)
    - 'inactive': skip
    - 'ask': call options['reaction_query'] callback for a yes/no decision;
      if no callback is set, treat as 'active'

    Returns a dict of context modifications:
    - ``new_defender_id``: substitute defender (Interpose)
    - ``defense_override``: replace defense value (Deflect)
    - ``free_attack``: reactor gets a free counter-attack
    """
    options = options or {}
    reactions_cfg = pack.combat.get("reactions", {})
    hook_cfg = reactions_cfg.get(hook_name, {})
    if not hook_cfg:
        return {}

    rows = db.execute(
        "SELECT id, character_id, source, duration_type, duration, metadata "
        "FROM combat_state "
        "WHERE duration_type IN ('reaction', 'triggered') AND duration > 0 AND metadata IS NOT NULL",
    ).fetchall()

    if not rows:
        return {}

    modifications = {}

    for row_id, reactor_id, source, dur_type, duration, metadata_str in rows:
        try:
            metadata = json.loads(metadata_str)
        except (ValueError, TypeError):
            continue

        if metadata.get("hook") != hook_name:
            continue

        # Determine the reaction's key for config lookup
        reaction_key = metadata.get("reaction_key", metadata.get("effect", ""))
        if reaction_key not in hook_cfg:
            continue

        effect_cfg = hook_cfg[reaction_key]
        scope = effect_cfg.get("scope", "self_targeted")

        # Scope filter
        if scope == "ally_targeted":
            if reactor_id == attacker.character_id or reactor_id == defender.character_id:
                continue
            team_row = db.execute(
                "SELECT cz1.team FROM character_zone cz1 "
                "JOIN character_zone cz2 ON cz1.encounter_id = cz2.encounter_id "
                "WHERE cz1.character_id = ? AND cz2.character_id = ? "
                "AND cz1.team != '' AND cz1.team = cz2.team",
                (reactor_id, defender.character_id),
            ).fetchone()
            if not team_row:
                continue
        elif scope == "self_targeted":
            if reactor_id != defender.character_id:
                continue

        # Range check if required
        if effect_cfg.get("check") == "range":
            from lorekit.encounter import _build_adjacency, _get_active_encounter, _shortest_path

            enc = _get_active_encounter(db, attacker.session_id)
            if enc:
                enc_id = enc[0]
                reactor_zone = db.execute(
                    "SELECT zone_id FROM character_zone WHERE encounter_id = ? AND character_id = ?",
                    (enc_id, reactor_id),
                ).fetchone()
                defender_zone = db.execute(
                    "SELECT zone_id FROM character_zone WHERE encounter_id = ? AND character_id = ?",
                    (enc_id, defender.character_id),
                ).fetchone()
                if reactor_zone and defender_zone:
                    adj = _build_adjacency(db, enc_id)
                    dist = _shortest_path(adj, reactor_zone[0], defender_zone[0])
                    max_range = metadata.get("range_zones", 1)
                    if dist is not None and dist > max_range:
                        continue

        # Check reaction policy
        policy = _get_reaction_policy(db, reactor_id, source)
        if policy == "inactive":
            continue
        if policy == "ask":
            query_fn = options.get("reaction_query")
            if query_fn:
                if not query_fn(db, reactor_id, source, hook_name, reaction_key, attacker, defender):
                    lines.append(f"REACTION [{source}]: declined")
                    continue
            # No callback (GM play) → treat as active

        if policy == "pending":
            reactor_name = _char_name_from_id(db, reactor_id)
            effects = metadata.get("effects", [])
            # Support legacy single-effect format
            if not effects and "effect" in metadata:
                legacy = metadata["effect"]
                effect_entry = {"type": legacy}
                if legacy == "use_reactor_stat":
                    effect_entry["stat"] = metadata.get("stat", "deflect")
                elif legacy == "counter_attack":
                    effect_entry["action"] = metadata.get("counter_action", "close_attack")
                effects = [effect_entry]

            pending = modifications.setdefault("pending_reactions", [])
            pending.append(
                {
                    "source": source,
                    "reactor_id": reactor_id,
                    "reactor_name": reactor_name,
                    "reaction_key": reaction_key,
                    "effects": effects,
                    "row_id": row_id,
                    "dur_type": dur_type,
                }
            )
            continue  # Don't dispatch — caller will handle

        # Dispatch effects (composable list)
        reactor_name = _char_name_from_id(db, reactor_id)
        effects = metadata.get("effects", [])

        # Support legacy single-effect format
        if not effects and "effect" in metadata:
            legacy = metadata["effect"]
            effect_entry = {"type": legacy}
            if legacy == "use_reactor_stat":
                effect_entry["stat"] = metadata.get("stat", "deflect")
            elif legacy == "counter_attack":
                effect_entry["action"] = metadata.get("counter_action", "close_attack")
            effects = [effect_entry]

        for eff in effects:
            eff_type = eff.get("type")
            if eff_type == "substitute_defender":
                lines.append(f"REACTION [{source}]: {reactor_name} interposes for {defender.name}!")
                modifications["new_defender_id"] = reactor_id
            elif eff_type == "use_reactor_stat":
                stat_name = eff.get("stat", "deflect")
                try:
                    reactor_char = load_character_data(db, reactor_id)
                    stat_val = _get_derived(reactor_char, stat_name)
                    lines.append(
                        f"REACTION [{source}]: {reactor_name} deflects! Using {stat_name} ({stat_val}) as defense"
                    )
                    modifications["defense_override"] = stat_val
                except LoreKitError:
                    continue
            elif eff_type == "counter_attack":
                counter_action = eff.get("action", "close_attack")
                lines.append(f"REACTION [{source}]: {reactor_name} counter-attacks!")
                modifications["free_attack"] = {
                    "reactor_id": reactor_id,
                    "target_id": attacker.character_id,
                    "action": counter_action,
                }

        # Consume
        if dur_type == "triggered":
            db.execute("DELETE FROM combat_state WHERE id = ?", (row_id,))
        else:
            db.execute("UPDATE combat_state SET duration = duration - 1 WHERE id = ?", (row_id,))
        db.commit()

        break  # One reaction per hook per resolution

    return modifications
