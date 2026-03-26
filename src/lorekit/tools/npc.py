import json
import os
import sqlite3
import subprocess

from lorekit._mcp_app import NPC_MCP_PORT, mcp
from lorekit.rules import project_root as _project_root
from lorekit.tools._helpers import (
    _load_combat_cfg,
    _resolve_character,
    _resolve_system_path_for_session,
)

_NPC_ALLOWED_TOOLS: list[str] = []

_MCP_PREFIX = "mcp__lorekit__"
_NPC_ALLOWED_SET = set(_NPC_ALLOWED_TOOLS)


def _get_npc_disallowed_tools() -> list[str]:
    """All tools are disallowed for NPCs — context is pre-fetched."""
    return [f"{_MCP_PREFIX}{name}" for name in mcp._tool_manager._tools]


def _load_npc_guides() -> str:
    """Load SHARED_GUIDE.md + NPC_GUIDE.md from guidelines/."""
    project_root = _project_root()
    guidelines_dir = os.path.join(project_root, "guidelines")
    parts = []
    for fname in ("SHARED_GUIDE.md", "NPC_GUIDE.md"):
        path = os.path.join(guidelines_dir, fname)
        try:
            with open(path, "r") as f:
                parts.append(f.read())
        except FileNotFoundError:
            pass
    return "\n\n".join(parts)


def _build_npc_prompt(db, npc_id: int, session_id: int, gm_message: str = "") -> tuple[str, str, str] | None:
    """Build NPC system prompt with pre-fetched context.

    Returns (system_prompt, model, npc_name) or None if NPC/session not found.
    """
    from lorekit.npc.prefetch import assemble_context

    db.row_factory = sqlite3.Row

    npc = db.execute("SELECT id, name, gender FROM characters WHERE id = ? AND type = 'npc'", (npc_id,)).fetchone()
    if not npc:
        return None

    session = db.execute("SELECT setting, system_type FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        return None

    npc_name = npc["name"]
    npc_gender = npc["gender"]
    setting = session["setting"]
    system_type = session["system_type"]

    # Attributes
    attrs = db.execute(
        "SELECT category, key, value FROM character_attributes WHERE character_id = ?",
        (npc_id,),
    ).fetchall()

    personality = "a common NPC"
    model = None
    identity_lines = []
    for a in attrs:
        if a["category"] == "identity" and a["key"] == "personality":
            personality = a["value"]
        elif a["category"] == "system" and a["key"] == "model":
            model = a["value"]
        if a["category"] != "system":
            identity_lines.append(f"  {a['key']}: {a['value']}")

    if model is None:
        from lorekit.db import LoreKitError

        raise LoreKitError(
            f"No model configured for NPC '{npc_name}' (id {npc_id}) — "
            "set category='system', key='model' in character_attributes"
        )

    # Inventory
    items = db.execute(
        "SELECT name, quantity, equipped FROM character_inventory WHERE character_id = ?",
        (npc_id,),
    ).fetchall()
    inv_lines = []
    for item in items:
        line = f"  {item['name']}"
        if item["quantity"] > 1:
            line += f" x{item['quantity']}"
        if item["equipped"]:
            line += " (equipped)"
        inv_lines.append(line)

    # Abilities
    abilities = db.execute(
        "SELECT name, uses, description FROM character_abilities WHERE character_id = ?",
        (npc_id,),
    ).fetchall()
    ability_lines = [f"  {ab['name']} ({ab['uses']}): {ab['description']}" for ab in abilities]

    # Combat modifiers (active conditions/buffs)
    combat_lines = []
    combat_rows = db.execute(
        "SELECT source, target_stat, modifier_type, value, bonus_type, duration_type, duration "
        "FROM combat_state WHERE character_id = ?",
        (npc_id,),
    ).fetchall()
    for cr in combat_rows:
        line = f"  {cr['source']}: {cr['modifier_type']} {cr['value']:+d} to {cr['target_stat']}"
        if cr["bonus_type"]:
            line += f" ({cr['bonus_type']})"
        if cr["duration_type"] == "rounds" and cr["duration"]:
            line += f" [{cr['duration']}r left]"
        combat_lines.append(line)

    # Get narrative time and lore_ meta keys
    meta_rows = db.execute(
        "SELECT key, value FROM session_meta WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    narrative_time = ""
    lore_lines = []
    _LORE_TOKEN_CAP = 800
    _lore_tokens = 0
    for mr in meta_rows:
        if mr["key"] == "narrative_time":
            narrative_time = mr["value"]
        elif mr["key"].startswith("lore_"):
            entry_tokens = len(mr["value"]) // 4
            if _lore_tokens + entry_tokens <= _LORE_TOKEN_CAP:
                label = mr["key"][5:].replace("_", " ").capitalize()
                lore_lines.append(f"  {label}: {mr['value']}")
                _lore_tokens += entry_tokens

    # Pre-fetch: core identity + memories + timeline
    prefetch_result = assemble_context(
        db,
        session_id,
        npc_id,
        gm_message,
        narrative_time=narrative_time,
    )

    _npc_log(f"[PREFETCH] {npc_name}: {prefetch_result.debug}")

    guides = _load_npc_guides()

    gender_line = f"\nGender: {npc_gender}" if npc_gender else ""

    lore_section = ""
    if lore_lines:
        lore_section = "\n\nWorld lore:\n" + chr(10).join(lore_lines)

    system_prompt = f"""You are {npc_name}, {personality}.{gender_line}

World setting: {setting}{lore_section}
Rule system: {system_type}

Your attributes:
{chr(10).join(identity_lines) if identity_lines else "  (none)"}

Your inventory:
{chr(10).join(inv_lines) if inv_lines else "  (none)"}

Your abilities:
{chr(10).join(ability_lines) if ability_lines else "  (none)"}

{"Active conditions:" + chr(10) + chr(10).join(combat_lines) + chr(10) if combat_lines else ""}{prefetch_result.context}

{guides}"""

    return system_prompt, model, npc_name


def _npc_log(msg: str):
    """Append a line to data/npc.log."""
    from datetime import datetime

    project_root = _project_root()
    log_path = os.path.join(project_root, "data", "lorekit.log")
    ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
    with open(log_path, "a") as f:
        f.write(f"{ts} NPC {msg}\n")


def _parse_npc_stream(stdout: str, npc_name: str = "NPC") -> tuple[str, list[str]]:
    """Parse stream-json output from the NPC process.

    Returns (response_text, list_of_tool_names_used).
    """
    _npc_log(f"[START] ─── {npc_name} ───")

    text_parts: list[str] = []
    tool_names: list[str] = []
    args_buffer = ""
    think_buffer = ""

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        if msg.get("type") == "assistant":
            # CLI outputs assistant messages with content arrays
            for block in msg.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    if name:
                        tool_names.append(name)
                        args = block.get("input", {})
                        _npc_log(f"[TOOL] {name}")
                        _npc_log(f"[ARGS] {json.dumps(args, ensure_ascii=False)}")
                elif block.get("type") == "thinking":
                    _npc_log(f"[THINK] {block.get('thinking', '')}")
                elif block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                    _npc_log(f"[TEXT] {block.get('text', '')}")
        elif msg.get("type") == "stream_event":
            evt = msg.get("event", {})
            if evt.get("type") == "content_block_start" and evt.get("content_block", {}).get("type") == "tool_use":
                name = evt["content_block"].get("name", "")
                if name:
                    tool_names.append(name)
                    _npc_log(f"[TOOL] {name}")
                    args_buffer = ""
            elif evt.get("type") == "content_block_delta":
                delta = evt.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_parts.append(delta.get("text", ""))
                elif delta.get("type") == "thinking_delta":
                    think_buffer += delta.get("thinking", "")
                elif delta.get("type") == "input_json_delta":
                    args_buffer += delta.get("partial_json", "")
            elif evt.get("type") == "content_block_stop":
                if think_buffer:
                    _npc_log(f"[THINK] {think_buffer}")
                    think_buffer = ""
                if args_buffer:
                    _npc_log(f"[ARGS] {args_buffer}")
                    args_buffer = ""
        elif msg.get("type") == "result":
            # Fallback: grab result text if we missed deltas
            if not text_parts and msg.get("result"):
                text_parts.append(msg["result"])

    _npc_log(f"[END] ─── {npc_name} ───")
    return "".join(text_parts), tool_names


def _is_npc_http_server_running() -> bool:
    """Check if the shared MCP HTTP server is listening."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", NPC_MCP_PORT), timeout=0.3):
            return True
    except (ConnectionRefusedError, OSError):
        return False


@mcp.tool()
def npc_interact(session_id: int, npc_id: int | str, message: str) -> str:
    """Make an NPC speak in character. Spawns an ephemeral AI process for the NPC.

    The GM should call this whenever the player wants to talk to an NPC.
    The message param should describe the situation and what the PC said.
    Returns the NPC's in-character response.

    npc_id: numeric ID or NPC name (case-insensitive).
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        npc_id = _resolve_character(db, npc_id, session_id)
        result = _build_npc_prompt(db, npc_id, session_id, gm_message=message)
        if not result:
            return f"ERROR: NPC #{npc_id} not found in session #{session_id}"
        system_prompt, model, npc_name = result
    finally:
        db.close()

    project_root = _project_root()

    # NPC is a pure narrative agent — no MCP tools needed
    cmd = [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--no-session-persistence",
        "--permission-mode",
        "bypassPermissions",
        "--tools",
        "",
        "--disable-slash-commands",
        "--model",
        model,
        "--system-prompt",
        system_prompt,
    ]
    cmd.append(message)
    _npc_log(f"[USER] → {npc_name}: {message[:500]}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            return f"ERROR: NPC process failed: {stderr or 'unknown error'}"

        response_text, _tool_names = _parse_npc_stream(proc.stdout, npc_name)

        # Post-process: extract memories/state from NPC response
        from lorekit.npc.postprocess import process_npc_response

        db2 = require_db()
        try:
            # Get narrative time from session meta
            meta_row = db2.execute(
                "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
                (session_id,),
            ).fetchone()
            narrative_time = meta_row[0] if meta_row else ""

            clean_text = process_npc_response(db2, session_id, npc_id, response_text, npc_name, narrative_time)
        except Exception:
            clean_text = response_text  # fallback: return raw text
        finally:
            db2.close()

        return clean_text.strip() or f"{npc_name} says nothing."
    except subprocess.TimeoutExpired:
        return "ERROR: NPC response timed out"
    except FileNotFoundError:
        return "ERROR: 'claude' CLI not found. Ensure it is installed and on PATH."


@mcp.tool()
def npc_memory_add(
    session_id: int,
    npc_id: int | str,
    content: str,
    importance: float = 0.5,
    memory_type: str = "experience",
    entities: str = "[]",
    narrative_time: str = "",
) -> str:
    """Add a memory to an NPC. Memories persist and influence future NPC behavior.

    memory_type: experience, observation, relationship, or reflection.
    importance: 0.0 to 1.0 (higher = more likely to be recalled).
    entities: JSON array of entity names referenced in this memory.
    narrative_time: in-game timestamp for the memory.
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        resolved_npc_id = _resolve_character(db, npc_id, session_id)

        # Verify it's an NPC
        row = db.execute("SELECT type FROM characters WHERE id = ?", (resolved_npc_id,)).fetchone()
        if not row or row[0] != "npc":
            return f"ERROR: Character {resolved_npc_id} is not an NPC"

        from lorekit.npc.memory import add_memory

        memory_id = add_memory(
            db, session_id, resolved_npc_id, content, importance, memory_type, entities, narrative_time
        )
        return f"NPC_MEMORY_ADDED: {memory_id}"
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def npc_reflect(session_id: int, npc_id: int | str) -> str:
    """Trigger reflection for a single NPC. Generates insights from accumulated memories."""
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        npc_id = _resolve_character(db, npc_id, session_id)
        # Verify it's an NPC
        char = db.execute("SELECT type FROM characters WHERE id = ?", (npc_id,)).fetchone()
        if not char or char[0] != "npc":
            return f"ERROR: Character #{npc_id} is not an NPC"
        from lorekit.npc.reflect import generate_reflection

        result = generate_reflection(db, session_id, npc_id)
        return f"NPC_REFLECTED: {result['npc_name']} — {result['reflections_stored']} reflections, {result['rules_added']} behavioral rules"
    except (LoreKitError, subprocess.SubprocessError, OSError) as e:
        return f"ERROR: {e}"
    finally:
        db.close()


@mcp.tool()
def entry_untag(source: str, source_id: int, entity_type: str, entity_id: int) -> str:
    """Remove an entity tag from a timeline or journal entry.

    Use this to correct auto-tagging errors (e.g. a character was falsely
    matched in text).

    source: 'timeline' or 'journal'.
    entity_type: 'character' or 'region'.
    """
    from lorekit.db import require_db

    if source not in ("timeline", "journal"):
        return "ERROR: source must be 'timeline' or 'journal'"
    if entity_type not in ("character", "region"):
        return "ERROR: entity_type must be 'character' or 'region'"

    db = require_db()
    try:
        cur = db.execute(
            "DELETE FROM entry_entities WHERE source = ? AND source_id = ? AND entity_type = ? AND entity_id = ?",
            (source, source_id, entity_type, entity_id),
        )
        db.commit()
        if cur.rowcount == 0:
            return "NO_CHANGE: tag not found"
        return "ENTRY_UNTAGGED"
    finally:
        db.close()


@mcp.tool()
def npc_combat_turn(session_id: int, npc_id: int | str) -> str:
    """Execute a full NPC combat turn: decision + movement + action + advance.

    Asks the NPC agent what to do (with combat context: positions, relative
    health, available actions), then executes the intent mechanically:
    move (if chosen) → resolve action (if chosen) → advance turn.

    The NPC returns structured intent (action, target, movement, narration).
    Narrative-only turns (null intent) still tick modifiers and advance
    initiative.

    npc_id: numeric ID or NPC name (case-insensitive).
    """
    from lorekit.db import LoreKitError, require_db

    db = require_db()
    try:
        npc_id = _resolve_character(db, npc_id, session_id)

        # Load combat config and system path
        combat_cfg = _load_combat_cfg(db, session_id)
        system_path = _resolve_system_path_for_session(db, session_id)
        if not system_path:
            return "ERROR: No rules_system set for this session."

        from lorekit.npc.combat import build_combat_context

        combat_context = build_combat_context(db, npc_id, session_id, combat_cfg)

        # Build NPC prompt with combat context as invocation message
        result = _build_npc_prompt(db, npc_id, session_id, gm_message=combat_context)
        if not result:
            return f"ERROR: NPC #{npc_id} not found in session #{session_id}"
        system_prompt, model, npc_name = result
    except LoreKitError as e:
        return f"ERROR: {e}"
    finally:
        db.close()

    # Call NPC subprocess for combat decision — no MCP tools
    project_root = _project_root()

    cmd = [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--no-session-persistence",
        "--permission-mode",
        "bypassPermissions",
        "--tools",
        "",
        "--disable-slash-commands",
        "--model",
        model,
        "--system-prompt",
        system_prompt,
        combat_context,
    ]

    _npc_log(f"[COMBAT] → {npc_name}: combat turn")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            return f"ERROR: NPC process failed: {stderr or 'unknown error'}"

        response_text, _ = _parse_npc_stream(proc.stdout, npc_name)
    except subprocess.TimeoutExpired:
        return "ERROR: NPC response timed out"
    except FileNotFoundError:
        return "ERROR: 'claude' CLI not found."

    # Parse structured intent from NPC response
    from cruncher.system_pack import load_system_pack
    from lorekit.npc.combat import execute_combat_turn, parse_combat_intent

    db3 = require_db()
    try:
        pack = load_system_pack(system_path)
        intent_schema = pack.intent or None
    finally:
        db3.close()

    intent = parse_combat_intent(response_text, schema=intent_schema)

    _npc_log(f"[COMBAT] ← {npc_name}: {json.dumps(intent, default=str)}")

    # Build output
    lines = [f"NPC TURN: {npc_name}"]

    if intent.get("narration"):
        lines.append(f'DECISION: "{intent["narration"]}"')

    if not intent["action"] and not intent["move_to"]:
        lines.append("ACTION: None (narrative only)")

    # Execute mechanical part
    db2 = require_db()
    try:
        mech_lines = execute_combat_turn(
            db2,
            session_id,
            npc_id,
            intent,
            combat_cfg,
            system_path,
        )
        lines.extend(mech_lines)
    except LoreKitError as e:
        lines.append(f"ERROR: {e}")
    finally:
        db2.close()

    return "\n".join(lines)
