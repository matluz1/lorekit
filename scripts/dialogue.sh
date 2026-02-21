#!/usr/bin/env bash
set -euo pipefail

# dialogue.sh -- Record and query dialogues between the player and NPCs.
#
# Usage: bash scripts/dialogue.sh <action> [args]
#
# Actions:
#   add <session_id> --npc <npc_id> --speaker <pc|npc_name> --content "<text>"
#   list <session_id> --npc <npc_id> [--last <N>]
#   search <session_id> --query "<text>"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${LOREKIT_DB:-$SCRIPT_DIR/../data/game.db}"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: Database not found. Run init_db.sh first." >&2
    exit 1
fi

# Escape single quotes for safe SQL insertion
esc() { echo "$1" | sed "s/'/''/g"; }

usage() {
    echo "Usage: bash scripts/dialogue.sh <action> [args]"
    echo ""
    echo "Actions:"
    echo "  add <session_id> --npc <npc_id> --speaker <pc|npc_name> --content \"<text>\""
    echo "  list <session_id> --npc <npc_id> [--last <N>]"
    echo "  search <session_id> --query \"<text>\""
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
        NPC="" SPEAKER="" CONTENT=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --npc)     NPC="$2";     shift 2 ;;
                --speaker) SPEAKER="$2"; shift 2 ;;
                --content) CONTENT="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$NPC" || -z "$SPEAKER" || -z "$CONTENT" ]]; then
            echo "ERROR: --npc, --speaker, and --content are required" >&2; exit 1
        fi
        ID=$(sqlite3 "$DB_PATH" "INSERT INTO dialogues (session_id, npc_id, speaker, content) VALUES ($SESSION_ID, $NPC, '$(esc "$SPEAKER")', '$(esc "$CONTENT")'); SELECT last_insert_rowid();")
        echo "DIALOGUE_ADDED: $ID"
        ;;

    list)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"; shift
        NPC="" LAST=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --npc)  NPC="$2";  shift 2 ;;
                --last) LAST="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$NPC" ]]; then
            echo "ERROR: --npc is required" >&2; exit 1
        fi
        QUERY="SELECT d.id, c.name AS npc, d.speaker, d.content, d.created_at FROM dialogues d JOIN characters c ON d.npc_id = c.id WHERE d.session_id = $SESSION_ID AND d.npc_id = $NPC ORDER BY d.id"
        if [[ -n "$LAST" ]]; then
            # Get the last N lines by ordering descending, limiting, then re-ordering
            QUERY="SELECT * FROM ($QUERY DESC LIMIT $LAST) ORDER BY id"
        fi
        sqlite3 -header -column "$DB_PATH" "$QUERY;"
        ;;

    search)
        if [[ $# -lt 1 ]]; then
            echo "ERROR: session_id required" >&2; exit 1
        fi
        SESSION_ID="$1"; shift
        QUERY_TEXT=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --query) QUERY_TEXT="$2"; shift 2 ;;
                *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
            esac
        done
        if [[ -z "$QUERY_TEXT" ]]; then
            echo "ERROR: --query is required" >&2; exit 1
        fi
        sqlite3 -header -column "$DB_PATH" "SELECT d.id, c.name AS npc, d.speaker, d.content, d.created_at FROM dialogues d JOIN characters c ON d.npc_id = c.id WHERE d.session_id = $SESSION_ID AND d.content LIKE '%$(esc "$QUERY_TEXT")%' ORDER BY d.id;"
        ;;

    *)
        echo "ERROR: Unknown action: $ACTION" >&2
        usage
        ;;
esac
