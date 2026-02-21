#!/usr/bin/env bash
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TESTS_DIR/test_helpers.sh"

CHAR="$SCRIPTS_DIR/character.sh"

# ── Happy Path ─────────────────────────────────────────────────────────

test_create_pc() {
    local sid
    sid=$(create_test_session)
    local output
    output=$(bash "$CHAR" create --session "$sid" --name "Gandalf" --type pc)
    assert_match "$output" "CHARACTER_CREATED: [0-9]+"
}

test_create_npc() {
    local sid
    sid=$(create_test_session)
    local output
    output=$(bash "$CHAR" create --session "$sid" --name "Shopkeeper" --type npc)
    assert_match "$output" "CHARACTER_CREATED: [0-9]+"
}

test_create_with_region() {
    local sid rid
    sid=$(create_test_session)
    rid=$(create_test_region "$sid" "Tavern")
    local cid
    cid=$(create_test_character "$sid" "Barkeep" "npc" "$rid")
    local output
    output=$(bash "$CHAR" view "$cid")
    assert_contains "$output" "REGION: Tavern"
}

test_create_with_level() {
    local sid
    sid=$(create_test_session)
    local output cid
    output=$(bash "$CHAR" create --session "$sid" --name "Hero" --level 5)
    cid=$(echo "$output" | sed 's/CHARACTER_CREATED: //')
    output=$(bash "$CHAR" view "$cid")
    assert_contains "$output" "LEVEL: 5"
}

test_view_character() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Arwen" "pc")
    local output
    output=$(bash "$CHAR" view "$cid")
    assert_contains "$output" "NAME: Arwen"
    assert_contains "$output" "TYPE: pc"
    assert_contains "$output" "STATUS: alive"
}

test_list_characters() {
    local sid
    sid=$(create_test_session)
    create_test_character "$sid" "Alice" > /dev/null
    create_test_character "$sid" "Bob" > /dev/null
    local output
    output=$(bash "$CHAR" list --session "$sid")
    assert_contains "$output" "Alice"
    assert_contains "$output" "Bob"
}

test_list_filter_by_type() {
    local sid
    sid=$(create_test_session)
    create_test_character "$sid" "Hero" "pc" > /dev/null
    create_test_character "$sid" "Villager" "npc" > /dev/null
    local output
    output=$(bash "$CHAR" list --session "$sid" --type npc)
    assert_contains "$output" "Villager"
    assert_not_contains "$output" "Hero"
}

test_list_filter_by_region() {
    local sid rid
    sid=$(create_test_session)
    rid=$(create_test_region "$sid" "Forest")
    create_test_character "$sid" "Elf" "npc" "$rid" > /dev/null
    create_test_character "$sid" "Dwarf" "npc" > /dev/null
    local output
    output=$(bash "$CHAR" list --session "$sid" --region "$rid")
    assert_contains "$output" "Elf"
    assert_not_contains "$output" "Dwarf"
}

test_update_level() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Hero")
    bash "$CHAR" update "$cid" --level 10 > /dev/null
    local output
    output=$(bash "$CHAR" view "$cid")
    assert_contains "$output" "LEVEL: 10"
}

test_update_status() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Hero")
    bash "$CHAR" update "$cid" --status dead > /dev/null
    local output
    output=$(bash "$CHAR" view "$cid")
    assert_contains "$output" "STATUS: dead"
}

test_set_and_get_attribute() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Hero")
    bash "$CHAR" set-attr "$cid" --category stats --key strength --value 18 > /dev/null
    local output
    output=$(bash "$CHAR" get-attr "$cid" --category stats)
    assert_contains "$output" "strength"
    assert_contains "$output" "18"
}

test_attribute_overwrite() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Hero")
    bash "$CHAR" set-attr "$cid" --category stats --key str --value 10 > /dev/null
    bash "$CHAR" set-attr "$cid" --category stats --key str --value 20 > /dev/null
    local output
    output=$(bash "$CHAR" get-attr "$cid" --category stats)
    assert_contains "$output" "20"
    assert_not_contains "$output" "10"
}

test_get_attr_all_categories() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Hero")
    bash "$CHAR" set-attr "$cid" --category stats --key str --value 15 > /dev/null
    bash "$CHAR" set-attr "$cid" --category saves --key fort --value 5 > /dev/null
    local output
    output=$(bash "$CHAR" get-attr "$cid")
    assert_contains "$output" "stats"
    assert_contains "$output" "saves"
}

test_set_and_get_item() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Hero")
    bash "$CHAR" set-item "$cid" --name "Longsword" --desc "A fine blade" --qty 1 --equipped 1 > /dev/null
    local output
    output=$(bash "$CHAR" get-items "$cid")
    assert_contains "$output" "Longsword"
}

test_remove_item() {
    local sid cid item_id
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Hero")
    item_id=$(bash "$CHAR" set-item "$cid" --name "Potion" | sed 's/ITEM_ADDED: //')
    bash "$CHAR" remove-item "$item_id" > /dev/null
    local output
    output=$(bash "$CHAR" get-items "$cid")
    assert_not_contains "$output" "Potion"
}

test_set_and_get_ability() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Wizard")
    bash "$CHAR" set-ability "$cid" --name "Fireball" --desc "3d6 fire damage" --category spell --uses "3/day" > /dev/null
    local output
    output=$(bash "$CHAR" get-abilities "$cid")
    assert_contains "$output" "Fireball"
    assert_contains "$output" "spell"
}

# ── Error Cases ────────────────────────────────────────────────────────

test_no_action_fails() {
    local exit_code=0
    bash "$CHAR" 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_create_missing_session_fails() {
    local exit_code=0
    local output
    output=$(bash "$CHAR" create --name "X" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_create_missing_name_fails() {
    local sid
    sid=$(create_test_session)
    local exit_code=0
    local output
    output=$(bash "$CHAR" create --session "$sid" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_create_invalid_type_fails() {
    local sid
    sid=$(create_test_session)
    local exit_code=0
    local output
    output=$(bash "$CHAR" create --session "$sid" --name "X" --type monster 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
    assert_contains "$output" "pc or npc"
}

test_view_missing_id_fails() {
    local exit_code=0
    bash "$CHAR" view 2>&1 || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_view_nonexistent_fails() {
    local exit_code=0
    local output
    output=$(bash "$CHAR" view 9999 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
    assert_contains "$output" "not found"
}

test_list_missing_session_fails() {
    local exit_code=0
    local output
    output=$(bash "$CHAR" list 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

test_update_no_fields_fails() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "Hero")
    local exit_code=0
    local output
    output=$(bash "$CHAR" update "$cid" 2>&1) || exit_code=$?
    assert_exit_code "1" "$exit_code"
}

# ── Edge Cases ─────────────────────────────────────────────────────────

test_sql_escaping_in_name() {
    local sid cid
    sid=$(create_test_session)
    cid=$(create_test_character "$sid" "O'Malley")
    local output
    output=$(bash "$CHAR" view "$cid")
    assert_contains "$output" "O'Malley"
}

test_default_type_is_pc() {
    local sid
    sid=$(create_test_session)
    local output cid
    output=$(bash "$CHAR" create --session "$sid" --name "Default")
    cid=$(echo "$output" | sed 's/CHARACTER_CREATED: //')
    output=$(bash "$CHAR" view "$cid")
    assert_contains "$output" "TYPE: pc"
}

test_default_level_is_one() {
    local sid
    sid=$(create_test_session)
    local output cid
    output=$(bash "$CHAR" create --session "$sid" --name "Newbie")
    cid=$(echo "$output" | sed 's/CHARACTER_CREATED: //')
    output=$(bash "$CHAR" view "$cid")
    assert_contains "$output" "LEVEL: 1"
}

# ── Run ────────────────────────────────────────────────────────────────
run_test "create PC"                       test_create_pc
run_test "create NPC"                      test_create_npc
run_test "create with region"              test_create_with_region
run_test "create with level"               test_create_with_level
run_test "view character"                  test_view_character
run_test "list characters"                 test_list_characters
run_test "list filter by type"             test_list_filter_by_type
run_test "list filter by region"           test_list_filter_by_region
run_test "update level"                    test_update_level
run_test "update status"                   test_update_status
run_test "set and get attribute"           test_set_and_get_attribute
run_test "attribute overwrite"             test_attribute_overwrite
run_test "get all attribute categories"    test_get_attr_all_categories
run_test "set and get item"                test_set_and_get_item
run_test "remove item"                     test_remove_item
run_test "set and get ability"             test_set_and_get_ability
run_test "no action fails"                 test_no_action_fails
run_test "create missing --session fails"  test_create_missing_session_fails
run_test "create missing --name fails"     test_create_missing_name_fails
run_test "create invalid type fails"       test_create_invalid_type_fails
run_test "view missing id fails"           test_view_missing_id_fails
run_test "view nonexistent fails"          test_view_nonexistent_fails
run_test "list missing --session fails"    test_list_missing_session_fails
run_test "update no fields fails"          test_update_no_fields_fails
run_test "SQL escaping in name"            test_sql_escaping_in_name
run_test "default type is pc"              test_default_type_is_pc
run_test "default level is 1"              test_default_level_is_one

echo "PASSED: $(get_passed)"
echo "FAILED: $(get_failed)"
