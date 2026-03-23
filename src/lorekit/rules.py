"""Rules orchestration — DB glue between cruncher and lorekit.

Loads character data and combat modifiers from the database, calls
cruncher's pure computation functions, and writes results back.

Also contains system_info() for human-readable system pack summaries,
and load_character_data() for assembling CharacterData from DB rows.
"""

from __future__ import annotations

import json
import os
from typing import Any

from cruncher import (
    ModifierEntry,
    load_system_pack,
    process_build,
    recalculate,
)
from cruncher.types import CharacterData
from lorekit.db import LoreKitError

# ---------------------------------------------------------------------------
# Character data extraction (from DB rows)
# ---------------------------------------------------------------------------


def load_character_data(db, character_id: int) -> CharacterData:
    """Load character data from the database."""
    row = db.execute(
        "SELECT id, session_id, name, level, type FROM characters WHERE id = ?",
        (character_id,),
    ).fetchone()
    if row is None:
        raise LoreKitError(f"Character {character_id} not found")

    char = CharacterData(
        character_id=row[0],
        session_id=row[1],
        name=row[2],
        level=row[3],
        char_type=row[4],
    )

    # Load attributes grouped by category
    for cat, key, val in db.execute(
        "SELECT category, key, value FROM character_attributes WHERE character_id = ? ORDER BY category, key",
        (character_id,),
    ):
        char.attributes.setdefault(cat, {})[key] = val

    # Load abilities
    for name, desc, category, uses, cost in db.execute(
        "SELECT name, description, category, uses, cost FROM character_abilities WHERE character_id = ?",
        (character_id,),
    ):
        char.abilities.append({"name": name, "description": desc, "category": category, "uses": uses, "cost": cost})

    # Load equipped items
    for name, desc, qty, equipped in db.execute(
        "SELECT name, description, quantity, equipped FROM character_inventory WHERE character_id = ? AND equipped = 1",
        (character_id,),
    ):
        char.items.append({"name": name, "description": desc, "quantity": qty})

    return char


# ---------------------------------------------------------------------------
# Combat modifier loading
# ---------------------------------------------------------------------------


def load_combat_modifiers(db, character_id: int) -> list[ModifierEntry]:
    """Load active combat_state rows as ModifierEntry items."""
    rows = db.execute(
        "SELECT target_stat, value, bonus_type, source FROM combat_state WHERE character_id = ?",
        (character_id,),
    ).fetchall()
    return [
        ModifierEntry(
            target_stat=row[0],
            value=row[1],
            bonus_type=row[2],
            source=row[3],
        )
        for row in rows
    ]


# Keep old name as alias for code that imports it
_load_combat_modifiers = load_combat_modifiers


# ---------------------------------------------------------------------------
# Write results back to DB
# ---------------------------------------------------------------------------


def write_derived(db, character_id: int, derived: dict[str, Any]) -> int:
    """Write derived stats to character_attributes with category='derived'.

    Returns the number of attributes written.
    """
    count = 0
    for key, value in derived.items():
        if isinstance(value, str) and value.startswith("ERROR:"):
            continue  # Skip errored stats
        db.execute(
            "INSERT INTO character_attributes (character_id, category, key, value) "
            "VALUES (?, 'derived', ?, ?) "
            "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
            (character_id, key, str(value)),
        )
        count += 1
    db.commit()
    return count


# ---------------------------------------------------------------------------
# Build engine integration
# ---------------------------------------------------------------------------


def _run_build(db, character_id: int, pack_dir: str, char: CharacterData):
    """Run the build engine and write results to the DB.

    Build attributes are written under category='build'. This must
    run before recalculate() so derived formulas can reference them.
    Returns the BuildResult (or None if nothing to process).
    """
    # Capture old cost values for diff reporting
    old_build = char.attributes.get("build", {})

    build_result = process_build(
        pack_dir,
        char.attributes,
        char.abilities,
        char.level,
        char_items=char.items,
    )

    if not build_result.attributes and not build_result.costs:
        return None

    # Compute cost diffs
    for cost_cat, cost_val in build_result.costs.items():
        cost_key = f"cost_{cost_cat}"
        old_val = float(old_build.get(cost_key, "0"))
        if cost_val != old_val:
            build_result.cost_changes[cost_cat] = (old_val, cost_val)

    # Write build attributes to DB and merge into character data
    count = 0
    build_attrs = char.attributes.setdefault("build", {})
    for key, value in build_result.attributes.items():
        str_val = str(value)
        db.execute(
            "INSERT INTO character_attributes (character_id, category, key, value) "
            "VALUES (?, 'build', ?, ?) "
            "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
            (character_id, key, str_val),
        )
        build_attrs[key] = str_val
        count += 1

    # Write budget tracking as build attributes
    if build_result.budget_total:
        for budget_key, budget_val in [
            ("budget_total", build_result.budget_total),
            ("budget_spent", build_result.budget_spent),
        ]:
            str_val = str(budget_val)
            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'build', ?, ?) "
                "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
                (character_id, budget_key, str_val),
            )
            build_attrs[budget_key] = str_val

        # Per-category costs
        for cost_cat, cost_val in build_result.costs.items():
            cost_key = f"cost_{cost_cat}"
            str_val = str(cost_val)
            db.execute(
                "INSERT INTO character_attributes (character_id, category, key, value) "
                "VALUES (?, 'build', ?, ?) "
                "ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value",
                (character_id, cost_key, str_val),
            )
            build_attrs[cost_key] = str_val

    if count:
        db.commit()

    return build_result


# ---------------------------------------------------------------------------
# Rules check (roll against DC)
# ---------------------------------------------------------------------------


def rules_check(db, character_id: int, check: str, dc: int, pack_dir: str) -> str:
    """Read a pre-computed derived stat and roll against a DC."""
    from cruncher.dice import roll_expr

    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    # Read from derived attributes
    derived = char.attributes.get("derived", {})
    bonus_str = derived.get(check)
    if bonus_str is None:
        raise LoreKitError(f"Stat '{check}' not found in derived attributes for {char.name}. Run rules_calc first.")

    bonus = int(bonus_str)
    result = roll_expr(pack.dice)
    roll = result["total"]
    total = roll + bonus

    outcome = "SUCCESS" if total >= dc else "FAILURE"
    margin = abs(total - dc)

    return (
        f"CHECK: {char.name} — {check}\n"
        f"ROLL: {pack.dice}({roll}) + {bonus} = {total} vs DC {dc}\n"
        f"RESULT: {outcome} (by {margin})"
    )


# ---------------------------------------------------------------------------
# Auto-calc entry point
# ---------------------------------------------------------------------------


def try_rules_calc(db, character_id: int) -> str:
    """Auto-run rules_calc if the character's session has a rules_system.

    Looks up session_id from the character row, then resolves the system pack
    path from session_meta.  Returns the rules_calc summary string, or empty
    string if not applicable (no system, missing pack dir, etc.).

    This is the single entry-point every write-side function should call after
    modifying combat_state or character_attributes.
    """
    row = db.execute(
        "SELECT session_id FROM characters WHERE id = ?",
        (character_id,),
    ).fetchone()
    if row is None:
        return ""
    session_id = row[0]

    meta_row = db.execute(
        "SELECT value FROM session_meta WHERE session_id = ? AND key = 'rules_system'",
        (session_id,),
    ).fetchone()
    if meta_row is None:
        return ""

    system_name = meta_row[0]
    system_path = resolve_system_path(system_name)

    if not system_path:
        return ""

    try:
        return rules_calc(db, character_id, system_path)
    except Exception as e:
        return f"RULES_CALC_WARNING: {e}"


# ---------------------------------------------------------------------------
# Full recalculation pipeline
# ---------------------------------------------------------------------------


def rules_calc(db, character_id: int, pack_dir: str) -> str:
    """Full recalculation pipeline: build → compute → write back → report."""
    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    # Run build engine first — writes build attributes to DB and merges
    # them into char so derived formulas can reference them
    build_result = _run_build(db, character_id, pack_dir, char)

    # Load combat modifiers and pass to pure recalculate
    modifiers = load_combat_modifiers(db, character_id)
    result = recalculate(pack, char, modifiers=modifiers)

    if not result.derived:
        return f"RULES_CALC: {char.name} — no derived stats defined in system pack"

    written = write_derived(db, character_id, result.derived)

    lines = [f"RULES_CALC: {char.name} — {written} stats computed"]

    if result.changes:
        lines.append("CHANGES:")
        for stat, (old, new) in result.changes.items():
            if old is None:
                lines.append(f"  {stat}: → {new}")
            else:
                lines.append(f"  {stat}: {old} → {new}")

    # Report errored derived stats (formula evaluation failures)
    errored = {k: v for k, v in result.derived.items() if isinstance(v, str) and v.startswith("ERROR:")}
    if errored:
        lines.append("⚠ FORMULA ERRORS:")
        for stat, err in errored.items():
            lines.append(f"  {stat}: {err}")

    if result.violations:
        lines.append("VIOLATIONS:")
        for v in result.violations:
            lines.append(f"  ⚠ {v}")

    # Budget summary (only for systems with budget, e.g. mm3e)
    if build_result and build_result.budget_total:
        remaining = build_result.budget_total - build_result.budget_spent
        lines.append(f"BUDGET: {build_result.budget_spent}/{build_result.budget_total} spent ({remaining} remaining)")
        if build_result.costs:
            for cat, cost in sorted(build_result.costs.items()):
                if cost:
                    lines.append(f"  {cat}: {cost}")
                    cat_breakdown = build_result.ability_costs.get(cat, {})
                    for ab_name, ab_cost in sorted(cat_breakdown.items()):
                        lines.append(f"    {ab_name}: {ab_cost}")
        if build_result.cost_changes:
            lines.append("COST CHANGES:")
            for cat, (old, new) in sorted(build_result.cost_changes.items()):
                delta = new - old
                sign = "+" if delta > 0 else ""
                lines.append(f"  {cat}: {int(old)} → {int(new)} ({sign}{int(delta)})")
        if build_result.budget_spent > build_result.budget_total:
            over = build_result.budget_spent - build_result.budget_total
            lines.append(f"WARNING: Over budget by {int(over)} points!")

    # Surface build warnings (uncosted abilities, missing sources, etc.)
    if build_result and build_result.warnings:
        lines.append("BUILD WARNINGS:")
        for w in build_result.warnings:
            lines.append(f"  {w}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System info (human-readable pack summary)
# ---------------------------------------------------------------------------


def _group_by_prefix(names: dict | list, min_group: int = 2) -> list[tuple[str, list[str]]]:
    """Group variable names by detected prefix for readable display."""
    keys = sorted(names if isinstance(names, list) else names.keys())

    groups: dict[str, list[str]] = {}
    for key in keys:
        if "_" in key:
            prefix = key[: key.index("_")]
        else:
            prefix = ""
        groups.setdefault(prefix, []).append(key)

    result: list[tuple[str, list[str]]] = []
    ungrouped: list[str] = []
    for prefix in sorted(groups):
        members = groups[prefix]
        if prefix and len(members) >= min_group:
            result.append((f"{prefix}_*", members))
        else:
            ungrouped.extend(members)

    if ungrouped:
        result.append(("other", ungrouped))

    return result


def _summarize_on_hit(on_hit: dict) -> str:
    """One-line summary of an on_hit block."""
    parts = []
    if on_hit.get("damage_roll") and on_hit.get("subtract_from"):
        parts.append(f"damage → {on_hit['subtract_from']}")
    if on_hit.get("apply_modifiers"):
        mods = on_hit["apply_modifiers"]
        targets = [m["target_stat"] for m in mods]
        parts.append(f"modifiers({', '.join(targets)})")
    if on_hit.get("push"):
        direction = on_hit.get("push_direction", "away")
        parts.append(f"push {on_hit['push']} {direction}")
    if on_hit.get("damage_rank_stat"):
        parts.append(f"damage_rank={on_hit['damage_rank_stat']}")
    return ", ".join(parts) if parts else "none"


def system_info(pack_dir: str, section: str = "all") -> str:
    """Return a human-readable summary of what a system pack provides."""
    system_path = os.path.join(pack_dir, "system.json")
    if not os.path.isfile(system_path):
        raise FileNotFoundError(f"system.json not found in {pack_dir}")

    with open(system_path) as f:
        data = json.load(f)
    meta = data.get("meta", {})
    pack_name = meta.get("name", os.path.basename(pack_dir))
    dice = meta.get("dice", "")

    valid_sections = {"actions", "defaults", "derived", "build", "constraints", "resolution", "combat", "all"}
    if section not in valid_sections:
        return f"ERROR: Unknown section '{section}'. Valid: {', '.join(sorted(valid_sections))}"

    sections: list[str] = []

    # Header
    header_parts = [f"SYSTEM: {pack_name}"]
    if dice:
        header_parts.append(f"Dice: {dice}")
    sections.append("\n".join(header_parts))

    # Actions
    if section in ("all", "actions"):
        actions = data.get("actions", {})
        if actions:
            lines = ["", "ACTIONS:"]
            for name, adef in actions.items():
                atk = adef.get("attack_stat", "?")
                dfn = adef.get("defense_stat", "?")
                rng = adef.get("range", "?")
                contested = " (contested)" if adef.get("contested") else ""

                effect_parts = []
                if adef.get("damage_rank_stat"):
                    effect_parts.append(f"damage_rank={adef['damage_rank_stat']}")
                on_hit = adef.get("on_hit")
                if on_hit:
                    effect_parts.append(_summarize_on_hit(on_hit))
                effect = f"  effect: {', '.join(effect_parts)}" if effect_parts else ""

                lines.append(f"  {name}: {atk} vs {dfn}, range={rng}{contested}")
                if effect:
                    lines.append(f"    {effect}")
            sections.append("\n".join(lines))

    # Defaults
    if section in ("all", "defaults"):
        defaults = data.get("defaults", {})
        if defaults:
            lines = ["", "DEFAULTS (settable attributes):"]
            for label, keys in _group_by_prefix(defaults):
                lines.append(f"  {label}: {', '.join(keys)}")
            sections.append("\n".join(lines))

    # Derived
    if section in ("all", "derived"):
        derived = data.get("derived", {})
        if derived:
            lines = ["", "DERIVED (computed stats):"]
            for label, keys in _group_by_prefix(derived):
                lines.append(f"  {label}: {', '.join(keys)}")

            if section == "derived":
                lines.append("")
                lines.append("FORMULAS:")
                for key in sorted(derived):
                    lines.append(f"  {key} = {derived[key]}")
            sections.append("\n".join(lines))

    # Build
    if section in ("all", "build"):
        build = data.get("build", {})
        if build:
            lines = ["", "BUILD (character construction):"]
            budget = build.get("budget")
            if budget:
                lines.append(f"  budget: {budget.get('total', '?')}")
            for cat, cfg in build.items():
                if cat == "budget":
                    continue
                if not isinstance(cfg, dict):
                    continue
                parts = []
                if "keys" in cfg:
                    parts.append(f"keys=[{', '.join(cfg['keys'])}]")
                if "source" in cfg:
                    parts.append(f"source={cfg['source']}")
                if "cost_per_rank" in cfg:
                    parts.append(f"cost={cfg['cost_per_rank']}/rank")
                if "writes" in cfg:
                    writes = cfg["writes"]
                    parts.append(f"writes=[{', '.join(writes.keys())}]")
                if cfg.get("pipeline"):
                    parts.append("pipeline")
                if cfg.get("feeds"):
                    parts.append("feeds")
                if cfg.get("effects"):
                    parts.append("effects")
                lines.append(f"  {cat}: {', '.join(parts)}")
            sections.append("\n".join(lines))

    # Constraints
    if section in ("all", "constraints"):
        constraints = data.get("constraints", {})
        if constraints:
            lines = ["", "CONSTRAINTS:"]
            for name, expr in constraints.items():
                lines.append(f"  {name}: {expr}")
            sections.append("\n".join(lines))

    # Resolution
    if section in ("all", "resolution"):
        res = data.get("resolution", {})
        if res:
            lines = ["", "RESOLUTION:"]
            res_type = res.get("type", "?")
            parts = [f"type={res_type}"]
            if "defense_dc_offset" in res:
                parts.append(f"dc_offset={res['defense_dc_offset']}")
            if "resistance_stat" in res:
                parts.append(f"resistance={res['resistance_stat']}")
            if "dc_base" in res:
                parts.append(f"dc_base={res['dc_base']}")
            lines.append(f"  {', '.join(parts)}")

            on_failure = res.get("on_failure", {})
            if on_failure:
                for degree, effect in sorted(on_failure.items()):
                    label = effect.get("label", "")
                    inc = effect.get("increment", {})
                    desc_parts = []
                    if inc:
                        desc_parts.append("+".join(f"{k}={v}" for k, v in inc.items()))
                    if label:
                        desc_parts.append(label)
                    lines.append(f"  degree {degree}: {', '.join(desc_parts)}")
            sections.append("\n".join(lines))

    # Combat positioning
    if section in ("all", "combat"):
        combat = data.get("combat", {})
        if combat:
            lines = ["", "COMBAT (positioning):"]
            lines.append(
                f"  zone_scale={combat.get('zone_scale', 1)}, "
                f"unit={combat.get('movement_unit', 'zone')}, "
                f"melee_range={combat.get('melee_range', 0)}"
            )
            zone_tags = combat.get("zone_tags", {})
            if zone_tags:
                lines.append("  Zone tags:")
                for tag, cfg in zone_tags.items():
                    parts = []
                    if "target_stat" in cfg:
                        parts.append(f"{cfg['target_stat']} {cfg.get('value', 0):+d}")
                    if "movement_multiplier" in cfg:
                        parts.append(f"movement x{cfg['movement_multiplier']}")
                    if "miss_chance" in cfg:
                        parts.append(f"miss {int(cfg['miss_chance'] * 100)}%")
                    lines.append(f"    {tag}: {', '.join(parts)}")
            sections.append("\n".join(lines))

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def project_root() -> str:
    """Return the project root directory.

    Resolution order:
    1. LOREKIT_ROOT env var (explicit override)
    2. Walk up from this file until a directory containing systems/ is found

    This is the single source of truth — all other modules should call this
    instead of computing paths from __file__.
    """
    from_env = os.environ.get("LOREKIT_ROOT")
    if from_env:
        return from_env

    here = os.path.dirname(os.path.abspath(__file__))
    candidate = here
    for _ in range(10):  # safety limit
        if os.path.isdir(os.path.join(candidate, "systems")):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break  # filesystem root
        candidate = parent

    # Last resort: assume src/lorekit/ layout
    return os.path.dirname(os.path.dirname(here))


def resolve_system_path(system_name: str) -> str | None:
    """Resolve a system pack name to its data directory path.

    Resolution order:
    1. Try importing cruncher_<name> package (e.g. cruncher_mm3e.pack_path())
    2. Fall back to systems/<name>/ under the project root
    3. Fall back to systems/<name>/src/cruncher_<name>/data/ (dev layout)

    Returns None if the system pack can't be found.
    """
    # Try installed package first
    pkg_name = f"cruncher_{system_name}"
    try:
        mod = __import__(pkg_name)
        path = mod.pack_path()
        if os.path.isdir(path):
            return path
    except (ImportError, AttributeError):
        pass

    # Fall back to local systems/ directory
    root = project_root()

    # Direct path (legacy layout or pf2e-style flat)
    direct = os.path.join(root, "systems", system_name)
    if os.path.isfile(os.path.join(direct, "system.json")):
        return direct

    # Dev layout: systems/<name>/src/cruncher_<name>/data/
    dev_path = os.path.join(direct, "src", pkg_name, "data")
    if os.path.isfile(os.path.join(dev_path, "system.json")):
        return dev_path

    return None
