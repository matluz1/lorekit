"""Tests for the Crunch formula evaluator."""

import math
import pytest

from rules_formulas import (
    FormulaContext,
    FormulaError,
    calc,
    extract_deps,
    parse,
)


# ---------------------------------------------------------------------------
# Basic arithmetic
# ---------------------------------------------------------------------------

class TestArithmetic:
    def test_integer(self):
        assert calc("42") == 42

    def test_float(self):
        assert calc("3.14") == 3.14

    def test_addition(self):
        assert calc("2 + 3") == 5

    def test_subtraction(self):
        assert calc("10 - 4") == 6

    def test_multiplication(self):
        assert calc("3 * 7") == 21

    def test_division(self):
        assert calc("10 / 4") == 2.5

    def test_precedence(self):
        assert calc("2 + 3 * 4") == 14

    def test_parentheses(self):
        assert calc("(2 + 3) * 4") == 20

    def test_nested_parens(self):
        assert calc("((1 + 2) * (3 + 4))") == 21

    def test_unary_negative(self):
        assert calc("-5") == -5

    def test_unary_in_expr(self):
        assert calc("10 + -3") == 7

    def test_complex_expr(self):
        # floor((score - 10) / 2) with score=18
        ctx = FormulaContext(values={"score": 18})
        assert calc("floor((score - 10) / 2)", ctx) == 4

    def test_division_by_zero(self):
        with pytest.raises(FormulaError, match="Division by zero"):
            calc("1 / 0")


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

class TestVariables:
    def test_simple_var(self):
        ctx = FormulaContext(values={"bab": 10})
        assert calc("bab", ctx) == 10

    def test_dotted_var(self):
        ctx = FormulaContext(values={"armor.bonus": 5})
        assert calc("armor.bonus", ctx) == 5

    def test_unknown_var(self):
        with pytest.raises(FormulaError, match="Unknown variable"):
            calc("nonexistent")

    def test_var_in_expr(self):
        ctx = FormulaContext(values={"bab": 10, "level": 5})
        assert calc("bab + level", ctx) == 15


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------

class TestComparisons:
    def test_equal(self):
        assert calc("5 == 5") is True

    def test_not_equal(self):
        assert calc("5 != 3") is True

    def test_less_than(self):
        assert calc("3 < 5") is True

    def test_greater_than(self):
        assert calc("5 > 3") is True

    def test_less_equal(self):
        assert calc("5 <= 5") is True

    def test_greater_equal(self):
        assert calc("3 >= 5") is False

    def test_comparison_with_vars(self):
        ctx = FormulaContext(values={"attack": 10, "cap": 20})
        assert calc("attack <= cap", ctx) is True


# ---------------------------------------------------------------------------
# Built-in functions
# ---------------------------------------------------------------------------

class TestFunctions:
    def test_floor(self):
        assert calc("floor(7 / 2)") == 3

    def test_ceil(self):
        assert calc("ceil(7 / 2)") == 4

    def test_abs(self):
        assert calc("abs(-5)") == 5

    def test_max(self):
        assert calc("max(3, 7)") == 7

    def test_min(self):
        assert calc("min(3, 7)") == 3

    def test_max_multiple(self):
        assert calc("max(1, 5, 3)") == 5

    def test_sum_values(self):
        assert calc("sum(2, 3, 5)") == 10

    def test_per(self):
        # per(23, 5) -> ceil(23 / 5) = 5
        assert calc("per(23, 5)") == 5

    def test_per_exact(self):
        assert calc("per(20, 5)") == 4

    def test_per_zero(self):
        with pytest.raises(FormulaError, match="step cannot be zero"):
            calc("per(10, 0)")

    def test_ratio(self):
        # ratio(10, 0.5) -> ceil(10 * 0.5) = 5
        assert calc("ratio(10, 0.5)") == 5

    def test_ratio_fractional(self):
        # ratio(7, 0.3) -> ceil(7 * 0.3) = ceil(2.1) = 3
        assert calc("ratio(7, 0.3)") == 3


# ---------------------------------------------------------------------------
# if()
# ---------------------------------------------------------------------------

class TestIf:
    def test_true_branch(self):
        assert calc("if(true, 10, 20)") == 10

    def test_false_branch(self):
        assert calc("if(false, 10, 20)") == 20

    def test_comparison_condition(self):
        ctx = FormulaContext(values={"removable": True, "base": 100})
        assert calc("if(removable, base - 10, base)", ctx) == 90

    def test_false_var_condition(self):
        ctx = FormulaContext(values={"removable": False, "base": 100})
        assert calc("if(removable, base - 10, base)", ctx) == 100


# ---------------------------------------------------------------------------
# table()
# ---------------------------------------------------------------------------

class TestTable:
    def test_basic_lookup(self):
        ctx = FormulaContext(
            tables={"bab_full": [1, 2, 3, 4, 5]},
            values={"level": 3},
        )
        assert calc("table(bab_full, level)", ctx) == 3

    def test_first_entry(self):
        ctx = FormulaContext(
            tables={"bab_full": [1, 2, 3]},
            values={"level": 1},
        )
        assert calc("table(bab_full, level)", ctx) == 1

    def test_unknown_table(self):
        ctx = FormulaContext(values={"level": 1})
        with pytest.raises(FormulaError, match="Unknown table"):
            calc("table(missing, level)", ctx)

    def test_out_of_range(self):
        ctx = FormulaContext(
            tables={"t": [1, 2, 3]},
            values={"level": 5},
        )
        with pytest.raises(FormulaError, match="out of range"):
            calc("table(t, level)", ctx)


# ---------------------------------------------------------------------------
# Dependency extraction
# ---------------------------------------------------------------------------

class TestDeps:
    def test_simple_var(self):
        ast = parse("bab + level")
        assert extract_deps(ast) == {"bab", "level"}

    def test_table_dep(self):
        ast = parse("table(bab_full, level)")
        assert extract_deps(ast) == {"level"}

    def test_complex_formula(self):
        ast = parse("base_attack + str_mod + bonus_melee_attack")
        assert extract_deps(ast) == {"base_attack", "str_mod", "bonus_melee_attack"}

    def test_nested(self):
        ast = parse("floor((score - 10) / 2)")
        assert extract_deps(ast) == {"score"}

    def test_if_deps(self):
        ast = parse("if(removable, base - 10, base)")
        assert extract_deps(ast) == {"removable", "base"}


# ---------------------------------------------------------------------------
# Composite formulas (from the spec)
# ---------------------------------------------------------------------------

class TestSpecFormulas:
    def test_d20_ability_mod(self):
        ctx = FormulaContext(values={"score": 16})
        assert calc("floor((score - 10) / 2)", ctx) == 3

    def test_d20_melee_attack(self):
        ctx = FormulaContext(
            values={"bab": 10, "str_mod": 4, "bonus_melee_attack": 1},
        )
        # bab(10) + str_mod(4) + bonus_melee_attack(1) = 15
        assert calc("bab + str_mod + bonus_melee_attack", ctx) == 15

    def test_d20_defense(self):
        ctx = FormulaContext(
            values={"armor_bonus": 5, "shield_bonus": 2, "dex_mod": 2, "size_mod": 0, "bonus_defense": 0},
        )
        # 10 + 5 + 2 + 2 + 0 + 0 = 19
        assert calc("10 + armor_bonus + shield_bonus + dex_mod + size_mod + bonus_defense", ctx) == 19

    def test_pipeline_base(self):
        ctx = FormulaContext(values={"base_cost_per_rank": 2, "ranks": 10})
        assert calc("base_cost_per_rank * ranks", ctx) == 20

    def test_pipeline_per_rank_mods(self):
        ctx = FormulaContext(
            values={"base_cost_per_rank": 1, "ranks": 10, "sum_extras": 1, "sum_flaws": -1},
        )
        # (1 + 1 + -1) * 10 = 10, max(1*10, 10) = 10
        result = calc(
            "max(1 * ranks, (base_cost_per_rank + sum_extras + sum_flaws) * ranks)",
            ctx,
        )
        assert result == 10

    def test_pipeline_floor(self):
        ctx = FormulaContext(
            values={"base_cost_per_rank": 1, "ranks": 5, "sum_extras": 0, "sum_flaws": -2},
        )
        # (1 + 0 + -2) * 5 = -5, max(1*5, -5) = 5 (floor at 1/rank)
        result = calc(
            "max(1 * ranks, (base_cost_per_rank + sum_extras + sum_flaws) * ranks)",
            ctx,
        )
        assert result == 5

    def test_pipeline_flat_mods(self):
        ctx = FormulaContext(
            values={"base": 10, "flat_mods": -1},
        )
        # max(1, 10 + -1) = max(1, 9) = 9
        assert calc("max(1, base + flat_mods)", ctx) == 9

    def test_pipeline_removable(self):
        ctx = FormulaContext(
            values={"removable": True, "base": 20, "removable_reduction": 1},
        )
        # if(true, 20 - per(20, 5) * 1, 20) = 20 - 4 * 1 = 16
        assert calc("if(removable, base - per(base, 5) * removable_reduction, base)", ctx) == 16

    def test_pipeline_not_removable(self):
        ctx = FormulaContext(
            values={"removable": False, "base": 20, "removable_reduction": 0},
        )
        assert calc("if(removable, base - per(base, 5) * removable_reduction, base)", ctx) == 20
