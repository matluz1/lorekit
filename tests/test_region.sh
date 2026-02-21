#!/usr/bin/env bash
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TESTS_DIR/test_helpers.sh"

REGION="$SCRIPTS_DIR/region.sh"

# ── Happy Path ─────────────────────────────────────────────────────────

test_create_region() {
    local sid
    sid=$(create_test_session)
    local output
    output=$(bash "$REGION" create "$sid" --name "Darkwood" --desc "A dense forest")
    assert_match "$output" "REGION_CREATED: [0-9]+"
}

test_view_region() {
    local sid rid
    sid=$(create_test_session)
    rid=$(create_test_region "$sid" "Ironforge" "Dwarven city")
    local output
    output=$(bash "$REGION" view "$rid")
    assert_contains "$output" "NAME: Ironforge"
    assert_contains "$output" "DESCRIPTION: Dwarven city"
}

test_list_regions() {
    local sid
    sid=$(create_test_session)
    create_test_region "$sid" "Town" > /dev/null
    create_test_region "$sid" "Dungeon" > /dev/null
    local output
    output=$(bash "$REGION" list "$sid")
    assert_contains "$output" "Town"
    assert_contains "$output" "Dungeon"
}

test_update_region_name() {
    local sid rid
    sid=$(create_test_session)
    rid=$(create_test_region "$sid" "OldName")
    bash "$REGION" update "$rid" --name "NewName" > /dev/null
    local output
    output=$(bash "$REGION" view "$rid")
    assert_contains "$output" "NAME: NewName"
}

test_update_region_desc() {
    local sid rid
    sid=$(create_test_session)
    rid=$(create_test_region "$sid" "Place" "Old desc")
    bash "$REGION" update "$rid" --desc "New desc" > /dev/null
    local output
    output=$(bash "$REGION" view "$rid")
    assert_contains "$output" "DESCRIPTION: New desc"
}

test_view_shows_npcs() {
    local sid rid
    sid=$(create_test_session)
    rid=$(create_test_region "$sid" "Village")
    create_test_character "$sid" "Guard" "npc" "$rid" > /dev/null
    local output
    output=$(bash "$REGION" view "$rid")
    assert_contains "$output" "NPCs IN THIS REGION"
    assert_contains "$output" "Guard"
}

test_view_excludes_pcs() {
    local sid rid
    sid=$(create_test_session)
    rid=$(create_test_region "$sid" "Camp")
    create_test_character "$sid" "Hero" "pc" "$rid" > /dev/null
    create_test_character "$sid" "Merchant" "npc" "$rid" > /dev/null
    local output
    output=$(bash "$REGION" view "$rid")
    assert_contains "$output" "Merchant"
    assert_not_contains "$output" "Hero"
}

test_create_without_desc() {
    local sid
    sid=$(create_test_session)
    local output
    output=$(bash "$REGION" create "$sid" --name "EmptyPlace")
    assert_match "$output" "REGION_CREATED: [0-9]+"
}

# ── Error Cases ────────────────────────────────────────────────────────

test_no_action_fails() {
    local exit_code=0
    bash "$REGION" 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_create_missing_session_fails() {
    local exit_code=0
    bash "$REGION" create 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_create_missing_name_fails() {
    local sid
    sid=$(create_test_session)
    local exit_code=0
    local output
    output=$(bash "$REGION" create "$sid" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_view_nonexistent_fails() {
    local exit_code=0
    local output
    output=$(bash "$REGION" view 9999 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
    assert_contains "$output" "not found"
}

# ── Edge Cases ─────────────────────────────────────────────────────────

test_sql_escaping_in_region_name() {
    local sid rid
    sid=$(create_test_session)
    rid=$(create_test_region "$sid" "Dragon's Lair" "It's dangerous")
    local output
    output=$(bash "$REGION" view "$rid")
    assert_contains "$output" "Dragon's Lair"
}

test_update_both_name_and_desc() {
    local sid rid
    sid=$(create_test_session)
    rid=$(create_test_region "$sid" "Old" "old desc")
    bash "$REGION" update "$rid" --name "New" --desc "new desc" > /dev/null
    local output
    output=$(bash "$REGION" view "$rid")
    assert_contains "$output" "NAME: New"
    assert_contains "$output" "DESCRIPTION: new desc"
}

# ── Run ────────────────────────────────────────────────────────────────
run_test "create region"                   test_create_region
run_test "view region"                     test_view_region
run_test "list regions"                    test_list_regions
run_test "update region name"              test_update_region_name
run_test "update region description"       test_update_region_desc
run_test "view shows NPCs in region"       test_view_shows_npcs
run_test "view excludes PCs from NPC list" test_view_excludes_pcs
run_test "create without description"      test_create_without_desc
run_test "no action fails"                 test_no_action_fails
run_test "create missing session fails"    test_create_missing_session_fails
run_test "create missing name fails"       test_create_missing_name_fails
run_test "view nonexistent fails"          test_view_nonexistent_fails
run_test "SQL escaping in region name"     test_sql_escaping_in_region_name
run_test "update both name and desc"       test_update_both_name_and_desc

echo "PASSED: $(get_passed)"
echo "FAILED: $(get_failed)"
