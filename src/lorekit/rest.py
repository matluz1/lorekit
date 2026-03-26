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


def rest(db, session_id: int, rest_type: str, pack_dir: str) -> str:
    """Apply rest rules to all PCs in the session.

    rest_type: key in the system pack's "rest" section (e.g. "short", "long")
    pack_dir: path to the system pack directory
    """
    from cruncher.errors import CruncherError
    from cruncher.formulas import FormulaContext, calc
    from cruncher.system_pack import load_system_pack
    from lorekit.rules import load_character_data, try_rules_calc

    pack = load_system_pack(pack_dir)

    # Load rest config directly from system.json (not a SystemPack field)
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

    # Get all PCs in the session
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

        # --- Restore stats via formulas ---
        restore = type_cfg.get("restore", {})
        if restore:
            # Build formula context from all character attributes
            values: dict[str, float] = {}
            for cat_attrs in char.attributes.values():
                for k, v in cat_attrs.items():
                    try:
                        values[k] = float(v)
                    except (ValueError, TypeError):
                        pass
            values["level"] = float(char.level)

            ctx = FormulaContext(values=values, tables=pack.tables)

            for stat, formula_str in restore.items():
                try:
                    new_val = int(calc(formula_str, ctx))
                except (ValueError, ZeroDivisionError, KeyError, CruncherError) as e:
                    char_lines.append(f"    {stat}: formula error ({e})")
                    continue

                # Read old value
                from lorekit.queries import get_attribute_by_key

                old_val = get_attribute_by_key(db, cid, stat) or "0"

                from lorekit.queries import upsert_attribute

                upsert_attribute(db, cid, "stat", stat, str(new_val))
                char_lines.append(f"    {stat}: {old_val} → {new_val}")

        # --- Reset ability uses ---
        reset_uses = type_cfg.get("reset_uses", [])
        if reset_uses:
            reset_count = 0
            for use_category in reset_uses:
                # Match abilities where uses contains the category keyword
                # e.g. "per_encounter" matches uses LIKE '%encounter%'
                # Strip "per_" prefix for matching
                keyword = use_category.replace("per_", "")
                rows = db.execute(
                    "SELECT id, name, uses FROM character_abilities WHERE character_id = ? AND uses LIKE ?",
                    (cid, f"%{keyword}%"),
                ).fetchall()
                for aid, aname, uses in rows:
                    # Reset uses to original max (e.g. "0/3 day" → "3/3 day")
                    # Parse "N/M unit" format
                    m = re.match(r"(\d+)/(\d+)\s*(.*)", uses)
                    if m:
                        max_uses = m.group(2)
                        unit = m.group(3)
                        new_uses = f"{max_uses}/{max_uses} {unit}".strip()
                        db.execute(
                            "UPDATE character_abilities SET uses = ? WHERE id = ?",
                            (new_uses, aid),
                        )
                        reset_count += 1
            if reset_count:
                char_lines.append(f"    Abilities reset: {reset_count}")

        # --- Reset named attributes (e.g. damage_condition, damage_penalty) ---
        reset_attrs = type_cfg.get("reset_attributes", [])
        for ra in reset_attrs:
            cat = ra["category"]
            key = ra["key"]
            val = str(ra.get("value", "0"))
            from lorekit.queries import get_attribute

            old_val = get_attribute(db, cid, cat, key)
            if old_val is not None and old_val != val:
                from lorekit.queries import upsert_attribute

                upsert_attribute(db, cid, cat, key, val)
                char_lines.append(f"    {key}: {old_val} → {val}")

        # --- Clear combat modifiers ---
        clear_types = type_cfg.get("clear_duration_types", [])
        if clear_types:
            ph = ",".join("?" * len(clear_types))
            cleared = db.execute(
                f"DELETE FROM combat_state WHERE character_id = ? AND duration_type IN ({ph})",
                (cid, *clear_types),
            ).rowcount
            if cleared:
                char_lines.append(f"    Modifiers cleared: {cleared}")

        # Recalc after changes
        try_rules_calc(db, cid)

        if len(char_lines) > 1:
            lines.extend(char_lines)
        else:
            lines.append(f"  {cname}: no changes")

    db.commit()

    # --- Auto-advance time ---
    time_cfg = type_cfg.get("time_advance")
    if time_cfg:
        try:
            from lorekit.narrative.time import advance as time_advance

            amount = time_cfg["amount"]
            unit = time_cfg["unit"]
            time_result = time_advance(db, session_id, amount, unit)
            lines.append(time_result)
        except (LoreKitError, ValueError) as e:
            lines.append(f"  Time advance skipped: {e}")

    return "\n".join(lines)
