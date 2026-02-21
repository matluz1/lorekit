#!/usr/bin/env bash
set -euo pipefail

# run_tests.sh -- Run all LoreKit tests and report results.

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TOTAL_PASSED=0
TOTAL_FAILED=0
FILES_RUN=0

# Colors
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    GREEN='' RED='' BOLD='' RESET=''
fi

echo ""
printf "${BOLD}LoreKit Test Suite${RESET}\n"
echo "═══════════════════════════════════════"

for test_file in "$TESTS_DIR"/test_*.sh; do
    [[ -f "$test_file" ]] || continue
    filename=$(basename "$test_file")
    # Skip the helpers file
    [[ "$filename" == "test_helpers.sh" ]] && continue
    echo ""
    printf "${BOLD}▸ %s${RESET}\n" "$filename"

    # Run the test file and capture output
    output=$(bash "$test_file" 2>&1) || true

    # Show only PASS/FAIL lines and the counters
    echo "$output" | grep -E '^\s*(PASS|FAIL)|^PASSED:|^FAILED:' || true

    # Extract passed/failed from the last lines
    passed=$(echo "$output" | grep '^PASSED:' | tail -1 | awk '{print $2}') || true
    failed=$(echo "$output" | grep '^FAILED:' | tail -1 | awk '{print $2}') || true

    TOTAL_PASSED=$(( TOTAL_PASSED + ${passed:-0} ))
    TOTAL_FAILED=$(( TOTAL_FAILED + ${failed:-0} ))
    FILES_RUN=$(( FILES_RUN + 1 ))
done

echo ""
echo "═══════════════════════════════════════"
TOTAL=$(( TOTAL_PASSED + TOTAL_FAILED ))
printf "${BOLD}Results: ${RESET}"
if [[ $TOTAL_FAILED -eq 0 ]]; then
    printf "${GREEN}%d/%d passed${RESET} across %d files\n" "$TOTAL_PASSED" "$TOTAL" "$FILES_RUN"
else
    printf "${RED}%d failed${RESET}, ${GREEN}%d passed${RESET} out of %d across %d files\n" \
        "$TOTAL_FAILED" "$TOTAL_PASSED" "$TOTAL" "$FILES_RUN"
fi
echo ""

exit $TOTAL_FAILED
