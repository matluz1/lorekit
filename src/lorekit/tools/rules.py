import json

from lorekit._mcp_app import mcp
from lorekit.rules import resolve_system_path, try_rules_calc
from lorekit.tools._helpers import (
    _resolve_character,
    _resolve_system_path_for_character,
    _resolve_system_path_for_session,
    _run_with_db,
    _session_for_character,
    _sync_condition_modifiers_for,
)


@mcp.tool()
def system_info(system: str = "", session_id: int = 0, section: str = "all") -> str:
    """Show what a system pack provides: actions, attributes, derived stats, build options.

    Use this to discover action names, attribute names, and formulas before
    calling rules_calc, rules_resolve, or character_build.

    system: system pack name (e.g. "mm3e", "pf2e").
    session_id: alternatively, resolve the system from a session's rules_system metadata.
    section: "actions", "defaults", "derived", "build", "constraints", "resolution", "combat", or "all".
    """
    from lorekit.db import LoreKitError, require_db

    if not system and session_id <= 0:
        return "ERROR: Provide either system (pack name) or session_id."

    try:
        if system:
            pack_dir = resolve_system_path(system)
            if not pack_dir:
                return f"ERROR: System pack '{system}' not found."
        else:
            db = require_db()
            try:
                pack_dir = _resolve_system_path_for_session(db, session_id)
                if not pack_dir:
                    return "ERROR: No rules_system set for this session."
            finally:
                db.close()

        from lorekit.rules import system_info as _system_info

        return _system_info(pack_dir, section)
    except (LoreKitError, FileNotFoundError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def rules_check(character_id: int | str, check: str, dc: int, system_path: str = "") -> str:
    """Roll a derived stat against a DC. Reads pre-computed values (run rules_calc first).

    Returns the roll result with success/failure and margin.

    character_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata
    and looks for the pack under systems/<rules_system>/ in the project root.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if not system_path:
            system_path, _, err = _resolve_system_path_for_character(db, character_id)
            if err:
                return err

        from lorekit.rules import rules_check as _rules_check

        return _rules_check(db, character_id, check, dc, system_path)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def rules_resolve(
    attacker_id: int | str, defender_id: int | str, action: str, options: str = "{}", system_path: str = ""
) -> str:
    """Resolve a combat action between two characters.

    Rolls attack vs defense, then applies damage/effects per the system's
    resolution rules (threshold for pf2e, degree for mm3e).

    Both characters must have derived stats computed (run rules_calc first).

    attacker_id/defender_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata
    and looks for the pack under systems/<rules_system>/ in the project root.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        attacker_id = _resolve_character(db, attacker_id)
        defender_id = _resolve_character(db, defender_id)
        if not system_path:
            system_path, session_id, err = _resolve_system_path_for_character(db, attacker_id)
            if err:
                return err
        else:
            session_id = _session_for_character(db, attacker_id)

        opts = json.loads(options) if options else {}

        # Area effect: options contains "area" dict
        area = opts.pop("area", None)
        if area:
            from lorekit.combat import resolve_area_action

            radius = area.get("radius", 0)
            center = area.get("center", "target")
            exclude_self = area.get("exclude_self", True)

            # Resolve center zone name
            if center == "target":
                if defender_id <= 0:
                    return "ERROR: area.center is 'target' but no defender_id provided"
                # Look up defender's zone name
                from lorekit.encounter import (
                    _get_active_encounter,
                    _get_character_zone,
                    _zone_id_to_name,
                )

                enc = _get_active_encounter(db, session_id)
                if enc is None:
                    return "ERROR: No active encounter — area effects require an encounter"
                def_zid = _get_character_zone(db, enc[0], defender_id)
                if def_zid is None:
                    return f"ERROR: Defender {defender_id} is not placed in the encounter"
                center_zone = _zone_id_to_name(db, def_zid)
            elif center == "self":
                center_zone = "self"
            else:
                center_zone = center

            return resolve_area_action(
                db,
                attacker_id,
                action,
                system_path,
                center_zone,
                radius,
                exclude_self,
                opts,
            )

        from lorekit.combat import resolve_action

        return resolve_action(db, attacker_id, defender_id, action, system_path, opts)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


def rules_calc(character_id: int | str, system_path: str = "") -> str:
    """Recompute all derived stats for a character using the rules engine.

    Loads the system pack, reads the character's base attributes, resolves
    the dependency graph, writes derived stats back to the sheet, and
    returns a summary of what changed.

    character_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata
    and looks for the pack under systems/<rules_system>/ in the project root.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if not system_path:
            system_path, _, err = _resolve_system_path_for_character(db, character_id)
            if err:
                return err

        from lorekit.rules import rules_calc as _rules_calc

        return _rules_calc(db, character_id, system_path)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


def end_turn(character_id: int | str, system_path: str = "") -> str:
    """Tick durations on a character's combat modifiers at end of turn.

    Processes each modifier according to the system pack's end_turn config:
    - rounds: decrement duration, remove when expired
    - save_ends (D&D): roll a save, remove on success

    Automatically recomputes derived stats when modifiers expire.

    character_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if not system_path:
            system_path, _, err = _resolve_system_path_for_character(db, character_id)
            if err:
                return err

        from lorekit.combat import end_turn as _end_turn

        return _end_turn(db, character_id, system_path)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def combat_modifier(
    character_id: int | str,
    action: str,
    source: str = "",
    target_stat: str = "",
    value: int = 0,
    modifier_type: str = "buff",
    bonus_type: str = "",
    duration_type: str = "encounter",
    duration: int = 0,
    save_stat: str = "",
    save_dc: int = 0,
    metadata: str = "",
) -> str:
    """Manage transient combat modifiers on a character.

    character_id: numeric ID or character name (case-insensitive).
    action: "add", "list", "remove", "clear", "activate", "deactivate",
            or "switch_alternate".

    add — apply a transient modifier. Requires source, target_stat, value.
      Optional metadata (JSON) for reactions/triggers/contagious flags.
    list — show all active modifiers on the character.
    remove — remove a modifier by source name.
    clear — remove all encounter/rounds/concentration modifiers.
    activate — activate a sustained power by ability name (source=ability name).
      Reads on_activate.apply_modifiers from the ability JSON.
    deactivate — deactivate a sustained power (source=ability name).
    switch_alternate — switch active power in array (source=array name,
      target_stat=alternate name to activate).
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if action == "add":
            if not source or not target_stat:
                return "ERROR: 'add' requires source and target_stat"
            meta_val = metadata or None
            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "bonus_type, duration_type, duration, save_stat, save_dc, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET "
                "value = excluded.value, bonus_type = excluded.bonus_type, "
                "duration_type = excluded.duration_type, duration = excluded.duration, "
                "save_stat = excluded.save_stat, save_dc = excluded.save_dc, "
                "metadata = excluded.metadata",
                (
                    character_id,
                    source,
                    target_stat,
                    modifier_type,
                    value,
                    bonus_type or None,
                    duration_type,
                    duration or None,
                    save_stat or None,
                    save_dc or None,
                    meta_val,
                ),
            )
            db.commit()
            type_tag = f" [{bonus_type}]" if bonus_type else ""
            result = (
                f"MODIFIER ADDED: {source} → {target_stat} {value:+d}{type_tag} "
                f"({duration_type}{f', {duration} rounds' if duration else ''})"
            )
            recalc = try_rules_calc(db, character_id)
            if recalc:
                result += "\n" + recalc
            result += _sync_condition_modifiers_for(db, character_id)
            return result

        elif action == "list":
            rows = db.execute(
                "SELECT source, target_stat, value, bonus_type, modifier_type, "
                "duration_type, duration FROM combat_state "
                "WHERE character_id = ? ORDER BY created_at",
                (character_id,),
            ).fetchall()
            if not rows:
                return f"No active modifiers on character {character_id}"
            lines = [f"MODIFIERS: character {character_id}"]
            for src, stat, val, btype, mtype, dtype, dur in rows:
                type_tag = f" [{btype}]" if btype else ""
                dur_info = f" ({dur} rounds)" if dur else ""
                lines.append(f"  {src}: {stat} {val:+d}{type_tag} ({dtype}{dur_info})")
            return "\n".join(lines)

        elif action == "remove":
            if not source:
                return "ERROR: 'remove' requires source"
            deleted = db.execute(
                "DELETE FROM combat_state WHERE character_id = ? AND source = ?",
                (character_id, source),
            ).rowcount
            db.commit()
            result = f"REMOVED: {deleted} modifier(s) from source '{source}'"
            if deleted:
                recalc = try_rules_calc(db, character_id)
                if recalc:
                    result += "\n" + recalc
                result += _sync_condition_modifiers_for(db, character_id)
            return result

        elif action == "clear":
            deleted = db.execute(
                "DELETE FROM combat_state WHERE character_id = ? "
                "AND duration_type IN ('encounter', 'rounds', 'concentration')",
                (character_id,),
            ).rowcount
            db.commit()
            result = f"CLEARED: {deleted} transient modifier(s) from character {character_id}"
            if deleted:
                recalc = try_rules_calc(db, character_id)
                if recalc:
                    result += "\n" + recalc
                result += _sync_condition_modifiers_for(db, character_id)
            return result

        elif action == "activate":
            if not source:
                return "ERROR: 'activate' requires source (ability name)"
            system_path = _resolve_system_path_for_session(db, _session_for_character(db, character_id))
            from lorekit.combat import activate_power

            return activate_power(db, character_id, source, system_path)

        elif action == "deactivate":
            if not source:
                return "ERROR: 'deactivate' requires source (ability name)"
            system_path = _resolve_system_path_for_session(db, _session_for_character(db, character_id))
            from lorekit.combat import deactivate_power

            return deactivate_power(db, character_id, source, system_path)

        elif action == "switch_alternate":
            if not source or not target_stat:
                return "ERROR: 'switch_alternate' requires source (array name) and target_stat (alternate name)"
            system_path = _resolve_system_path_for_session(db, _session_for_character(db, character_id))
            from lorekit.combat import switch_alternate

            return switch_alternate(db, character_id, source, target_stat, system_path)

        else:
            return (
                f"ERROR: Unknown action '{action}'. "
                "Use add, list, remove, clear, activate, deactivate, or switch_alternate."
            )

    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


def rules_modifiers(character_id: int | str, stat: str = "", system_path: str = "") -> str:
    """Show modifier decomposition for a character's stats.

    Displays all active modifiers with their types, sources, and which
    ones survived stacking. If stat is specified, shows only that stat;
    otherwise shows all stats with active modifiers.

    character_id: numeric ID or character name (case-insensitive).
    If system_path is empty, reads the session's 'rules_system' metadata.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        character_id = _resolve_character(db, character_id)
        if not system_path:
            system_path, _, err = _resolve_system_path_for_character(db, character_id)
            if err:
                return err

        from cruncher.stacking import (
            ModifierEntry,
            decompose_modifiers,
            load_stacking_policy,
        )
        from cruncher.system_pack import load_system_pack
        from lorekit.rules import (
            _load_combat_modifiers,
            load_character_data,
        )

        pack = load_system_pack(system_path)
        char = load_character_data(db, character_id)
        policy = load_stacking_policy(pack.stacking)

        # Collect modifiers from character attributes
        all_mods: list[ModifierEntry] = []
        for cat, attrs in char.attributes.items():
            for key, val in attrs.items():
                if key.startswith("bonus_"):
                    try:
                        num_val = float(val) if "." in val else int(val)
                    except (ValueError, TypeError):
                        continue
                    if num_val != 0:
                        all_mods.append(ModifierEntry(key, num_val, source=cat))

        # Add combat_state modifiers
        all_mods.extend(_load_combat_modifiers(db, character_id))

        if not all_mods:
            return f"No active modifiers on {char.name}"

        decomposed = decompose_modifiers(all_mods, policy, stat=stat or None)

        if not decomposed:
            return f"No modifiers found for stat '{stat}' on {char.name}"

        lines = [f"MODIFIERS: {char.name}" + (f" — {stat}" if stat else "")]
        for d in decomposed:
            status = "" if d.active else " (suppressed)"
            type_tag = f" [{d.bonus_type}]" if d.bonus_type else ""
            lines.append(f"  {d.source}: {d.target_stat} {d.value:+g}{type_tag}{status}")
        return "\n".join(lines)

    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()
