#!/usr/bin/env bash
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TESTS_DIR/test_helpers.sh"

DIALOGUE="$SCRIPTS_DIR/dialogue.sh"

# ── Happy Path ─────────────────────────────────────────────────────────

test_add_dialogue() {
    local sid npc_id
    sid=$(create_test_session)
    npc_id=$(create_test_character "$sid" "Merchant" "npc")
    local output
    output=$(bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Merchant" --content "Welcome to my shop!")
    assert_match "$output" "DIALOGUE_ADDED: [0-9]+"
}

test_list_dialogue() {
    local sid npc_id
    sid=$(create_test_session)
    npc_id=$(create_test_character "$sid" "Guard" "npc")
    bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Guard" --content "Halt!" > /dev/null
    bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Player" --content "I mean no harm" > /dev/null
    local output
    output=$(bash "$DIALOGUE" list "$sid" --npc "$npc_id")
    assert_contains "$output" "Halt!"
    assert_contains "$output" "I mean no harm"
}

test_list_last_n() {
    local sid npc_id
    sid=$(create_test_session)
    npc_id=$(create_test_character "$sid" "Sage" "npc")
    bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Sage" --content "First line" > /dev/null
    bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Sage" --content "Second line" > /dev/null
    bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Sage" --content "Third line" > /dev/null
    local output
    output=$(bash "$DIALOGUE" list "$sid" --npc "$npc_id" --last 1)
    assert_contains "$output" "Third line"
    assert_not_contains "$output" "First line"
}

test_search_dialogue() {
    local sid npc_id
    sid=$(create_test_session)
    npc_id=$(create_test_character "$sid" "Oracle" "npc")
    bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Oracle" --content "The prophecy speaks of doom" > /dev/null
    bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Player" --content "Tell me more" > /dev/null
    local output
    output=$(bash "$DIALOGUE" search "$sid" --query "prophecy")
    assert_contains "$output" "prophecy"
    assert_not_contains "$output" "Tell me more"
}

test_search_case_insensitive() {
    local sid npc_id
    sid=$(create_test_session)
    npc_id=$(create_test_character "$sid" "Bard" "npc")
    bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Bard" --content "The DRAGON awaits" > /dev/null
    local output
    # SQLite LIKE is case-insensitive for ASCII by default
    output=$(bash "$DIALOGUE" search "$sid" --query "dragon")
    assert_contains "$output" "DRAGON"
}

# ── Error Cases ────────────────────────────────────────────────────────

test_no_action_fails() {
    local exit_code=0
    bash "$DIALOGUE" 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_add_missing_npc_fails() {
    local sid
    sid=$(create_test_session)
    local exit_code=0
    local output
    output=$(bash "$DIALOGUE" add "$sid" --speaker "X" --content "Y" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_add_missing_speaker_fails() {
    local sid npc_id
    sid=$(create_test_session)
    npc_id=$(create_test_character "$sid" "NPC" "npc")
    local exit_code=0
    local output
    output=$(bash "$DIALOGUE" add "$sid" --npc "$npc_id" --content "Y" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_add_missing_content_fails() {
    local sid npc_id
    sid=$(create_test_session)
    npc_id=$(create_test_character "$sid" "NPC" "npc")
    local exit_code=0
    local output
    output=$(bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "X" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_list_missing_npc_fails() {
    local sid
    sid=$(create_test_session)
    local exit_code=0
    local output
    output=$(bash "$DIALOGUE" list "$sid" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

# ── Edge Cases ─────────────────────────────────────────────────────────

test_quotes_in_content() {
    local sid npc_id
    sid=$(create_test_session)
    npc_id=$(create_test_character "$sid" "Innkeeper" "npc")
    bash "$DIALOGUE" add "$sid" --npc "$npc_id" --speaker "Innkeeper" --content "He said 'hello' to me" > /dev/null
    local output
    output=$(bash "$DIALOGUE" list "$sid" --npc "$npc_id")
    assert_contains "$output" "said"
}

test_multiple_npcs_isolated() {
    local sid npc1 npc2
    sid=$(create_test_session)
    npc1=$(create_test_character "$sid" "NPC1" "npc")
    npc2=$(create_test_character "$sid" "NPC2" "npc")
    bash "$DIALOGUE" add "$sid" --npc "$npc1" --speaker "NPC1" --content "Line from NPC1" > /dev/null
    bash "$DIALOGUE" add "$sid" --npc "$npc2" --speaker "NPC2" --content "Line from NPC2" > /dev/null
    local output
    output=$(bash "$DIALOGUE" list "$sid" --npc "$npc1")
    assert_contains "$output" "Line from NPC1"
    assert_not_contains "$output" "Line from NPC2"
}

# ── Run ────────────────────────────────────────────────────────────────
run_test "add dialogue"                    test_add_dialogue
run_test "list dialogue"                   test_list_dialogue
run_test "list --last N"                   test_list_last_n
run_test "search dialogue"                 test_search_dialogue
run_test "search case insensitive"         test_search_case_insensitive
run_test "no action fails"                 test_no_action_fails
run_test "add missing --npc fails"         test_add_missing_npc_fails
run_test "add missing --speaker fails"     test_add_missing_speaker_fails
run_test "add missing --content fails"     test_add_missing_content_fails
run_test "list missing --npc fails"        test_list_missing_npc_fails
run_test "quotes in content"               test_quotes_in_content
run_test "multiple NPCs isolated"          test_multiple_npcs_isolated

echo "PASSED: $(get_passed)"
echo "FAILED: $(get_failed)"
