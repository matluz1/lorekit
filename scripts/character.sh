#!/usr/bin/env bash
set -euo pipefail

# character.sh -- Manage characters and their attributes, inventory, abilities.
#
# Usage: bash scripts/character.sh <action> [args]
#
# Actions:
#   create --session <id> --name <name> --level <level>
#   view <character_id>
#   list --session <session_id>
#   update <character_id> --level <level> | --status <status>
#   set-attr <character_id> --category <cat> --key <key> --value <value>
#   get-attr <character_id> [--category <cat>]
#   set-item <character_id> --name <name> [--desc <desc>] [--qty <n>] [--equipped 0|1]
#   get-items <character_id>
#   remove-item <item_id>
#   set-ability <character_id> --name <name> --desc <desc> --category <cat> [--uses <uses>]
#   get-abilities <character_id>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="$SCRIPT_DIR/../data/game.db"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: Database not found. Run init_db.sh first." >&2
    exit 1
fi

# Escape single quotes for safe SQL insertion
esc() { echo "$1" | sed "s/'/''/g"; }

usage() {
    echo "Usage: bash scripts/character.sh <action> [args]"
    echo ""
    echo "Actions:"
    echo "  create --session <id> --name <name> --level <level>"
    echo "  view <character_id>"
    echo "  list --session <session_id>"
    echo "  update <character_id> --level <level> | --status <status>"
    echo "  set-attr <character_id> --category <cat> --key <key> --value <value>"
    echo "  get-attr <character_id> [--category <cat>]"
    echo "  set-item <character_id> --name <name> [--desc <desc>] [--qty <n>] [--equipped 0|1]"
    echo "  get-items <character_id>"
    echo "  remove-item <item_id>"
    echo "  set-ability <character_id> --name <name> --desc <desc> --category <cat> [--uses <uses>]"
    echo "  get-abilities <character_id>"
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

ACTION="$1"
shift

case "$ACTION" in
    create)
        SESSION="" NAME="" LEVEL="1"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --session) SESSION="$2"; shift 2 ;;
                --name)    NAME="$2";    shift 2 ;;
                --level)   LEVEL="$2";   shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$SESSION" || -z "$NAME" ]]; then
            echo "ERROR: --session and --name are required" >&2; exit 1
        fi
        ID=$(sqlite3 "$DB_PATH" "INSERT INTO characters (session_id, name, level) VALUES ($SESSION, '$(esc "$NAME")', $LEVEL); SELECT last_insert_rowid();")
        echo "CHARACTER_CREATED: $ID"
        ;;

    view)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: character_id required" >&2; exit 1
        fi
        CHAR_ID="$1"
        ROW=$(sqlite3 -separator '|' "$DB_PATH" "SELECT id, session_id, name, level, status, created_at FROM characters WHERE id = $CHAR_ID;")
        if [[ -z "$ROW" ]]; then
            echo "ERROR: Character $CHAR_ID not found" >&2; exit 1
        fi
        IFS='|' read -r id sid name level status created <<< "$ROW"
        echo "ID: $id"
        echo "SESSION: $sid"
        echo "NAME: $name"
        echo "LEVEL: $level"
        echo "STATUS: $status"
        echo "CREATED: $created"
        echo ""
        echo "--- ATTRIBUTES ---"
        sqlite3 -header -column "$DB_PATH" "SELECT category, key, value FROM character_attributes WHERE character_id = $CHAR_ID ORDER BY category, key;"
        echo ""
        echo "--- INVENTORY ---"
        sqlite3 -header -column "$DB_PATH" "SELECT id, name, description, quantity, equipped FROM character_inventory WHERE character_id = $CHAR_ID ORDER BY name;"
        echo ""
        echo "--- ABILITIES ---"
        sqlite3 -header -column "$DB_PATH" "SELECT id, name, category, uses, description FROM character_abilities WHERE character_id = $CHAR_ID ORDER BY category, name;"
        ;;

    list)
        SESSION=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --session) SESSION="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$SESSION" ]]; then
            echo "ERROR: --session is required" >&2; exit 1
        fi
        sqlite3 -header -column "$DB_PATH" "SELECT id, name, level, status FROM characters WHERE session_id = $SESSION ORDER BY id;"
        ;;

    update)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: character_id required" >&2; exit 1
        fi
        CHAR_ID="$1"; shift
        SETS=()
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --level)  SETS+=("level = $2");                    shift 2 ;;
                --status) SETS+=("status = '$(esc "$2")'");       shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ ${#SETS[@]} -eq 0 ]]; then
            echo "ERROR: Provide --level and/or --status" >&2; exit 1
        fi
        SET_CLAUSE=$(IFS=,; echo "${SETS[*]}")
        sqlite3 "$DB_PATH" "UPDATE characters SET $SET_CLAUSE WHERE id = $CHAR_ID;"
        echo "CHARACTER_UPDATED: $CHAR_ID"
        ;;

    set-attr)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: character_id required" >&2; exit 1
        fi
        CHAR_ID="$1"; shift
        CATEGORY="" KEY="" VALUE=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --category) CATEGORY="$2"; shift 2 ;;
                --key)      KEY="$2";      shift 2 ;;
                --value)    VALUE="$2";    shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$CATEGORY" || -z "$KEY" || -z "$VALUE" ]]; then
            echo "ERROR: --category, --key, and --value are required" >&2; exit 1
        fi
        sqlite3 "$DB_PATH" "INSERT INTO character_attributes (character_id, category, key, value) VALUES ($CHAR_ID, '$(esc "$CATEGORY")', '$(esc "$KEY")', '$(esc "$VALUE")') ON CONFLICT(character_id, category, key) DO UPDATE SET value = excluded.value;"
        echo "ATTR_SET: $KEY = $VALUE"
        ;;

    get-attr)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: character_id required" >&2; exit 1
        fi
        CHAR_ID="$1"; shift
        CATEGORY=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --category) CATEGORY="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -n "$CATEGORY" ]]; then
            sqlite3 -header -column "$DB_PATH" "SELECT key, value FROM character_attributes WHERE character_id = $CHAR_ID AND category = '$(esc "$CATEGORY")' ORDER BY key;"
        else
            sqlite3 -header -column "$DB_PATH" "SELECT category, key, value FROM character_attributes WHERE character_id = $CHAR_ID ORDER BY category, key;"
        fi
        ;;

    set-item)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: character_id required" >&2; exit 1
        fi
        CHAR_ID="$1"; shift
        NAME="" DESC="" QTY="1" EQUIPPED="0"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --name)     NAME="$2";     shift 2 ;;
                --desc)     DESC="$2";     shift 2 ;;
                --qty)      QTY="$2";      shift 2 ;;
                --equipped) EQUIPPED="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$NAME" ]]; then
            echo "ERROR: --name is required" >&2; exit 1
        fi
        ID=$(sqlite3 "$DB_PATH" "INSERT INTO character_inventory (character_id, name, description, quantity, equipped) VALUES ($CHAR_ID, '$(esc "$NAME")', '$(esc "$DESC")', $QTY, $EQUIPPED); SELECT last_insert_rowid();")
        echo "ITEM_ADDED: $ID"
        ;;

    get-items)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: character_id required" >&2; exit 1
        fi
        CHAR_ID="$1"
        sqlite3 -header -column "$DB_PATH" "SELECT id, name, description, quantity, equipped FROM character_inventory WHERE character_id = $CHAR_ID ORDER BY name;"
        ;;

    remove-item)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: item_id required" >&2; exit 1
        fi
        ITEM_ID="$1"
        sqlite3 "$DB_PATH" "DELETE FROM character_inventory WHERE id = $ITEM_ID;"
        echo "ITEM_REMOVED: $ITEM_ID"
        ;;

    set-ability)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: character_id required" >&2; exit 1
        fi
        CHAR_ID="$1"; shift
        NAME="" DESC="" CATEGORY="" USES="at_will"
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --name)     NAME="$2";     shift 2 ;;
                --desc)     DESC="$2";     shift 2 ;;
                --category) CATEGORY="$2"; shift 2 ;;
                --uses)     USES="$2";     shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$NAME" || -z "$DESC" || -z "$CATEGORY" ]]; then
            echo "ERROR: --name, --desc, and --category are required" >&2; exit 1
        fi
        ID=$(sqlite3 "$DB_PATH" "INSERT INTO character_abilities (character_id, name, description, category, uses) VALUES ($CHAR_ID, '$(esc "$NAME")', '$(esc "$DESC")', '$(esc "$CATEGORY")', '$(esc "$USES")'); SELECT last_insert_rowid();")
        echo "ABILITY_ADDED: $ID"
        ;;

    get-abilities)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: character_id required" >&2; exit 1
        fi
        CHAR_ID="$1"
        sqlite3 -header -column "$DB_PATH" "SELECT id, name, category, uses, description FROM character_abilities WHERE character_id = $CHAR_ID ORDER BY category, name;"
        ;;

    *)
        echo "ERROR: Unknown action: $ACTION" >&2
        usage
        ;;
esac
