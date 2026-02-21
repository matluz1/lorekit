#!/usr/bin/env bash
set -euo pipefail

# session.sh -- Manage adventure sessions.
#
# Usage: bash scripts/session.sh <action> [args]
#
# Actions:
#   create --name <name> --setting <setting> --system <system_type>
#   view <session_id>
#   list [--status active|finished]
#   update <session_id> --status <status>
#   meta-set <session_id> --key <key> --value <value>
#   meta-get <session_id> [--key <key>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${LOREKIT_DB:-$SCRIPT_DIR/../data/game.db}"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: Database not found. Run init_db.sh first." >&2
    exit 1
fi

usage() {
    echo "Usage: bash scripts/session.sh <action> [args]"
    echo ""
    echo "Actions:"
    echo "  create --name <name> --setting <setting> --system <system_type>"
    echo "  view <session_id>"
    echo "  list [--status active|finished]"
    echo "  update <session_id> --status <status>"
    echo "  meta-set <session_id> --key <key> --value <value>"
    echo "  meta-get <session_id> [--key <key>]"
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

ACTION="$1"
shift

case "$ACTION" in
    create)
        NAME="" SETTING="" SYSTEM=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --name)   NAME="$2";    shift 2 ;;
                --setting) SETTING="$2"; shift 2 ;;
                --system) SYSTEM="$2";  shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$NAME" || -z "$SETTING" || -z "$SYSTEM" ]]; then
            echo "ERROR: --name, --setting, and --system are required" >&2
            exit 1
        fi
        ID=$(sqlite3 "$DB_PATH" "INSERT INTO sessions (name, setting, system_type) VALUES ('$(echo "$NAME" | sed "s/'/''/g")', '$(echo "$SETTING" | sed "s/'/''/g")', '$(echo "$SYSTEM" | sed "s/'/''/g")'); SELECT last_insert_rowid();")
        echo "SESSION_CREATED: $ID"
        ;;

    view)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"
        ROW=$(sqlite3 -separator '|' "$DB_PATH" "SELECT id, name, setting, system_type, status, created_at, updated_at FROM sessions WHERE id = $SESSION_ID;")
        if [[ -z "$ROW" ]]; then
            echo "ERROR: Session $SESSION_ID not found" >&2; exit 1
        fi
        IFS='|' read -r id name setting system status created updated <<< "$ROW"
        echo "ID: $id"
        echo "NAME: $name"
        echo "SETTING: $setting"
        echo "SYSTEM: $system"
        echo "STATUS: $status"
        echo "CREATED: $created"
        echo "UPDATED: $updated"
        ;;

    list)
        FILTER=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --status) FILTER="WHERE status = '$2'"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        sqlite3 -header -column "$DB_PATH" "SELECT id, name, setting, system_type, status, created_at FROM sessions $FILTER ORDER BY id;"
        ;;

    update)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"; shift
        STATUS=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --status) STATUS="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$STATUS" ]]; then
            echo "ERROR: --status is required" >&2; exit 1
        fi
        sqlite3 "$DB_PATH" "UPDATE sessions SET status = '$(echo "$STATUS" | sed "s/'/''/g")', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = $SESSION_ID;"
        echo "SESSION_UPDATED: $SESSION_ID"
        ;;

    meta-set)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"; shift
        KEY="" VALUE=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --key)   KEY="$2";   shift 2 ;;
                --value) VALUE="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$KEY" || -z "$VALUE" ]]; then
            echo "ERROR: --key and --value are required" >&2; exit 1
        fi
        sqlite3 "$DB_PATH" "INSERT INTO session_meta (session_id, key, value) VALUES ($SESSION_ID, '$(echo "$KEY" | sed "s/'/''/g")', '$(echo "$VALUE" | sed "s/'/''/g")') ON CONFLICT(session_id, key) DO UPDATE SET value = excluded.value;"
        echo "META_SET: $KEY"
        ;;

    meta-get)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"; shift
        KEY=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --key) KEY="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -n "$KEY" ]]; then
            VALUE=$(sqlite3 "$DB_PATH" "SELECT value FROM session_meta WHERE session_id = $SESSION_ID AND key = '$(echo "$KEY" | sed "s/'/''/g")';")
            echo "$KEY: $VALUE"
        else
            sqlite3 -header -column "$DB_PATH" "SELECT key, value FROM session_meta WHERE session_id = $SESSION_ID ORDER BY key;"
        fi
        ;;

    *)
        echo "ERROR: Unknown action: $ACTION" >&2
        usage
        ;;
esac
