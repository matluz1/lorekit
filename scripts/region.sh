#!/usr/bin/env bash
set -euo pipefail

# region.sh -- Manage regions (locations, areas) within a session.
#
# Usage: bash scripts/region.sh <action> [args]
#
# Actions:
#   create <session_id> --name <name> --desc <description>
#   list <session_id>
#   view <region_id>
#   update <region_id> --name <name> --desc <description>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${LOREKIT_DB:-$SCRIPT_DIR/../data/game.db}"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: Database not found. Run init_db.sh first." >&2
    exit 1
fi

# Escape single quotes for safe SQL insertion
esc() { echo "$1" | sed "s/'/''/g"; }

usage() {
    echo "Usage: bash scripts/region.sh <action> [args]"
    echo ""
    echo "Actions:"
    echo "  create <session_id> --name <name> --desc <description>"
    echo "  list <session_id>"
    echo "  view <region_id>"
    echo "  update <region_id> --name <name> --desc <description>"
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

ACTION="$1"
shift

case "$ACTION" in
    create)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"; shift
        NAME="" DESC=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --name) NAME="$2"; shift 2 ;;
                --desc) DESC="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$NAME" ]]; then
            echo "ERROR: --name is required" >&2; exit 1
        fi
        ID=$(sqlite3 "$DB_PATH" "INSERT INTO regions (session_id, name, description) VALUES ($SESSION_ID, '$(esc "$NAME")', '$(esc "$DESC")'); SELECT last_insert_rowid();")
        echo "REGION_CREATED: $ID"
        ;;

    list)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"
        sqlite3 -header -column "$DB_PATH" "SELECT id, name, description, created_at FROM regions WHERE session_id = $SESSION_ID ORDER BY id;"
        ;;

    view)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: region_id required" >&2; exit 1
        fi
        REGION_ID="$1"
        ROW=$(sqlite3 -separator '|' "$DB_PATH" "SELECT id, session_id, name, description, created_at FROM regions WHERE id = $REGION_ID;")
        if [[ -z "$ROW" ]]; then
            echo "ERROR: Region $REGION_ID not found" >&2; exit 1
        fi
        IFS='|' read -r id sid name desc created <<< "$ROW"
        echo "ID: $id"
        echo "SESSION: $sid"
        echo "NAME: $name"
        echo "DESCRIPTION: $desc"
        echo "CREATED: $created"
        echo ""
        echo "--- NPCs IN THIS REGION ---"
        sqlite3 -header -column "$DB_PATH" "SELECT id, name, level, status FROM characters WHERE region_id = $REGION_ID AND type = 'npc' ORDER BY id;"
        ;;

    update)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: region_id required" >&2; exit 1
        fi
        REGION_ID="$1"; shift
        SETS=()
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --name) SETS+=("name = '$(esc "$2")'");        shift 2 ;;
                --desc) SETS+=("description = '$(esc "$2")'"); shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ ${#SETS[@]} -eq 0 ]]; then
            echo "ERROR: Provide --name and/or --desc" >&2; exit 1
        fi
        SET_CLAUSE=$(IFS=,; echo "${SETS[*]}")
        sqlite3 "$DB_PATH" "UPDATE regions SET $SET_CLAUSE WHERE id = $REGION_ID;"
        echo "REGION_UPDATED: $REGION_ID"
        ;;

    *)
        echo "ERROR: Unknown action: $ACTION" >&2
        usage
        ;;
esac
