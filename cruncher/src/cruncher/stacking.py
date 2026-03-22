"""Modifier stacking resolver — domain-agnostic.

Resolves how multiple modifiers to the same variable combine, based on
a declared stacking policy. The resolver knows nothing about RPG systems,
bonus types, or conditions. It groups, selects, and sums numbers based
on configuration.

Policy fields:
  - group_by:  which ModifierEntry field to group on (e.g. "bonus_type",
               "source"), or None for no grouping (sum all).
  - positive:  how to combine positive values within a group:
               "sum" (add them all) or "max" (keep highest).
  - negative:  how to combine negative values within a group:
               "sum" (add them all) or "min" (keep most negative).
  - overrides: per-group-value policy overrides. A dict mapping a group
               value to {"positive": ..., "negative": ...}. "_none"
               matches modifiers where the group field is None.

This is a pure function module with no DB or engine dependencies.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModifierEntry:
    """A single modifier targeting a variable."""

    target_stat: str
    value: float
    bonus_type: str | None = None
    source: str = ""


@dataclass
class StackingPolicy:
    """Parsed stacking policy from a system pack."""

    group_by: str | None = None  # field name to group on, None = no grouping
    positive: str = "sum"  # "sum" or "max"
    negative: str = "sum"  # "sum" or "min"
    overrides: dict[str, dict] = field(default_factory=dict)  # group_value -> {positive/negative}


def load_stacking_policy(stacking_cfg: dict[str, Any]) -> StackingPolicy:
    """Parse a stacking config dict from system.json into a StackingPolicy."""
    if not stacking_cfg:
        return StackingPolicy()
    return StackingPolicy(
        group_by=stacking_cfg.get("group_by"),
        positive=stacking_cfg.get("positive", "sum"),
        negative=stacking_cfg.get("negative", "sum"),
        overrides=stacking_cfg.get("overrides", {}),
    )


# ---------------------------------------------------------------------------
# Stacking resolver
# ---------------------------------------------------------------------------


def resolve_stacking(
    modifiers: list[ModifierEntry],
    policy: StackingPolicy,
) -> dict[str, float]:
    """Resolve stacking and return net value per target_stat.

    Groups modifiers by the field named in policy.group_by, applies
    the combine rule (max/sum for positives, min/sum for negatives)
    within each group, then sums across groups.
    """
    if not modifiers:
        return {}

    if policy.group_by is None:
        return _sum_all(modifiers)

    return _resolve_grouped(modifiers, policy)


def _sum_all(modifiers: list[ModifierEntry]) -> dict[str, float]:
    """No grouping — sum all modifiers per stat."""
    totals: dict[str, float] = defaultdict(float)
    for m in modifiers:
        totals[m.target_stat] += m.value
    return dict(totals)


def _resolve_grouped(
    modifiers: list[ModifierEntry],
    policy: StackingPolicy,
) -> dict[str, float]:
    """Group by a field, apply combine rules per group, sum across groups."""
    # Group by stat, then by group_key
    by_stat: dict[str, dict[str | None, list[float]]] = defaultdict(lambda: defaultdict(list))
    for m in modifiers:
        group_key = getattr(m, policy.group_by, None)
        by_stat[m.target_stat][group_key].append(m.value)

    totals: dict[str, float] = {}
    for stat, groups in by_stat.items():
        total = 0.0
        for group_key, values in groups.items():
            pos = [v for v in values if v > 0]
            neg = [v for v in values if v < 0]

            pos_rule, neg_rule = _rules_for_group(group_key, policy)

            if pos:
                total += sum(pos) if pos_rule == "sum" else max(pos)
            if neg:
                total += sum(neg) if neg_rule == "sum" else min(neg)

        totals[stat] = total

    return totals


def _rules_for_group(
    group_key: str | None,
    policy: StackingPolicy,
) -> tuple[str, str]:
    """Return (positive_rule, negative_rule) for a group value.

    Checks overrides first. "_none" matches group_key=None.
    Falls back to the policy defaults.
    """
    if policy.overrides:
        override_key = "_none" if group_key is None else group_key
        override = policy.overrides.get(override_key)
        if override:
            return (
                override.get("positive", policy.positive),
                override.get("negative", policy.negative),
            )
    return policy.positive, policy.negative


# ---------------------------------------------------------------------------
# Decomposition (for audit tool)
# ---------------------------------------------------------------------------


@dataclass
class DecomposedModifier:
    """A modifier with its stacking resolution status."""

    target_stat: str
    value: float
    bonus_type: str | None
    source: str
    active: bool  # True if this modifier survived stacking


def decompose_modifiers(
    modifiers: list[ModifierEntry],
    policy: StackingPolicy,
    stat: str | None = None,
) -> list[DecomposedModifier]:
    """Return per-modifier breakdown showing which survived stacking.

    If stat is specified, only modifiers for that stat are returned.
    """
    filtered = modifiers if stat is None else [m for m in modifiers if m.target_stat == stat]

    if policy.group_by is None:
        # No grouping — everything is active
        return [DecomposedModifier(m.target_stat, m.value, m.bonus_type, m.source, active=True) for m in filtered]

    active_set = _compute_active_set(filtered, policy)
    return [
        DecomposedModifier(m.target_stat, m.value, m.bonus_type, m.source, active=(i in active_set))
        for i, m in enumerate(filtered)
    ]


def _compute_active_set(
    modifiers: list[ModifierEntry],
    policy: StackingPolicy,
) -> set[int]:
    """Return indices of modifiers that survive stacking."""
    active: set[int] = set()

    # Group by (stat, group_key)
    by_stat: dict[str, dict[str | None, list[tuple[int, float]]]] = defaultdict(lambda: defaultdict(list))
    for i, m in enumerate(modifiers):
        group_key = getattr(m, policy.group_by, None)
        by_stat[m.target_stat][group_key].append((i, m.value))

    for stat, groups in by_stat.items():
        for group_key, entries in groups.items():
            pos_rule, neg_rule = _rules_for_group(group_key, policy)

            pos = [(i, v) for i, v in entries if v > 0]
            neg = [(i, v) for i, v in entries if v < 0]

            if pos:
                if pos_rule == "sum":
                    for i, _ in pos:
                        active.add(i)
                else:  # max
                    best_i = max(pos, key=lambda x: x[1])[0]
                    active.add(best_i)

            if neg:
                if neg_rule == "sum":
                    for i, _ in neg:
                        active.add(i)
                else:  # min
                    worst_i = min(neg, key=lambda x: x[1])[0]
                    active.add(worst_i)

    return active
