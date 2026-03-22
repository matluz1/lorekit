"""Cruncher rules engine — pure computation, domain-agnostic formula evaluator.

Builds a flat variable context from character attributes, evaluates
derived formulas in dependency order, resolves modifier stacking,
and validates constraints.

The engine knows nothing about RPG concepts (classes, feats, abilities,
proficiencies). All domain knowledge lives in the system pack JSON
data files.

This module contains only pure computation functions. Database access,
build orchestration, and write-back logic live in the host application
(e.g. lorekit/rules.py).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from cruncher.formulas import (
    CruncherError,
    FormulaContext,
    calc,
    extract_deps,
    parse,
)
from cruncher.stacking import (
    ModifierEntry,
    load_stacking_policy,
    resolve_stacking,
)
from cruncher.system_pack import (
    SystemPack,
)
from cruncher.types import CharacterData

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
        raise CruncherError(f"Circular dependency detected among: {missing}")

    return result


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
    modifiers: list[ModifierEntry] | None = None,
) -> FormulaContext:
    """Build a FormulaContext from a system pack and character data.

    When modifiers are provided, resolves stacking for all bonus_*
    variables. Without modifiers, falls back to simple override
    (backward compatible with pure-mode tests).
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

            # Collect bonus_* attributes as modifiers (single source so
            # stacking treats all base attributes as one group)
            if key.startswith("bonus_") and isinstance(parsed, (int, float)):
                bonus_modifiers.append(ModifierEntry(target_stat=key, value=parsed, source="_attr"))

    # Extend with externally-provided modifiers (e.g. combat_state rows)
    if modifiers is not None:
        bonus_modifiers.extend(modifiers)

    # Resolve stacking if we have modifiers and a stacking policy
    if bonus_modifiers and pack.stacking:
        policy = load_stacking_policy(pack.stacking)
        resolved = resolve_stacking(bonus_modifiers, policy)
        for stat, net_value in resolved.items():
            ctx.values[stat] = net_value
    elif modifiers is not None and bonus_modifiers:
        # No stacking policy declared but modifiers were provided —
        # sum provided modifiers on top of existing values (rule="all")
        for m in modifiers:
            ctx.values[m.target_stat] = ctx.values.get(m.target_stat, 0) + m.value

    return ctx


def recalculate(
    pack: SystemPack,
    char: CharacterData,
    modifiers: list[ModifierEntry] | None = None,
) -> CalcResult:
    """Recalculate all derived stats for a character.

    Returns a CalcResult with computed values, constraint violations,
    and a diff of what changed.
    """
    result = CalcResult()

    if not pack.derived:
        return result

    # Build evaluation context
    ctx = _build_context(pack, char, modifiers=modifiers)

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
        except CruncherError as e:
            result.derived[stat] = f"ERROR: {e}"

    # Validate constraints
    for name, expr in pack.constraints.items():
        try:
            passed = calc(expr, ctx)
            if not passed:
                result.violations.append(f"{name}: {expr}")
        except CruncherError:
            result.violations.append(f"{name}: could not evaluate ({expr})")

    # Compute diff
    for stat, value in result.derived.items():
        old_val = old_derived.get(stat)
        if old_val is None:
            result.changes[stat] = (None, value)
        elif str(value) != old_val:
            result.changes[stat] = (old_val, value)

    return result
