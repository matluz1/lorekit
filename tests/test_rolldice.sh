#!/usr/bin/env bash
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TESTS_DIR/test_helpers.sh"

ROLL="$SCRIPTS_DIR/rolldice.sh"

# ── Happy Path ─────────────────────────────────────────────────────────

test_d20_basic() {
    local output
    output=$(bash "$ROLL" d20)
    assert_contains "$output" "ROLLS:"    "has ROLLS"
    assert_contains "$output" "KEPT:"     "has KEPT"
    assert_contains "$output" "MODIFIER:" "has MODIFIER"
    assert_contains "$output" "TOTAL:"    "has TOTAL"
}

test_d20_range() {
    # Roll 100 times; all totals should be 1..20
    for _ in $(seq 1 100); do
        local total
        total=$(bash "$ROLL" d20 | grep '^TOTAL:' | awk '{print $2}')
        if [[ "$total" -lt 1 || "$total" -gt 20 ]]; then
            _fail "d20 total $total out of range 1-20"; return 1
        fi
    done
}

test_3d6_shows_three_rolls() {
    local rolls_line
    rolls_line=$(bash "$ROLL" 3d6 | grep '^ROLLS:')
    # Should have exactly 2 commas (3 values)
    local commas="${rolls_line//[^,]/}"
    assert_equals "2" "${#commas}" "3d6 should produce 3 rolls"
}

test_modifier_plus() {
    local output total rolls_kept
    output=$(bash "$ROLL" 1d1+5 2>&1) || true
    # 1d1 always rolls 1, +5 = 6
    # d1 has <2 sides, should error actually. Use d2 trick instead.
    # Actually d1 fails validation (sides < 2). Let's use a different approach.
    # We'll just check the MODIFIER line contains +5
    output=$(bash "$ROLL" 1d4+5)
    assert_contains "$output" "MODIFIER: +5" "modifier shown"
}

test_modifier_minus() {
    local output
    output=$(bash "$ROLL" 1d4-2)
    assert_contains "$output" "MODIFIER: -2" "negative modifier shown"
}

test_zero_modifier() {
    local output
    output=$(bash "$ROLL" d20)
    assert_contains "$output" "MODIFIER: +0" "zero modifier"
}

test_keep_highest() {
    local output kept_line
    output=$(bash "$ROLL" 4d6kh3)
    kept_line=$(echo "$output" | grep '^KEPT:')
    # Should have exactly 2 commas (3 kept values)
    local commas="${kept_line//[^,]/}"
    assert_equals "2" "${#commas}" "4d6kh3 should keep 3"
}

# ── Error Cases ────────────────────────────────────────────────────────

test_no_args_fails() {
    local exit_code=0
    bash "$ROLL" 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code" "no args"
}

test_invalid_expression_fails() {
    local exit_code=0
    local output
    output=$(bash "$ROLL" "abc" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code" "invalid expr"
    assert_contains "$output" "ERROR" "error message"
}

test_zero_sides_fails() {
    local exit_code=0
    local output
    output=$(bash "$ROLL" "1d0" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code" "0 sides"
}

test_one_side_fails() {
    local exit_code=0
    local output
    output=$(bash "$ROLL" "1d1" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code" "1 side"
}

test_keep_more_than_rolled_fails() {
    local exit_code=0
    local output
    output=$(bash "$ROLL" "2d6kh5" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code" "keep > rolled"
}

test_two_args_fails() {
    local exit_code=0
    bash "$ROLL" d20 d6 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code" "two args"
}

# ── Edge Cases ─────────────────────────────────────────────────────────

test_d100_range() {
    for _ in $(seq 1 50); do
        local total
        total=$(bash "$ROLL" d100 | grep '^TOTAL:' | awk '{print $2}')
        if [[ "$total" -lt 1 || "$total" -gt 100 ]]; then
            _fail "d100 total $total out of range"; return 1
        fi
    done
}

test_case_insensitive() {
    local output
    output=$(bash "$ROLL" D20)
    assert_contains "$output" "TOTAL:" "uppercase D20 works"
}

test_keep_one() {
    local output kept_line
    output=$(bash "$ROLL" 3d6kh1)
    kept_line=$(echo "$output" | grep '^KEPT:')
    # No commas = 1 value
    local commas="${kept_line//[^,]/}"
    assert_equals "0" "${#commas}" "kh1 keeps 1"
}

# ── Run ────────────────────────────────────────────────────────────────
run_test "d20 basic output"                test_d20_basic
run_test "d20 results in range 1-20"       test_d20_range
run_test "3d6 shows three rolls"           test_3d6_shows_three_rolls
run_test "positive modifier"               test_modifier_plus
run_test "negative modifier"               test_modifier_minus
run_test "zero modifier"                   test_zero_modifier
run_test "keep highest (4d6kh3)"           test_keep_highest
run_test "no args fails"                   test_no_args_fails
run_test "invalid expression fails"        test_invalid_expression_fails
run_test "zero sides fails"               test_zero_sides_fails
run_test "one side fails"                  test_one_side_fails
run_test "keep more than rolled fails"     test_keep_more_than_rolled_fails
run_test "two args fails"                  test_two_args_fails
run_test "d100 in range"                   test_d100_range
run_test "case insensitive (D20)"          test_case_insensitive
run_test "keep exactly 1 (3d6kh1)"         test_keep_one

echo "PASSED: $(get_passed)"
echo "FAILED: $(get_failed)"
