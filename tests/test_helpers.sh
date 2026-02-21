#!/usr/bin/env bash
# test_helpers.sh -- Lightweight test framework for LoreKit.
#
# Provides isolation (temp DB per test), assertions, and setup helpers.
# Source this file from each test_*.sh file.

set -euo pipefail

# ── Paths ──────────────────────────────────────────────────────────────
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$TESTS_DIR/.." && pwd)"
SCRIPTS_DIR="$PROJECT_DIR/scripts"

# ── Counters ───────────────────────────────────────────────────────────
_PASSED=0
_FAILED=0
_CURRENT_TEST=""

# ── Colors (disabled if not a terminal) ────────────────────────────────
if [[ -t 1 ]]; then
    _GREEN='\033[0;32m'
    _RED='\033[0;31m'
    _YELLOW='\033[0;33m'
    _RESET='\033[0m'
else
    _GREEN='' _RED='' _YELLOW='' _RESET=''
fi

# ── Setup / Teardown ──────────────────────────────────────────────────
setup() {
    TEST_TMP="$(mktemp -d)"
    export LOREKIT_DB_DIR="$TEST_TMP"
    export LOREKIT_DB="$TEST_TMP/game.db"
    # Initialize a fresh database
    bash "$SCRIPTS_DIR/init_db.sh" > /dev/null 2>&1
}

teardown() {
    rm -rf "$TEST_TMP"
    unset LOREKIT_DB LOREKIT_DB_DIR
}

# ── Test runner ────────────────────────────────────────────────────────
run_test() {
    local name="$1"
    local func="$2"
    _CURRENT_TEST="$name"
    setup
    local _test_failed=0
    # Run the test function; capture failure
    if ! "$func"; then
        _test_failed=1
    fi
    teardown
    if [[ $_test_failed -eq 0 ]]; then
        _PASSED=$(( _PASSED + 1 ))
        printf "  ${_GREEN}PASS${_RESET}  %s\n" "$name"
    fi
}

_fail() {
    local msg="$1"
    _FAILED=$(( _FAILED + 1 ))
    printf "  ${_RED}FAIL${_RESET}  %s\n" "$_CURRENT_TEST"
    printf "        %s\n" "$msg"
    return 1
}

# ── Assertions ─────────────────────────────────────────────────────────
assert_equals() {
    local expected="$1" actual="$2"
    local label="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        _fail "${label:+$label: }expected '$expected', got '$actual'"
    fi
}

assert_contains() {
    local haystack="$1" needle="$2"
    local label="${3:-}"
    if [[ "$haystack" != *"$needle"* ]]; then
        _fail "${label:+$label: }output does not contain '$needle'"
    fi
}

assert_not_contains() {
    local haystack="$1" needle="$2"
    local label="${3:-}"
    if [[ "$haystack" == *"$needle"* ]]; then
        _fail "${label:+$label: }output should not contain '$needle'"
    fi
}

assert_match() {
    local text="$1" pattern="$2"
    local label="${3:-}"
    if [[ ! "$text" =~ $pattern ]]; then
        _fail "${label:+$label: }output does not match pattern '$pattern'"
    fi
}

assert_exit_code() {
    local expected="$1" actual="$2"
    local label="${3:-}"
    if [[ "$expected" != "$actual" ]]; then
        _fail "${label:+$label: }expected exit code $expected, got $actual"
    fi
}

assert_line_count() {
    local expected="$1" text="$2"
    local label="${3:-}"
    local actual
    if [[ -z "$text" ]]; then
        actual=0
    else
        actual=$(echo "$text" | wc -l | tr -d ' ')
    fi
    if [[ "$expected" != "$actual" ]]; then
        _fail "${label:+$label: }expected $expected lines, got $actual"
    fi
}

# ── Setup helpers (return IDs) ─────────────────────────────────────────
create_test_session() {
    local name="${1:-Test Campaign}"
    local setting="${2:-Fantasy World}"
    local system="${3:-d20 Fantasy}"
    local output
    output=$(bash "$SCRIPTS_DIR/session.sh" create --name "$name" --setting "$setting" --system "$system")
    echo "$output" | sed 's/SESSION_CREATED: //'
}

create_test_character() {
    local session_id="$1"
    local name="${2:-Test Hero}"
    local type="${3:-pc}"
    local region="${4:-}"
    local args=(create --session "$session_id" --name "$name" --type "$type")
    if [[ -n "$region" ]]; then
        args+=(--region "$region")
    fi
    local output
    output=$(bash "$SCRIPTS_DIR/character.sh" "${args[@]}")
    echo "$output" | sed 's/CHARACTER_CREATED: //'
}

create_test_region() {
    local session_id="$1"
    local name="${2:-Test Region}"
    local desc="${3:-A test region}"
    local output
    output=$(bash "$SCRIPTS_DIR/region.sh" create "$session_id" --name "$name" --desc "$desc")
    echo "$output" | sed 's/REGION_CREATED: //'
}

# ── Summary ────────────────────────────────────────────────────────────
print_summary() {
    local total=$(( _PASSED + _FAILED ))
    echo ""
    if [[ $_FAILED -eq 0 ]]; then
        printf "${_GREEN}All %d tests passed.${_RESET}\n" "$total"
    else
        printf "${_RED}%d of %d tests failed.${_RESET}\n" "$_FAILED" "$total"
    fi
    return $_FAILED
}

get_passed() { echo "$_PASSED"; }
get_failed() { echo "$_FAILED"; }
