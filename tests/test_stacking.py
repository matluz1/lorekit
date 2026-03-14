"""Tests for the modifier stacking resolver."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from rules_stacking import (
    DecomposedModifier,
    ModifierEntry,
    StackingPolicy,
    decompose_modifiers,
    load_stacking_policy,
    resolve_stacking,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def M(stat, value, bonus_type=None, source=""):
    """Shorthand for ModifierEntry."""
    return ModifierEntry(stat, value, bonus_type, source)


# Reusable policies
NO_GROUP = StackingPolicy()  # group_by=None → sum all
GROUP_BY_TYPE = StackingPolicy(
    group_by="bonus_type",
    positive="max",
    negative="sum",
    overrides={"untyped": {"positive": "sum"}, "_none": {"positive": "sum"}},
)
GROUP_BY_SOURCE = StackingPolicy(group_by="source", positive="max", negative="min")


# ---------------------------------------------------------------------------
# load_stacking_policy
# ---------------------------------------------------------------------------


class TestLoadStackingPolicy:
    def test_empty_config(self):
        p = load_stacking_policy({})
        assert p.group_by is None
        assert p.positive == "sum"
        assert p.negative == "sum"

    def test_group_by_type_config(self):
        p = load_stacking_policy(
            {
                "group_by": "bonus_type",
                "positive": "max",
                "negative": "sum",
                "overrides": {"untyped": {"positive": "sum"}},
            }
        )
        assert p.group_by == "bonus_type"
        assert p.positive == "max"
        assert p.overrides == {"untyped": {"positive": "sum"}}

    def test_group_by_source_config(self):
        p = load_stacking_policy({"group_by": "source", "positive": "max", "negative": "min"})
        assert p.group_by == "source"
        assert p.negative == "min"


# ---------------------------------------------------------------------------
# No grouping (sum all)
# ---------------------------------------------------------------------------


class TestNoGrouping:
    def test_sums_everything(self):
        mods = [M("bonus_ac", 2), M("bonus_ac", 3), M("bonus_ac", -1)]
        result = resolve_stacking(mods, NO_GROUP)
        assert result["bonus_ac"] == 4

    def test_multiple_stats(self):
        mods = [M("bonus_ac", 2), M("bonus_attack", 1), M("bonus_ac", 1)]
        result = resolve_stacking(mods, NO_GROUP)
        assert result["bonus_ac"] == 3
        assert result["bonus_attack"] == 1

    def test_empty(self):
        result = resolve_stacking([], NO_GROUP)
        assert result == {}


# ---------------------------------------------------------------------------
# Group by bonus_type (positive=max per group, negative=sum)
# ---------------------------------------------------------------------------


class TestGroupByType:
    def test_same_group_takes_highest(self):
        mods = [
            M("bonus_ac", 2, "circumstance", "flanking"),
            M("bonus_ac", 1, "circumstance", "aid"),
        ]
        result = resolve_stacking(mods, GROUP_BY_TYPE)
        assert result["bonus_ac"] == 2  # not 3

    def test_different_groups_stack(self):
        mods = [
            M("bonus_ac", 2, "circumstance", "flanking"),
            M("bonus_ac", 1, "status", "bless"),
            M("bonus_ac", 3, "item", "plate_mail"),
        ]
        result = resolve_stacking(mods, GROUP_BY_TYPE)
        assert result["bonus_ac"] == 6  # 2 + 1 + 3

    def test_negatives_sum_within_group(self):
        mods = [
            M("bonus_ac", -2, "status", "frightened"),
            M("bonus_ac", -1, "status", "sickened"),
        ]
        result = resolve_stacking(mods, GROUP_BY_TYPE)
        assert result["bonus_ac"] == -3  # both sum

    def test_negatives_take_worst_when_configured(self):
        policy = StackingPolicy(group_by="bonus_type", positive="max", negative="min")
        mods = [
            M("bonus_ac", -2, "status", "frightened"),
            M("bonus_ac", -1, "status", "sickened"),
        ]
        result = resolve_stacking(mods, policy)
        assert result["bonus_ac"] == -2  # take most negative

    def test_untyped_sums_via_override(self):
        mods = [
            M("bonus_hp", 5, "untyped", "toughness"),
            M("bonus_hp", 3, "untyped", "ancestry"),
        ]
        result = resolve_stacking(mods, GROUP_BY_TYPE)
        assert result["bonus_hp"] == 8

    def test_untyped_takes_max_without_override(self):
        policy = StackingPolicy(group_by="bonus_type", positive="max", negative="sum")
        mods = [
            M("bonus_hp", 5, "untyped", "toughness"),
            M("bonus_hp", 3, "untyped", "ancestry"),
        ]
        result = resolve_stacking(mods, policy)
        assert result["bonus_hp"] == 5  # no override → max

    def test_mixed_positive_and_negative(self):
        mods = [
            M("bonus_ac", 2, "circumstance", "cover"),
            M("bonus_ac", -2, "circumstance", "off_guard"),
        ]
        result = resolve_stacking(mods, GROUP_BY_TYPE)
        assert result["bonus_ac"] == 0

    def test_none_bonus_type_sums_via_override(self):
        mods = [
            M("bonus_ac", 2, None, "feat_a"),
            M("bonus_ac", 3, None, "feat_b"),
        ]
        result = resolve_stacking(mods, GROUP_BY_TYPE)
        assert result["bonus_ac"] == 5  # _none override → sum


# ---------------------------------------------------------------------------
# Group by source (positive=max per source, negative=min)
# ---------------------------------------------------------------------------


class TestGroupBySource:
    def test_same_source_takes_highest(self):
        mods = [
            M("bonus_ac", 2, source="shield_spell"),
            M("bonus_ac", 4, source="shield_spell"),
        ]
        result = resolve_stacking(mods, GROUP_BY_SOURCE)
        assert result["bonus_ac"] == 4

    def test_different_sources_stack(self):
        mods = [
            M("bonus_ac", 2, source="shield_spell"),
            M("bonus_ac", 3, source="armor"),
        ]
        result = resolve_stacking(mods, GROUP_BY_SOURCE)
        assert result["bonus_ac"] == 5

    def test_same_source_penalty_takes_worst(self):
        mods = [
            M("bonus_attack", -1, source="power_attack"),
            M("bonus_attack", -3, source="power_attack"),
        ]
        result = resolve_stacking(mods, GROUP_BY_SOURCE)
        assert result["bonus_attack"] == -3

    def test_same_source_mixed(self):
        mods = [
            M("bonus_ac", 2, source="spell_x"),
            M("bonus_ac", -1, source="spell_x"),
        ]
        result = resolve_stacking(mods, GROUP_BY_SOURCE)
        assert result["bonus_ac"] == 1  # max(+2) + min(-1)


# ---------------------------------------------------------------------------
# decompose_modifiers
# ---------------------------------------------------------------------------


class TestDecompose:
    def test_no_grouping_everything_active(self):
        mods = [M("bonus_ac", 2), M("bonus_ac", 3)]
        result = decompose_modifiers(mods, NO_GROUP)
        assert all(d.active for d in result)
        assert len(result) == 2

    def test_grouped_shows_suppressed(self):
        mods = [
            M("bonus_ac", 2, "circumstance", "flanking"),
            M("bonus_ac", 1, "circumstance", "aid"),  # suppressed
            M("bonus_ac", 3, "item", "plate"),  # different group
        ]
        result = decompose_modifiers(mods, GROUP_BY_TYPE)
        assert result[0].active is True  # +2 circumstance (highest)
        assert result[1].active is False  # +1 circumstance (suppressed)
        assert result[2].active is True  # +3 item

    def test_filter_by_stat(self):
        mods = [M("bonus_ac", 2), M("bonus_attack", 1)]
        result = decompose_modifiers(mods, NO_GROUP, stat="bonus_ac")
        assert len(result) == 1
        assert result[0].target_stat == "bonus_ac"

    def test_source_grouping_decompose(self):
        mods = [
            M("bonus_ac", 2, source="shield"),
            M("bonus_ac", 4, source="shield"),  # highest from same source
            M("bonus_ac", 1, source="dodge"),
        ]
        result = decompose_modifiers(mods, GROUP_BY_SOURCE)
        assert result[0].active is False  # +2 shield (suppressed by +4)
        assert result[1].active is True  # +4 shield (highest)
        assert result[2].active is True  # +1 dodge (different source)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_zero_value_modifier(self):
        mods = [M("bonus_ac", 0)]
        result = resolve_stacking(mods, NO_GROUP)
        assert result.get("bonus_ac", 0) == 0

    def test_single_modifier(self):
        mods = [M("bonus_ac", 5, "item", "plate")]
        result = resolve_stacking(mods, GROUP_BY_TYPE)
        assert result["bonus_ac"] == 5

    def test_many_groups_same_stat(self):
        mods = [
            M("bonus_ac", 2, "circumstance"),
            M("bonus_ac", 3, "item"),
            M("bonus_ac", 1, "status"),
            M("bonus_ac", -2, "status"),
            M("bonus_ac", -1, "circumstance"),
        ]
        result = resolve_stacking(mods, GROUP_BY_TYPE)
        # Positives: circ=2 (max), item=3 (max), status=1 (max) → 6
        # Negatives: status=-2, circ=-1 → sum = -3
        assert result["bonus_ac"] == 3
