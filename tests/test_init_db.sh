#!/usr/bin/env bash
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$TESTS_DIR/test_helpers.sh"

# ── Tests ──────────────────────────────────────────────────────────────

test_creates_database_file() {
    [[ -f "$LOREKIT_DB" ]] || { _fail "Database file not created"; return 1; }
}

test_creates_data_directory() {
    [[ -d "$LOREKIT_DB_DIR" ]] || { _fail "Data directory not created"; return 1; }
}

test_creates_all_nine_tables() {
    local tables
    tables=$(sqlite3 "$LOREKIT_DB" ".tables")
    for t in sessions session_meta characters character_attributes character_inventory character_abilities regions journal dialogues; do
        assert_contains "$tables" "$t" "table $t"
    done
}

test_idempotent_reinit() {
    # Run init again -- should succeed without error
    local output
    output=$(bash "$SCRIPTS_DIR/init_db.sh" 2>&1)
    assert_contains "$output" "Database initialized" "re-init message"
}

test_characters_has_type_column() {
    local cols
    cols=$(sqlite3 "$LOREKIT_DB" "PRAGMA table_info(characters);")
    assert_contains "$cols" "|type|" "type column"
}

test_characters_has_region_id_column() {
    local cols
    cols=$(sqlite3 "$LOREKIT_DB" "PRAGMA table_info(characters);")
    assert_contains "$cols" "|region_id|" "region_id column"
}

# ── Run ────────────────────────────────────────────────────────────────
run_test "creates database file"           test_creates_database_file
run_test "creates data directory"          test_creates_data_directory
run_test "creates all 9 tables"            test_creates_all_nine_tables
run_test "idempotent re-init"              test_idempotent_reinit
run_test "characters has type column"      test_characters_has_type_column
run_test "characters has region_id column" test_characters_has_region_id_column

echo "PASSED: $(get_passed)"
echo "FAILED: $(get_failed)"
