"""npc_reflect.py -- NPC async reflection: triggers, generation, parsing, pruning."""

import json
import re
import subprocess
from datetime import datetime, timezone

import lorekit.npc.memory as npc_memory
from lorekit.db import LoreKitError
from lorekit.npc.config import PRUNE_IMPORTANCE, PRUNE_RECENCY, RECENCY_DECAY, REFLECT_TIMEOUT, REFLECTION_THRESHOLD
from lorekit.npc.memory import MEMORY_SELECT, memory_row_to_dict


def check_trigger(db, session_id, npc_id, threshold=REFLECTION_THRESHOLD):
    """Return True if unprocessed memories' importance sum >= threshold."""
    unprocessed = get_unprocessed_memories(db, session_id, npc_id)
    total = sum(float(m["importance"]) for m in unprocessed)
    return total >= threshold


def get_unprocessed_memories(db, session_id, npc_id):
    """Memories created after the last reflection (or all if none exists).

    Excludes memory_type='reflection' from candidates.
    Ordered by created_at ASC.
    """
    # Find the last reflection time
    row = db.execute(
        "SELECT MAX(created_at) FROM npc_memories WHERE npc_id = ? AND session_id = ? AND memory_type = 'reflection'",
        (npc_id, session_id),
    ).fetchone()
    last_reflection_at = row[0] if row else None

    if last_reflection_at:
        rows = db.execute(
            f"SELECT {MEMORY_SELECT} FROM npc_memories WHERE npc_id = ? AND session_id = ? "
            "AND memory_type != 'reflection' AND created_at > ? "
            "ORDER BY created_at ASC",
            (npc_id, session_id, last_reflection_at),
        ).fetchall()
    else:
        rows = db.execute(
            f"SELECT {MEMORY_SELECT} FROM npc_memories WHERE npc_id = ? AND session_id = ? "
            "AND memory_type != 'reflection' "
            "ORDER BY created_at ASC",
            (npc_id, session_id),
        ).fetchall()

    return [memory_row_to_dict(r) for r in rows]


def generate_reflection(db, session_id, npc_id, context_hint="", narrative_time=""):
    """Generate reflections from accumulated memories via LLM.

    narrative_time: current in-game time, stored on reflection memories and
    used for pruning recency. If empty, looks up session_meta.

    Returns {"reflections_stored": N, "rules_added": M, "npc_name": name, "pruned": P}.
    """
    # Resolve narrative_time from session_meta if not provided
    if not narrative_time:
        meta_row = db.execute(
            "SELECT value FROM session_meta WHERE session_id = ? AND key = 'narrative_time'",
            (session_id,),
        ).fetchone()
        narrative_time = meta_row[0] if meta_row else ""

    # 1. Load NPC core identity
    core = npc_memory.get_core(db, session_id, npc_id)

    # 2. Load NPC name and gender
    char_row = db.execute("SELECT name, gender FROM characters WHERE id = ?", (npc_id,)).fetchone()
    if not char_row:
        raise LoreKitError(f"Character #{npc_id} not found")
    npc_name = char_row[0]
    npc_gender = char_row[1] or ""

    # 3. Load unprocessed memories
    memories = get_unprocessed_memories(db, session_id, npc_id)

    # 4. Early return if nothing to reflect on
    if not memories:
        return {"reflections_stored": 0, "rules_added": 0, "npc_name": npc_name, "pruned": 0}

    # 5. Build reflection prompt
    prompt = _build_reflection_prompt(npc_name, core, memories, context_hint, gender=npc_gender)

    # 6. Build memory_id_map (1-indexed → actual memory ID)
    memory_id_map = {i + 1: m["id"] for i, m in enumerate(memories)}

    # 7. Call LLM
    llm_output = _call_llm(prompt)

    # 8. Parse output
    parsed = parse_reflection_output(llm_output, memory_id_map)

    # 9. Store reflections as memories
    source_memory_ids = [m["id"] for m in memories]
    reflections_stored = 0
    for ref in parsed["reflections"]:
        try:
            npc_memory.add_memory(
                db,
                session_id,
                npc_id,
                content=ref["content"],
                importance=ref["importance"],
                memory_type="reflection",
                entities=[],
                narrative_time=narrative_time,
                source_ids=ref.get("source_ids", source_memory_ids),
            )
            reflections_stored += 1
        except Exception:
            pass

    # 10. Merge behavioral rules into npc_core
    rules_added = 0
    if parsed["behavioral_rules"]:
        existing_patterns = ""
        if core and core.get("behavioral_patterns"):
            existing_patterns = core["behavioral_patterns"]

        new_rules = parsed["behavioral_rules"]
        if existing_patterns:
            merged = existing_patterns.rstrip()
            for rule in new_rules:
                merged += f"\n- {rule}"
        else:
            merged = "\n".join(f"- {rule}" for rule in new_rules)

        npc_memory.set_core(db, session_id, npc_id, behavioral_patterns=merged)
        rules_added = len(new_rules)

    # 11. Apply identity updates if present
    if parsed["identity_updates"]:
        update_fields = {}
        for field in ("self_concept", "current_goals", "emotional_state"):
            if field in parsed["identity_updates"]:
                update_fields[field] = parsed["identity_updates"][field]
        if update_fields:
            npc_memory.set_core(db, session_id, npc_id, **update_fields)

    # 12. Prune old memories
    pruned = prune_memories(db, session_id, npc_id, narrative_now=narrative_time)

    return {
        "reflections_stored": reflections_stored,
        "rules_added": rules_added,
        "npc_name": npc_name,
        "pruned": pruned,
    }


def reflect_all(db, session_id, threshold=REFLECTION_THRESHOLD, context_hint=""):
    """Reflect on all NPCs in a session that meet the trigger threshold.

    Returns a summary string.
    """
    npcs = db.execute(
        "SELECT id, name FROM characters WHERE session_id = ? AND type = 'npc'",
        (session_id,),
    ).fetchall()

    reflected = []
    skipped = 0

    for npc_id, npc_name in npcs:
        if check_trigger(db, session_id, npc_id, threshold):
            result = generate_reflection(db, session_id, npc_id, context_hint)
            reflected.append(f"{result['npc_name']}: {result['reflections_stored']} insights")
        else:
            skipped += 1

    if not reflected and skipped == 0:
        return "REFLECTIONS: No NPCs in session."

    parts = []
    if reflected:
        parts.append(f"Reflected on {len(reflected)} NPCs ({', '.join(reflected)}).")
    if skipped:
        parts.append(f"Skipped {skipped} NPCs below threshold.")

    return "REFLECTIONS: " + " ".join(parts)


def prune_memories(db, session_id, npc_id, narrative_now=""):
    """Remove very old, unimportant, never-accessed memories.

    Criteria: recency_score < 0.01 AND importance < 0.3 AND access_count == 0.
    recency_score = 0.995 ^ narrative_hours_since_created.
    0.995^h < 0.01 → h > ~920 narrative hours (~38 in-game days).

    Uses narrative_now for recency calculation. Falls back to wall-clock
    if narrative_now is empty or unparseable.

    Returns count of pruned memories.
    """
    from lorekit.npc.memory import narrative_hours_since, parse_time

    now_dt = parse_time(narrative_now)
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    candidates = db.execute(
        "SELECT id, importance, access_count, narrative_time FROM npc_memories "
        f"WHERE npc_id = ? AND session_id = ? AND importance < {PRUNE_IMPORTANCE} AND access_count = 0",
        (npc_id, session_id),
    ).fetchall()

    to_prune = []
    for row in candidates:
        mem_id, importance, access_count, nar_time = row
        if not nar_time:
            continue

        hours = narrative_hours_since(nar_time, now_dt)
        recency = RECENCY_DECAY**hours
        if recency < PRUNE_RECENCY:
            to_prune.append(mem_id)

    if not to_prune:
        return 0

    placeholders = ",".join("?" * len(to_prune))
    db.execute(f"DELETE FROM npc_memories WHERE id IN ({placeholders})", to_prune)

    # Also delete embeddings if the table exists
    try:
        db.execute(f"DELETE FROM npc_memory_embeddings WHERE memory_id IN ({placeholders})", to_prune)
    except Exception:
        pass

    db.commit()
    return len(to_prune)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _build_reflection_prompt(npc_name, core, memories, context_hint="", gender=""):
    """Build the reflection prompt for the LLM."""
    # Identity section
    identity_parts = []
    if core:
        if core.get("self_concept"):
            identity_parts.append(f"Self-concept: {core['self_concept']}")
        if core.get("current_goals"):
            identity_parts.append(f"Goals: {core['current_goals']}")
        if core.get("emotional_state"):
            identity_parts.append(f"Emotional state: {core['emotional_state']}")
        if core.get("relationships"):
            identity_parts.append(f"Relationships: {core['relationships']}")
        if core.get("behavioral_patterns"):
            identity_parts.append(f"Behavioral patterns: {core['behavioral_patterns']}")
    identity_text = "\n".join(identity_parts) if identity_parts else "(No established identity yet)"

    # Memory list
    mem_lines = []
    for i, m in enumerate(memories, 1):
        mem_lines.append(f"{i}. [{m['memory_type']}] (importance: {m['importance']}) {m['content']}")
    memories_text = "\n".join(mem_lines)

    # Context hint
    context_line = f"\nNote: {context_hint}\n" if context_hint else ""

    gender_note = f" (gender: {gender})" if gender else ""
    return f"""You are analyzing the recent experiences of {npc_name}{gender_note}, a character in a tabletop RPG.

## {npc_name}'s Identity
{identity_text}

## Recent Experiences (since last reflection)
{memories_text}
{context_line}
Based on these experiences, generate:

1. **Reflections** (2-5): Higher-order insights, conclusions, or realizations that {npc_name} would form. These are beliefs, not facts — they can be wrong or biased.

2. **Behavioral rules** (0-3): Concrete "when X, do Y" directives that {npc_name} has developed from these experiences.

3. **Identity updates** (optional): If these experiences significantly changed {npc_name}'s self-concept, goals, or emotional state, note the updates.

Format your response EXACTLY as:

[REFLECTIONS]
- content: "insight text" | importance: 0.8-1.0 | sources: [1, 3, 5]
- content: "another insight" | importance: 0.9 | sources: [2, 4]

[BEHAVIORAL_RULES]
- "When someone mentions the guild, become defensive and evasive"
- "When the party asks for help, give them the benefit of the doubt"

[IDENTITY_UPDATES]
- self_concept: "updated self-concept text"
- current_goals: "updated goals"
- emotional_state: "updated emotional state"

Omit sections if empty (e.g., no identity updates needed). Source numbers reference the memory list above."""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _call_llm(prompt):
    """Call LLM via provider (if configured) or claude -p subprocess."""
    from lorekit._mcp_app import get_default_model, get_provider_name

    provider_name = get_provider_name()
    if provider_name:
        from lorekit.providers import load_provider

        provider = load_provider(provider_name)
        model = get_default_model() or "sonnet"
        return provider.run_ephemeral_sync("", model, prompt)

    from lorekit.rules import project_root as _pr

    project_root = _pr()

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
        "sonnet",
    ]
    cmd.append(prompt)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=REFLECT_TIMEOUT,
        cwd=project_root,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise LoreKitError(f"Reflection LLM process failed: {stderr or 'unknown error'}")

    # Parse stream-json output — extract text from assistant messages
    return _parse_stream_json(proc.stdout)


def _parse_stream_json(raw_output):
    """Extract text content from stream-json output."""
    text_parts = []
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "assistant" and "message" in obj:
                for block in obj["message"].get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
            elif obj.get("type") == "result" and "result" in obj:
                text_parts.append(obj["result"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    return "\n".join(text_parts) if text_parts else raw_output


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_reflection_output(text, memory_id_map):
    """Parse LLM reflection output into structured data.

    memory_id_map: {1-indexed number -> actual memory ID} for resolving source references.
    Returns {"reflections": [...], "behavioral_rules": [...], "identity_updates": {...}}.
    """
    reflections = []
    behavioral_rules = []
    identity_updates = {}

    # Parse [REFLECTIONS] block
    ref_pattern = re.compile(r"\[REFLECTIONS\]\s*\n(.*?)(?=\n\[[A-Z_]+\]|\Z)", re.DOTALL)
    ref_match = ref_pattern.search(text)
    if ref_match:
        for line in ref_match.group(1).strip().splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            parsed = _parse_reflection_line(line[2:], memory_id_map)
            if parsed:
                reflections.append(parsed)

    # Parse [BEHAVIORAL_RULES] block
    rules_pattern = re.compile(r"\[BEHAVIORAL_RULES\]\s*\n(.*?)(?=\n\[[A-Z_]+\]|\Z)", re.DOTALL)
    rules_match = rules_pattern.search(text)
    if rules_match:
        for line in rules_match.group(1).strip().splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            rule = line[2:].strip().strip('"').strip("'")
            if rule:
                behavioral_rules.append(rule)

    # Parse [IDENTITY_UPDATES] block
    id_pattern = re.compile(r"\[IDENTITY_UPDATES\]\s*\n(.*?)(?=\n\[[A-Z_]+\]|\Z)", re.DOTALL)
    id_match = id_pattern.search(text)
    if id_match:
        for line in id_match.group(1).strip().splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            key, _, val = line[2:].partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key in ("self_concept", "current_goals", "emotional_state"):
                identity_updates[key] = val

    return {
        "reflections": reflections,
        "behavioral_rules": behavioral_rules,
        "identity_updates": identity_updates,
    }


def _parse_reflection_line(line, memory_id_map):
    """Parse: content: "insight" | importance: 0.9 | sources: [1, 3]"""
    try:
        parts = {}
        for segment in line.split("|"):
            segment = segment.strip()
            if ":" not in segment:
                continue
            key, _, val = segment.partition(":")
            parts[key.strip()] = val.strip()

        content = parts.get("content", "").strip('"').strip("'")
        if not content:
            return None

        importance = 0.9
        if "importance" in parts:
            try:
                importance = float(parts["importance"])
                importance = max(0.0, min(1.0, importance))
            except ValueError:
                pass

        source_ids = []
        if "sources" in parts:
            try:
                source_nums = json.loads(parts["sources"])
                if isinstance(source_nums, list):
                    source_ids = [memory_id_map[n] for n in source_nums if n in memory_id_map]
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        return {
            "content": content,
            "importance": importance,
            "source_ids": source_ids if source_ids else list(memory_id_map.values()),
        }
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None
