#!/usr/bin/env bash
set -euo pipefail

# journal.sh -- Append-only adventure log.
#
# Usage: bash scripts/journal.sh <action> [args]
#
# Actions:
#   add <session_id> --type <type> --content <content>
#   list <session_id> [--type <type>] [--last <N>]
#   search <session_id> --query <text>
#
# Entry types: event, combat, discovery, npc, decision, note

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${LOREKIT_DB:-$SCRIPT_DIR/../data/game.db}"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: Database not found. Run init_db.sh first." >&2
    exit 1
fi

esc() { echo "$1" | sed "s/'/''/g"; }

usage() {
    echo "Usage: bash scripts/journal.sh <action> [args]"
    echo ""
    echo "Actions:"
    echo "  add <session_id> --type <type> --content <content>"
    echo "  list <session_id> [--type <type>] [--last <N>]"
    echo "  search <session_id> --query <text>"
    echo ""
    echo "Types: event, combat, discovery, npc, decision, note"
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

ACTION="$1"
shift

case "$ACTION" in
    add)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"; shift
        TYPE="" CONTENT=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --type)    TYPE="$2";    shift 2 ;;
                --content) CONTENT="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$TYPE" || -z "$CONTENT" ]]; then
            echo "ERROR: --type and --content are required" >&2; exit 1
        fi
        ID=$(sqlite3 "$DB_PATH" "INSERT INTO journal (session_id, entry_type, content) VALUES ($SESSION_ID, '$(esc "$TYPE")', '$(esc "$CONTENT")'); SELECT last_insert_rowid();")
        echo "JOURNAL_ADDED: $ID"
        ;;

    list)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"; shift
        TYPE="" LAST=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --type) TYPE="$2"; shift 2 ;;
                --last) LAST="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        WHERE="WHERE session_id = $SESSION_ID"
        if [[ -n "$TYPE" ]]; then
            WHERE="$WHERE AND entry_type = '$(esc "$TYPE")'"
        fi
        LIMIT=""
        if [[ -n "$LAST" ]]; then
            LIMIT="LIMIT $LAST"
        fi
        sqlite3 -header -column "$DB_PATH" "SELECT id, entry_type, content, created_at FROM journal $WHERE ORDER BY id DESC $LIMIT;"
        ;;

    search)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"; shift
        QUERY=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --query) QUERY="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$QUERY" ]]; then
            echo "ERROR: --query is required" >&2; exit 1
        fi
        sqlite3 -header -column "$DB_PATH" "SELECT id, entry_type, content, created_at FROM journal WHERE session_id = $SESSION_ID AND content LIKE '%$(esc "$QUERY")%' ORDER BY id;"
        ;;

    *)
        echo "ERROR: Unknown action: $ACTION" >&2
        usage
        ;;
esac
