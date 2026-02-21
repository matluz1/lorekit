#!/usr/bin/env bash
set -euo pipefail

# rolldice.sh -- Roll dice using standard tabletop notation.
#
# Usage: ./rolldice.sh <expression>
#
# Supports:
#   d20        Roll 1d20
#   3d6        Roll 3d6, show each + total
#   2d8+5      Roll 2d8 and add 5
#   2d8-2      Roll 2d8 and subtract 2
#   d100       Percentile roll
#   4d6kh3     Roll 4d6, keep highest 3
#
# Output format (machine-readable):
#   ROLLS: 4,3,6,2
#   KEPT: 6,4,3
#   MODIFIER: +5
#   TOTAL: 18

usage() {
    echo "Usage: $(basename "$0") <expression>"
    echo ""
    echo "Examples:"
    echo "  $(basename "$0") d20        # Roll 1d20"
    echo "  $(basename "$0") 3d6        # Roll 3d6"
    echo "  $(basename "$0") 2d8+5      # Roll 2d8 and add 5"
    echo "  $(basename "$0") 4d6kh3     # Roll 4d6, keep highest 3"
    exit 1
}

if [[ $# -ne 1 ]]; then
    usage
fi

EXPR="${1,,}"  # lowercase

# Parse the dice expression: [N]d<S>[kh<K>][+/-<M>]
if [[ ! "$EXPR" =~ ^([0-9]*)d([0-9]+)(kh([0-9]+))?([+-]([0-9]+))?$ ]]; then
    echo "ERROR: Invalid dice expression: $1" >&2
    echo "Expected format: [N]d<sides>[kh<keep>][+/-<modifier>]" >&2
    exit 1
fi

NUM="${BASH_REMATCH[1]:-1}"
SIDES="${BASH_REMATCH[2]}"
KEEP="${BASH_REMATCH[4]:-}"
MOD_SIGN="${BASH_REMATCH[5]:0:1}"
MOD_VAL="${BASH_REMATCH[6]:-0}"

# Validate
if [[ "$NUM" -lt 1 ]]; then
    echo "ERROR: Number of dice must be at least 1" >&2
    exit 1
fi

if [[ "$SIDES" -lt 2 ]]; then
    echo "ERROR: Dice must have at least 2 sides" >&2
    exit 1
fi

if [[ -n "$KEEP" ]]; then
    if [[ "$KEEP" -lt 1 || "$KEEP" -gt "$NUM" ]]; then
        echo "ERROR: Keep count must be between 1 and $NUM" >&2
        exit 1
    fi
fi

# Seed RANDOM from /dev/urandom for better randomness
RANDOM=$(od -An -tu4 -N4 /dev/urandom | tr -d ' ')

# Roll the dice
ROLLS=()
for (( i = 0; i < NUM; i++ )); do
    ROLLS+=( $(( (RANDOM % SIDES) + 1 )) )
done

# Format rolls
ROLLS_STR=$(IFS=,; echo "${ROLLS[*]}")

# Determine kept dice
if [[ -n "$KEEP" ]]; then
    # Sort descending, keep top K
    SORTED=($(printf '%s\n' "${ROLLS[@]}" | sort -rn))
    KEPT=("${SORTED[@]:0:$KEEP}")
    KEPT_STR=$(IFS=,; echo "${KEPT[*]}")
else
    KEPT=("${ROLLS[@]}")
    KEPT_STR="$ROLLS_STR"
fi

# Calculate total
SUM=0
for val in "${KEPT[@]}"; do
    SUM=$(( SUM + val ))
done

# Apply modifier
MODIFIER="+0"
if [[ "$MOD_VAL" -ne 0 ]]; then
    if [[ "$MOD_SIGN" == "-" ]]; then
        MODIFIER="-${MOD_VAL}"
        SUM=$(( SUM - MOD_VAL ))
    else
        MODIFIER="+${MOD_VAL}"
        SUM=$(( SUM + MOD_VAL ))
    fi
fi

# Output
echo "ROLLS: $ROLLS_STR"
echo "KEPT: $KEPT_STR"
echo "MODIFIER: $MODIFIER"
echo "TOTAL: $SUM"
