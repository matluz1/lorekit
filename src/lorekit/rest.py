"""rest.py — Mechanical rest resolution.

Reads rest rules from the system pack and applies them to all PCs
in a session: restore stats via formulas, reset ability uses,
clear combat modifiers, and optionally advance time.

The engine is domain-agnostic — it executes JSON instructions from
the system pack without knowing what "rest" means.
"""

from __future__ import annotations

import json
import os
import re

from lorekit.db import LoreKitError
from lorekit.queries import get_attribute, get_attribute_by_key, upsert_attribute


def _load_rest_config(pack_dir: str, rest_type: str) -> dict:
    """Load and validate rest config from system.json."""
    system_json_path = os.path.join(pack_dir, "system.json")
    with open(system_json_path) as f:
        system_data = json.load(f)

    rest_cfg = system_data.get("rest", {})
    if not rest_cfg:
        raise LoreKitError("No rest rules defined in system pack")

    type_cfg = rest_cfg.get(rest_type)
    if type_cfg is None:
        available = ", ".join(rest_cfg.keys())
        raise LoreKitError(f"Unknown rest type '{rest_type}'. Available: {available}")
    return type_cfg


def _restore_stats(db, cid: int, char, type_cfg: dict, pack) -> list[str]:
    """Restore stats via formulas from the rest config."""
    from cruncher.errors import CruncherError
    from cruncher.formulas import FormulaContext, calc

    restore = type_cfg.get("restore", {})
    if not restore:
        return []

    values: dict[str, float] = {}
    for cat_attrs in char.attributes.values():
        for k, v in cat_attrs.items():
            try:
                values[k] = float(v)
            except (ValueError, TypeError):
                pass
    values["level"] = float(char.level)

    ctx = FormulaContext(values=values, tables=pack.tables)
    lines = []
    for stat, formula_str in restore.items():
        try:
            new_val = int(calc(formula_str, ctx))
        except (ValueError, ZeroDivisionError, KeyError, CruncherError) as e:
            lines.append(f"    {stat}: formula error ({e})")
            continue
        old_val = get_attribute_by_key(db, cid, stat) or "0"
        upsert_attribute(db, cid, "stat", stat, str(new_val))
        lines.append(f"    {stat}: {old_val} → {new_val}")
    return lines


def _reset_ability_uses(db, cid: int, type_cfg: dict) -> list[str]:
    """Reset ability uses matching the configured categories."""
    reset_uses = type_cfg.get("reset_uses", [])
    if not reset_uses:
        return []

    reset_count = 0
    for use_category in reset_uses:
        keyword = use_category.replace("per_", "")
        rows = db.execute(
            "SELECT id, name, uses FROM character_abilities WHERE character_id = ? AND uses LIKE ?",
            (cid, f"%{keyword}%"),
        ).fetchall()
        for aid, aname, uses in rows:
            m = re.match(r"(\d+)/(\d+)\s*(.*)", uses)
            if m:
                max_uses = m.group(2)
                unit = m.group(3)
                new_uses = f"{max_uses}/{max_uses} {unit}".strip()
                db.execute("UPDATE character_abilities SET uses = ? WHERE id = ?", (new_uses, aid))
                reset_count += 1

    if reset_count:
        return [f"    Abilities reset: {reset_count}"]
    return []


def _reset_attributes(db, cid: int, type_cfg: dict) -> list[str]:
    """Reset named attributes to configured values."""
    lines = []
    for ra in type_cfg.get("reset_attributes", []):
        cat = ra["category"]
        key = ra["key"]
        val = str(ra.get("value", "0"))
        old_val = get_attribute(db, cid, cat, key)
        if old_val is not None and old_val != val:
            upsert_attribute(db, cid, cat, key, val)
            lines.append(f"    {key}: {old_val} → {val}")
    return lines


def _clear_modifiers(db, cid: int, type_cfg: dict) -> list[str]:
    """Clear combat modifiers matching the configured duration types."""
    clear_types = type_cfg.get("clear_duration_types", [])
    if not clear_types:
        return []
    ph = ",".join("?" * len(clear_types))
    cleared = db.execute(
        f"DELETE FROM combat_state WHERE character_id = ? AND duration_type IN ({ph})",
        (cid, *clear_types),
    ).rowcount
    if cleared:
        return [f"    Modifiers cleared: {cleared}"]
    return []


def _auto_advance_time(db, session_id: int, type_cfg: dict) -> list[str]:
    """Advance narrative time if configured."""
    time_cfg = type_cfg.get("time_advance")
    if not time_cfg:
        return []
    try:
        from lorekit.narrative.time import advance as time_advance

        result = time_advance(db, session_id, time_cfg["amount"], time_cfg["unit"])
        return [result]
    except (LoreKitError, ValueError) as e:
        return [f"  Time advance skipped: {e}"]


def rest(db, session_id: int, rest_type: str, pack_dir: str) -> str:
    """Apply rest rules to all PCs in the session.

    rest_type: key in the system pack's "rest" section (e.g. "short", "long")
    pack_dir: path to the system pack directory
    """
    from cruncher.system_pack import load_system_pack
    from lorekit.rules import load_character_data, try_rules_calc

    type_cfg = _load_rest_config(pack_dir, rest_type)
    pack = load_system_pack(pack_dir)

    pc_rows = db.execute(
        "SELECT id, name FROM characters WHERE session_id = ? AND type = 'pc'",
        (session_id,),
    ).fetchall()
    if not pc_rows:
        return f"REST ({rest_type}): No PCs in session {session_id}"

    lines = [f"REST ({rest_type.upper()})"]

    for cid, cname in pc_rows:
        char_lines = [f"  {cname}:"]
        char = load_character_data(db, cid)

        char_lines.extend(_restore_stats(db, cid, char, type_cfg, pack))
        char_lines.extend(_reset_ability_uses(db, cid, type_cfg))
        char_lines.extend(_reset_attributes(db, cid, type_cfg))
        char_lines.extend(_clear_modifiers(db, cid, type_cfg))

        try_rules_calc(db, cid)

        if len(char_lines) > 1:
            lines.extend(char_lines)
        else:
            lines.append(f"  {cname}: no changes")

    db.commit()
    lines.extend(_auto_advance_time(db, session_id, type_cfg))

    return "\n".join(lines)
