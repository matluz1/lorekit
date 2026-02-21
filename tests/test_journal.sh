#!/usr/bin/env bash
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TESTS_DIR/test_helpers.sh"

JOURNAL="$SCRIPTS_DIR/journal.sh"

# ── Happy Path ─────────────────────────────────────────────────────────

test_add_entry() {
    local sid
    sid=$(create_test_session)
    local output
    output=$(bash "$JOURNAL" add "$sid" --type event --content "The party entered the dungeon")
    assert_match "$output" "JOURNAL_ADDED: [0-9]+"
}

test_list_entries() {
    local sid
    sid=$(create_test_session)
    bash "$JOURNAL" add "$sid" --type event --content "Entered dungeon" > /dev/null
    bash "$JOURNAL" add "$sid" --type combat --content "Fought goblins" > /dev/null
    local output
    output=$(bash "$JOURNAL" list "$sid")
    assert_contains "$output" "Entered dungeon"
    assert_contains "$output" "Fought goblins"
}

test_list_filter_by_type() {
    local sid
    sid=$(create_test_session)
    bash "$JOURNAL" add "$sid" --type event --content "Event entry" > /dev/null
    bash "$JOURNAL" add "$sid" --type combat --content "Combat entry" > /dev/null
    local output
    output=$(bash "$JOURNAL" list "$sid" --type combat)
    assert_contains "$output" "Combat entry"
    assert_not_contains "$output" "Event entry"
}

test_list_last_n() {
    local sid
    sid=$(create_test_session)
    bash "$JOURNAL" add "$sid" --type note --content "First note" > /dev/null
    bash "$JOURNAL" add "$sid" --type note --content "Second note" > /dev/null
    bash "$JOURNAL" add "$sid" --type note --content "Third note" > /dev/null
    local output
    output=$(bash "$JOURNAL" list "$sid" --last 1)
    assert_contains "$output" "Third note"
    assert_not_contains "$output" "First note"
}

test_search_entries() {
    local sid
    sid=$(create_test_session)
    bash "$JOURNAL" add "$sid" --type discovery --content "Found a magical artifact" > /dev/null
    bash "$JOURNAL" add "$sid" --type event --content "Talked to the king" > /dev/null
    local output
    output=$(bash "$JOURNAL" search "$sid" --query "artifact")
    assert_contains "$output" "magical artifact"
    assert_not_contains "$output" "king"
}

test_search_case_insensitive() {
    local sid
    sid=$(create_test_session)
    bash "$JOURNAL" add "$sid" --type event --content "The DRAGON attacked" > /dev/null
    local output
    output=$(bash "$JOURNAL" search "$sid" --query "dragon")
    assert_contains "$output" "DRAGON"
}

# ── Error Cases ────────────────────────────────────────────────────────

test_no_action_fails() {
    local exit_code=0
    bash "$JOURNAL" 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_add_missing_type_fails() {
    local sid
    sid=$(create_test_session)
    local exit_code=0
    local output
    output=$(bash "$JOURNAL" add "$sid" --content "X" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_add_missing_content_fails() {
    local sid
    sid=$(create_test_session)
    local exit_code=0
    local output
    output=$(bash "$JOURNAL" add "$sid" --type event 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

# ── Edge Cases ─────────────────────────────────────────────────────────

test_quotes_in_content() {
    local sid
    sid=$(create_test_session)
    bash "$JOURNAL" add "$sid" --type npc --content "The innkeeper said 'welcome'" > /dev/null
    local output
    output=$(bash "$JOURNAL" search "$sid" --query "innkeeper")
    assert_contains "$output" "innkeeper"
}

test_multiple_types() {
    local sid
    sid=$(create_test_session)
    for t in event combat discovery npc decision note; do
        bash "$JOURNAL" add "$sid" --type "$t" --content "Entry of type $t" > /dev/null
    done
    local output
    output=$(bash "$JOURNAL" list "$sid")
    for t in event combat discovery npc decision note; do
        assert_contains "$output" "$t"
    done
}

test_list_last_with_type_filter() {
    local sid
    sid=$(create_test_session)
    bash "$JOURNAL" add "$sid" --type combat --content "Combat 1" > /dev/null
    bash "$JOURNAL" add "$sid" --type event --content "Event 1" > /dev/null
    bash "$JOURNAL" add "$sid" --type combat --content "Combat 2" > /dev/null
    local output
    output=$(bash "$JOURNAL" list "$sid" --type combat --last 1)
    assert_contains "$output" "Combat 2"
    assert_not_contains "$output" "Combat 1"
}

# ── Run ────────────────────────────────────────────────────────────────
run_test "add journal entry"               test_add_entry
run_test "list journal entries"            test_list_entries
run_test "list filter by type"             test_list_filter_by_type
run_test "list --last N"                   test_list_last_n
run_test "search entries"                  test_search_entries
run_test "search case insensitive"         test_search_case_insensitive
run_test "no action fails"                 test_no_action_fails
run_test "add missing --type fails"        test_add_missing_type_fails
run_test "add missing --content fails"     test_add_missing_content_fails
run_test "quotes in content"               test_quotes_in_content
run_test "multiple entry types"            test_multiple_types
run_test "list --last with --type filter"  test_list_last_with_type_filter

echo "PASSED: $(get_passed)"
echo "FAILED: $(get_failed)"
