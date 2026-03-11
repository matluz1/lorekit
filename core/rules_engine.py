"""Crunch rules engine — zero-knowledge formula evaluator.

Loads a system pack (defaults, derived formulas, tables, constraints),
builds a flat variable context from character attributes, evaluates
formulas in dependency order, and validates constraints.

The engine knows nothing about RPG concepts (classes, feats, abilities,
proficiencies). All domain knowledge lives in the system pack JSON
data files.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from rules_formulas import (
    FormulaContext,
    FormulaError,
    calc,
    extract_deps,
    parse,
)
from rules_stacking import (
    ModifierEntry,
    StackingPolicy,
    load_stacking_policy,
    resolve_stacking,
)


# ---------------------------------------------------------------------------
# System pack model
# ---------------------------------------------------------------------------

@dataclass
class SystemPack:
    """Parsed representation of a system pack directory."""

    name: str = ""
    dice: str = ""

    # Default values for optional variables
    defaults: dict[str, Any] = field(default_factory=dict)

    # Derived stat formulas: {"melee_attack": "str_mod + base_attack + ...", ...}
    derived: dict[str, str] = field(default_factory=dict)

    # Lookup tables: {"base_attack_full": [1, 2, 3, ...], ...}
    tables: dict[str, list] = field(default_factory=dict)

    # Constraint expressions: {"name": "expr that should be true", ...}
    constraints: dict[str, str] = field(default_factory=dict)

    # Combat resolution config: {"type": "threshold"|"degree", ...}
    resolution: dict[str, Any] = field(default_factory=dict)

    # Action definitions: {"melee_attack": {"attack_stat": ..., "defense_stat": ..., ...}, ...}
    actions: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Stacking policy: {"group_by": ..., "positive": ..., "negative": ..., ...}
    stacking: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def load_system_pack(pack_dir: str) -> SystemPack:
    """Load a system pack from a directory of JSON files."""
    system_path = os.path.join(pack_dir, "system.json")
    if not os.path.isfile(system_path):
        raise FileNotFoundError(f"system.json not found in {pack_dir}")

    data = _load_json(system_path)
    pack = SystemPack()

    # Meta
    meta = data.get("meta", {})
    pack.name = meta.get("name", "")
    pack.dice = meta.get("dice", "")

    # Defaults for optional variables
    pack.defaults = dict(data.get("defaults", {}))

    # Derived formulas
    pack.derived = dict(data.get("derived", {}))

    # Tables
    for tbl_name, tbl_data in data.get("tables", {}).items():
        if isinstance(tbl_data, list):
            pack.tables[tbl_name] = tbl_data

    # Constraints
    pack.constraints = dict(data.get("constraints", {}))

    # Combat resolution
    pack.resolution = dict(data.get("resolution", {}))
    pack.actions = dict(data.get("actions", {}))

    # Stacking policy
    pack.stacking = dict(data.get("stacking", {}))

    return pack


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------

def _build_dep_graph(derived: dict[str, str]) -> dict[str, set[str]]:
    """Build a dependency graph: stat -> set of stats it depends on."""
    graph: dict[str, set[str]] = {}
    for stat, formula in derived.items():
        ast = parse(formula)
        deps = extract_deps(ast)
        # Only keep deps that are themselves derived stats
        graph[stat] = deps & set(derived.keys())
    return graph


def _topo_sort(graph: dict[str, set[str]]) -> list[str]:
    """Topological sort via Kahn's algorithm. Raises on cycles."""
    # Build reverse adjacency: dep -> set of nodes that depend on it
    reverse: dict[str, set[str]] = defaultdict(set)
    for node, deps in graph.items():
        for dep in deps:
            if dep in graph:
                reverse[dep].add(node)

    # Count in-degrees
    in_degree = {node: len(deps & set(graph.keys())) for node, deps in graph.items()}

    queue = [node for node, deg in in_degree.items() if deg == 0]
    result = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for dependent in reverse.get(node, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(graph):
        missing = set(graph.keys()) - set(result)
        raise FormulaError(f"Circular dependency detected among: {missing}")

    return result


# ---------------------------------------------------------------------------
# Character data extraction (from DB rows)
# ---------------------------------------------------------------------------

@dataclass
class CharacterData:
    """Raw character data extracted from the database."""
    character_id: int = 0
    session_id: int = 0
    name: str = ""
    level: int = 1
    char_type: str = "pc"

    # category -> key -> value (all strings from DB)
    attributes: dict[str, dict[str, str]] = field(default_factory=dict)

    # Abilities on the character (feats, powers, etc.)
    abilities: list[dict[str, str]] = field(default_factory=list)

    # Equipped items
    items: list[dict[str, Any]] = field(default_factory=list)


def load_character_data(db, character_id: int) -> CharacterData:
    """Load character data from the database."""
    row = db.execute(
        "SELECT id, session_id, name, level, type FROM characters WHERE id = ?",
        (character_id,),
    ).fetchone()
    if row is None:
        from _db import LoreKitError
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
        "SELECT category, key, value FROM character_attributes "
        "WHERE character_id = ? ORDER BY category, key",
        (character_id,),
    ):
        char.attributes.setdefault(cat, {})[key] = val

    # Load abilities
    for name, desc, category, uses in db.execute(
        "SELECT name, description, category, uses FROM character_abilities "
        "WHERE character_id = ?",
        (character_id,),
    ):
        char.abilities.append({"name": name, "description": desc, "category": category, "uses": uses})

    # Load equipped items
    for name, desc, qty, equipped in db.execute(
        "SELECT name, description, quantity, equipped FROM character_inventory "
        "WHERE character_id = ? AND equipped = 1",
        (character_id,),
    ):
        char.items.append({"name": name, "description": desc, "quantity": qty})

    return char


# ---------------------------------------------------------------------------
# Recalculation engine
# ---------------------------------------------------------------------------

@dataclass
class CalcResult:
    """Result of a rules recalculation."""
    derived: dict[str, Any] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)  # stat -> (old, new)


def _try_parse_number(val: str) -> int | float | str:
    """Try to parse a string as a number, return original if not numeric."""
    try:
        return float(val) if "." in val else int(val)
    except ValueError:
        return val


def _build_context(
    pack: SystemPack,
    char: CharacterData,
    db=None,
) -> FormulaContext:
    """Build a FormulaContext from a system pack and character data.

    When db is provided, loads active combat_state modifiers and resolves
    stacking for all bonus_* variables. Without db, falls back to simple
    override (backward compatible with pure-mode tests).
    """
    ctx = FormulaContext()
    ctx.tables = dict(pack.tables)

    # Base values
    ctx.values["level"] = char.level

    # Apply system pack defaults
    for key, val in pack.defaults.items():
        ctx.values[key] = val

    # Load all character attributes as flat variables, collecting
    # bonus_* entries as modifier entries for stacking resolution
    bonus_modifiers: list[ModifierEntry] = []
    for cat, attrs in char.attributes.items():
        for key, val in attrs.items():
            parsed = _try_parse_number(val)
            ctx.values[f"{cat}.{key}"] = parsed
            ctx.values[key] = parsed

            # Collect bonus_* attributes as modifiers (source = category)
            if key.startswith("bonus_") and isinstance(parsed, (int, float)):
                bonus_modifiers.append(
                    ModifierEntry(target_stat=key, value=parsed, source=cat)
                )

    # Load combat_state modifiers when db is available
    if db is not None:
        combat_mods = _load_combat_modifiers(db, char.character_id)
        bonus_modifiers.extend(combat_mods)

    # Resolve stacking if we have modifiers and a stacking policy
    if bonus_modifiers and pack.stacking:
        policy = load_stacking_policy(pack.stacking)
        resolved = resolve_stacking(bonus_modifiers, policy)
        for stat, net_value in resolved.items():
            ctx.values[stat] = net_value
    elif db is not None and bonus_modifiers:
        # No stacking policy declared but combat_state rows exist —
        # sum combat modifiers on top of existing values (rule="all")
        for m in _load_combat_modifiers(db, char.character_id):
            ctx.values[m.target_stat] = ctx.values.get(m.target_stat, 0) + m.value

    return ctx


def _load_combat_modifiers(db, character_id: int) -> list[ModifierEntry]:
    """Load active combat_state rows as ModifierEntry items."""
    rows = db.execute(
        "SELECT target_stat, value, bonus_type, source FROM combat_state "
        "WHERE character_id = ?",
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


def recalculate(pack: SystemPack, char: CharacterData, db=None) -> CalcResult:
    """Recalculate all derived stats for a character.

    Returns a CalcResult with computed values, constraint violations,
    and a diff of what changed.
    """
    result = CalcResult()

    if not pack.derived:
        return result

    # Build evaluation context
    ctx = _build_context(pack, char, db=db)

    # Load previous derived values for diffing
    old_derived: dict[str, str] = {}
    if "derived" in char.attributes:
        old_derived = dict(char.attributes["derived"])

    # Topological sort of derived stats
    dep_graph = _build_dep_graph(pack.derived)
    eval_order = _topo_sort(dep_graph)

    # Evaluate each derived stat in order
    for stat in eval_order:
        formula = pack.derived[stat]
        try:
            value = calc(formula, ctx)
            # Ensure numeric results are clean ints where possible
            if isinstance(value, float) and value == int(value):
                value = int(value)
            result.derived[stat] = value
            # Feed back into context for downstream stats
            ctx.values[stat] = value
        except FormulaError as e:
            result.derived[stat] = f"ERROR: {e}"

    # Validate constraints
    for name, expr in pack.constraints.items():
        try:
            passed = calc(expr, ctx)
            if not passed:
                result.violations.append(f"{name}: {expr}")
        except FormulaError:
            result.violations.append(f"{name}: could not evaluate ({expr})")

    # Compute diff
    for stat, value in result.derived.items():
        old_val = old_derived.get(stat)
        if old_val is None:
            result.changes[stat] = (None, value)
        elif str(value) != old_val:
            result.changes[stat] = (old_val, value)

    return result


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
# Top-level: full recalc from DB
# ---------------------------------------------------------------------------

def _run_build(db, character_id: int, pack_dir: str,
               char: CharacterData) -> None:
    """Run the build engine and write results to the DB.

    Build attributes are written under category='build'. This must
    run before recalculate() so derived formulas can reference them.
    """
    from build_engine import process_build

    build_result = process_build(
        pack_dir, char.attributes, char.abilities, char.level,
        char_items=char.items,
    )

    if not build_result.attributes and not build_result.costs:
        return

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


def rules_check(db, character_id: int, check: str, dc: int, pack_dir: str) -> str:
    """Read a pre-computed derived stat and roll against a DC."""
    from rolldice import roll_expr

    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    # Read from derived attributes
    derived = char.attributes.get("derived", {})
    bonus_str = derived.get(check)
    if bonus_str is None:
        from _db import LoreKitError
        raise LoreKitError(
            f"Stat '{check}' not found in derived attributes for {char.name}. "
            f"Run rules_calc first."
        )

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


def rules_calc(db, character_id: int, pack_dir: str) -> str:
    """Full recalculation pipeline: build → compute → write back → report."""
    pack = load_system_pack(pack_dir)
    char = load_character_data(db, character_id)

    # Run build engine first — writes build attributes to DB and merges
    # them into char so derived formulas can reference them
    _run_build(db, character_id, pack_dir, char)

    result = recalculate(pack, char, db=db)

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

    if result.violations:
        lines.append("VIOLATIONS:")
        for v in result.violations:
            lines.append(f"  ⚠ {v}")

    return "\n".join(lines)
