"""Shared helper functions used across multiple tool modules."""

import json

from lorekit.rules import resolve_system_path, try_rules_calc


def _resolve_character(db, identifier, session_id: int | None = None) -> int:
    """Resolve a character by ID or name.

    - int or numeric string → used as ID directly
    - string → case-insensitive name search, scoped to session_id if given
    - Raises LoreKitError on not found or ambiguous match
    """
    from lorekit.db import LoreKitError

    # Numeric passthrough
    if isinstance(identifier, int):
        return identifier
    if isinstance(identifier, str) and identifier.strip().isdigit():
        return int(identifier.strip())

    # Name search
    name = identifier.strip()
    if session_id is not None:
        rows = db.execute(
            "SELECT id, name FROM characters WHERE session_id = ? AND LOWER(name) = LOWER(?)",
            (session_id, name),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, name FROM characters WHERE LOWER(name) = LOWER(?)",
            (name,),
        ).fetchall()

    if len(rows) == 1:
        return rows[0][0]
    if len(rows) == 0:
        # Fallback: check aliases
        if session_id is not None:
            alias_rows = db.execute(
                "SELECT ca.character_id FROM character_aliases ca "
                "JOIN characters c ON c.id = ca.character_id "
                "WHERE c.session_id = ? AND LOWER(ca.alias) = LOWER(?)",
                (session_id, name),
            ).fetchall()
        else:
            alias_rows = db.execute(
                "SELECT character_id FROM character_aliases WHERE LOWER(alias) = LOWER(?)",
                (name,),
            ).fetchall()
        if len(alias_rows) == 1:
            return alias_rows[0][0]
        if len(alias_rows) > 1:
            raise LoreKitError(f"Ambiguous alias '{name}'")
        raise LoreKitError(f"Character '{name}' not found")
    # Ambiguous
    options = ", ".join(f"{r[1]} (id={r[0]})" for r in rows)
    raise LoreKitError(f"Ambiguous name '{name}' — matches: {options}")


def _auto_register_reactions(db, session_id: int) -> list[str]:
    """Scan encounter participants for abilities with reaction metadata.

    For each ability that has a ``"reaction"`` field in its JSON description,
    insert a combat_state row with ``duration_type = 'reaction'`` so the
    engine's ``_check_reactions()`` can find it during resolution.
    """
    # Get all characters in the encounter
    enc = db.execute(
        "SELECT id, initiative_order FROM encounter_state WHERE session_id = ? AND status = 'active'",
        (session_id,),
    ).fetchone()
    if not enc:
        return []

    init_order = json.loads(enc[1])
    lines = []

    for char_id in init_order:
        abilities = db.execute(
            "SELECT name, description FROM character_abilities WHERE character_id = ?",
            (char_id,),
        ).fetchall()

        from lorekit.queries import get_character_name

        char_name = get_character_name(db, char_id) or f"#{char_id}"

        for ability_name, desc_str in abilities:
            try:
                desc = json.loads(desc_str)
            except (ValueError, TypeError):
                continue

            reaction = desc.get("reaction")
            if not reaction or not isinstance(reaction, dict):
                continue

            source = reaction.get("source", ability_name.lower().replace(" ", "_"))
            hook = reaction.get("hook", "before_attack")
            effect = reaction.get("effect", "substitute_defender")
            metadata = json.dumps(
                {
                    "hook": hook,
                    "effect": effect,
                    **{k: v for k, v in reaction.items() if k not in ("source", "hook", "effect")},
                }
            )

            db.execute(
                "INSERT INTO combat_state "
                "(character_id, source, target_stat, modifier_type, value, "
                "duration_type, duration, metadata) "
                "VALUES (?, ?, '_reaction', 'reaction', 0, 'reaction', 1, ?) "
                "ON CONFLICT(character_id, source, target_stat) DO UPDATE SET "
                "metadata = excluded.metadata, duration = excluded.duration",
                (char_id, source, metadata),
            )
            lines.append(f"REACTION REGISTERED: {char_name} — {source} ({hook}/{effect})")

    if lines:
        db.commit()

    return lines


def _session_for_character(db, character_id: int) -> int:
    """Look up the session_id for a character."""
    from lorekit.db import LoreKitError
    from lorekit.queries import get_character_session_id

    sid = get_character_session_id(db, character_id)
    if sid is None:
        raise LoreKitError(f"Character {character_id} not found")
    return sid


def _run_with_db(fn, *args, **kwargs):
    """Get a DB connection, call fn(db, ...), close DB."""
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        return fn(db, *args, **kwargs)
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


def _timeskip_hours(amount, unit):
    """Convert a time amount+unit to approximate hours."""
    multipliers = {
        "minutes": 1 / 60,
        "hours": 1,
        "days": 24,
        "weeks": 168,
        "months": 720,
        "years": 8760,
    }
    return amount * multipliers.get(unit, 0)


def _embed_ability_metadata(ab: dict) -> str:
    """Embed array_of/dynamic/uses_action into description JSON when present."""
    desc = ab.get("desc", "")
    array_of = ab.get("array_of")
    uses_action = ab.get("uses_action")
    if not array_of and not uses_action:
        return desc
    try:
        desc_data = json.loads(desc) if desc.strip().startswith("{") else {"desc": desc}
    except (ValueError, AttributeError):
        desc_data = {"desc": desc}
    if array_of:
        desc_data["array_of"] = array_of
    if ab.get("dynamic"):
        desc_data["dynamic"] = True
    if uses_action:
        desc_data["uses_action"] = uses_action
    return json.dumps(desc_data)


def _resolve_system_path_for_session(db, session_id: int) -> str:
    """Resolve system pack path from session metadata."""
    from lorekit.queries import get_session_meta

    system_name = get_session_meta(db, session_id, "rules_system")
    if system_name is None:
        return ""
    return resolve_system_path(system_name) or ""


def _resolve_system_path_for_character(db, character_id: int) -> tuple[str, int, str | None]:
    """Resolve system pack path from a character's session.

    Returns (system_path, session_id, error_message).
    If error_message is not None, system_path and session_id are meaningless.
    """
    from lorekit.queries import get_character_session_id

    session_id = get_character_session_id(db, character_id)
    if session_id is None:
        return "", 0, f"ERROR: Character {character_id} not found"
    system_path = _resolve_system_path_for_session(db, session_id)
    if not system_path:
        return "", session_id, "ERROR: No rules_system set for this session. Use session_meta_set to configure it."
    return system_path, session_id, None


def _sync_condition_modifiers_for(db, character_id: int) -> str:
    """Run condition modifier sync for a character. Returns any recalc output."""
    from lorekit.queries import get_character_session_id

    session_id = get_character_session_id(db, character_id)
    if session_id is None:
        return ""
    system_path = _resolve_system_path_for_session(db, session_id)
    if not system_path:
        return ""
    from cruncher.system_pack import load_system_pack
    from lorekit.combat import sync_condition_modifiers

    try:
        pack = load_system_pack(system_path)
    except Exception:
        return ""
    combat_cfg = pack.combat or {}
    cr = combat_cfg.get("condition_rules", {})
    cc = combat_cfg.get("combined_conditions", {})
    th = combat_cfg.get("condition_thresholds")
    if cr and sync_condition_modifiers(db, character_id, cr, cc, th):
        recalc = try_rules_calc(db, character_id)
        return f"\n{recalc}" if recalc else ""
    return ""


def _load_combat_cfg(db, session_id: int) -> dict:
    """Load the combat config from the session's system pack."""
    system_path = _resolve_system_path_for_session(db, session_id)
    if not system_path:
        return {}
    from cruncher.system_pack import load_system_pack

    try:
        pack = load_system_pack(system_path)
        return pack.combat
    except Exception:
        return {}
