#!/usr/bin/env bash
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TESTS_DIR/test_helpers.sh"

SESSION="$SCRIPTS_DIR/session.sh"

# ── Happy Path ─────────────────────────────────────────────────────────

test_create_session() {
    local output
    output=$(bash "$SESSION" create --name "Quest" --setting "Fantasy" --system "d20 Fantasy")
    assert_match "$output" "SESSION_CREATED: [0-9]+" "create returns ID"
}

test_view_session() {
    local sid
    sid=$(create_test_session "My Campaign" "Dark World" "PF2e")
    local output
    output=$(bash "$SESSION" view "$sid")
    assert_contains "$output" "NAME: My Campaign"
    assert_contains "$output" "SETTING: Dark World"
    assert_contains "$output" "SYSTEM: PF2e"
    assert_contains "$output" "STATUS: active"
}

test_list_sessions() {
    create_test_session "Camp A" > /dev/null
    create_test_session "Camp B" > /dev/null
    local output
    output=$(bash "$SESSION" list)
    assert_contains "$output" "Camp A"
    assert_contains "$output" "Camp B"
}

test_list_filter_status() {
    local s1 s2
    s1=$(create_test_session "Active Camp")
    s2=$(create_test_session "Done Camp")
    bash "$SESSION" update "$s2" --status finished > /dev/null
    local output
    output=$(bash "$SESSION" list --status active)
    assert_contains "$output" "Active Camp"
    assert_not_contains "$output" "Done Camp"
}

test_update_status() {
    local sid
    sid=$(create_test_session)
    bash "$SESSION" update "$sid" --status finished > /dev/null
    local output
    output=$(bash "$SESSION" view "$sid")
    assert_contains "$output" "STATUS: finished"
}

test_meta_set_and_get() {
    local sid
    sid=$(create_test_session)
    bash "$SESSION" meta-set "$sid" --key "difficulty" --value "hard" > /dev/null
    local output
    output=$(bash "$SESSION" meta-get "$sid" --key "difficulty")
    assert_contains "$output" "difficulty: hard"
}

test_meta_overwrite() {
    local sid
    sid=$(create_test_session)
    bash "$SESSION" meta-set "$sid" --key "level" --value "5" > /dev/null
    bash "$SESSION" meta-set "$sid" --key "level" --value "10" > /dev/null
    local output
    output=$(bash "$SESSION" meta-get "$sid" --key "level")
    assert_contains "$output" "level: 10"
}

test_meta_get_all() {
    local sid
    sid=$(create_test_session)
    bash "$SESSION" meta-set "$sid" --key "a" --value "1" > /dev/null
    bash "$SESSION" meta-set "$sid" --key "b" --value "2" > /dev/null
    local output
    output=$(bash "$SESSION" meta-get "$sid")
    assert_contains "$output" "a"
    assert_contains "$output" "b"
}

# ── Error Cases ────────────────────────────────────────────────────────

test_no_action_fails() {
    local exit_code=0
    bash "$SESSION" 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_unknown_action_fails() {
    local exit_code=0
    local output
    output=$(bash "$SESSION" foobar 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
    assert_contains "$output" "ERROR"
}

test_create_missing_name_fails() {
    local exit_code=0
    local output
    output=$(bash "$SESSION" create --setting "X" --system "Y" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_create_missing_setting_fails() {
    local exit_code=0
    local output
    output=$(bash "$SESSION" create --name "X" --system "Y" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_create_missing_system_fails() {
    local exit_code=0
    local output
    output=$(bash "$SESSION" create --name "X" --setting "Y" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_view_missing_id_fails() {
    local exit_code=0
    bash "$SESSION" view 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_view_nonexistent_fails() {
    local exit_code=0
    local output
    output=$(bash "$SESSION" view 9999 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
    assert_contains "$output" "not found"
}

# ── Edge Cases ─────────────────────────────────────────────────────────

test_special_characters_in_name() {
    local sid
    sid=$(create_test_session "O'Brien's Quest" "Land of \"Quotes\"" "d20 Fantasy")
    local output
    output=$(bash "$SESSION" view "$sid")
    assert_contains "$output" "O'Brien's Quest"
}

# ── Run ────────────────────────────────────────────────────────────────
run_test "create session"                  test_create_session
run_test "view session"                    test_view_session
run_test "list sessions"                   test_list_sessions
run_test "list filter by status"           test_list_filter_status
run_test "update status"                   test_update_status
run_test "meta set and get"                test_meta_set_and_get
run_test "meta overwrite"                  test_meta_overwrite
run_test "meta get all keys"               test_meta_get_all
run_test "no action fails"                 test_no_action_fails
run_test "unknown action fails"            test_unknown_action_fails
run_test "create missing --name fails"     test_create_missing_name_fails
run_test "create missing --setting fails"  test_create_missing_setting_fails
run_test "create missing --system fails"   test_create_missing_system_fails
run_test "view missing id fails"           test_view_missing_id_fails
run_test "view nonexistent session fails"  test_view_nonexistent_fails
run_test "special characters in name"      test_special_characters_in_name

echo "PASSED: $(get_passed)"
echo "FAILED: $(get_failed)"
