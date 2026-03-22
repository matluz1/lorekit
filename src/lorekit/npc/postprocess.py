"""npc_postprocess.py -- Parse NPC response metadata and auto-store memories/state."""

import json
import re

import lorekit.npc.memory as npc_memory


def parse_npc_metadata(text):
    """Extract [MEMORIES] and [STATE_CHANGES] blocks from NPC response text.

    Returns (narrative, memories, state_changes) where:
      - narrative: text with metadata blocks stripped
      - memories: list of dicts with keys: content, importance, type, entities
      - state_changes: dict of field -> value (relationship.X uses dot notation)
    """
    memories = []
    state_changes = {}

    # Extract [MEMORIES] block
    mem_pattern = re.compile(r"\[MEMORIES\]\s*\n(.*?)(?=\n\[[A-Z_]+\]|\Z)", re.DOTALL)
    mem_match = mem_pattern.search(text)
    if mem_match:
        for line in mem_match.group(1).strip().splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            parsed = _parse_memory_line(line[2:])
            if parsed:
                memories.append(parsed)

    # Extract [STATE_CHANGES] block
    state_pattern = re.compile(r"\[STATE_CHANGES\]\s*\n(.*?)(?=\n\[[A-Z_]+\]|\Z)", re.DOTALL)
    state_match = state_pattern.search(text)
    if state_match:
        for line in state_match.group(1).strip().splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            parsed = _parse_state_line(line[2:])
            if parsed:
                state_changes[parsed[0]] = parsed[1]

    # Strip metadata blocks from narrative
    narrative = text
    for pattern in (mem_pattern, state_pattern):
        # Remove the header + block content
        narrative = re.sub(
            r"\n?\[(?:MEMORIES|STATE_CHANGES)\]\s*\n.*?(?=\n\[[A-Z_]+\]|\Z)",
            "",
            narrative,
            flags=re.DOTALL,
        )
    narrative = narrative.strip()

    return narrative, memories, state_changes


def _parse_memory_line(line):
    """Parse a memory line: content: "..." | importance: 0.7 | type: experience | entities: ["x"]"""
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

        importance = 0.5
        if "importance" in parts:
            try:
                importance = float(parts["importance"])
                importance = max(0.0, min(1.0, importance))
            except ValueError:
                pass

        mem_type = parts.get("type", "experience").strip()
        if mem_type not in npc_memory.VALID_MEMORY_TYPES:
            mem_type = "experience"

        entities = []
        if "entities" in parts:
            try:
                entities = json.loads(parts["entities"])
                if not isinstance(entities, list):
                    entities = []
            except (json.JSONDecodeError, ValueError):
                pass

        return {
            "content": content,
            "importance": importance,
            "type": mem_type,
            "entities": entities,
        }
    except Exception:
        return None


def _parse_state_line(line):
    """Parse a state change line: key: "value" """
    try:
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not key or not val:
            return None
        return (key, val)
    except Exception:
        return None


def process_npc_response(db, session_id, npc_id, full_text, npc_name, narrative_time):
    """Post-process an NPC response: extract and store memories/state, return clean narrative.

    Args:
        db: database connection
        session_id: current session ID
        npc_id: NPC character ID
        full_text: raw NPC response text (may contain metadata blocks)
        npc_name: NPC display name
        narrative_time: in-game time string

    Returns:
        Clean narrative text with metadata blocks stripped.
    """
    narrative, memories, state_changes = parse_npc_metadata(full_text)

    # Store parsed memories
    for mem in memories:
        try:
            npc_memory.add_memory(
                db,
                session_id,
                npc_id,
                content=mem["content"],
                importance=mem["importance"],
                memory_type=mem["type"],
                entities=mem["entities"],
                narrative_time=narrative_time,
            )
        except Exception:
            pass  # tolerant: skip failures silently

    # Apply state changes
    if state_changes:
        _apply_state_changes(db, session_id, npc_id, state_changes)

    # Always store an interaction summary as safety net
    summary_content = f"[{npc_name} interaction] {narrative[:150]}"
    try:
        npc_memory.add_memory(
            db,
            session_id,
            npc_id,
            content=summary_content,
            importance=0.7,
            memory_type="experience",
            entities=[],
            narrative_time=narrative_time,
        )
    except Exception:
        pass

    return narrative


def _apply_state_changes(db, session_id, npc_id, state_changes):
    """Apply state changes to npc_core, handling relationship.X dot notation."""
    direct_fields = {}
    relationship_updates = {}

    for key, value in state_changes.items():
        if key.startswith("relationship."):
            rel_name = key[len("relationship.") :]
            relationship_updates[rel_name] = value
        elif key in ("self_concept", "current_goals", "emotional_state", "behavioral_patterns"):
            direct_fields[key] = value
        elif key == "emotional_state":
            direct_fields["emotional_state"] = value

    # Merge relationship updates into existing relationships JSON
    if relationship_updates:
        existing_core = npc_memory.get_core(db, session_id, npc_id)
        existing_rels = {}
        if existing_core and existing_core.get("relationships"):
            try:
                existing_rels = json.loads(existing_core["relationships"])
                if not isinstance(existing_rels, dict):
                    existing_rels = {}
            except (json.JSONDecodeError, ValueError):
                existing_rels = {}
        existing_rels.update(relationship_updates)
        direct_fields["relationships"] = json.dumps(existing_rels, ensure_ascii=False)

    if direct_fields:
        try:
            npc_memory.set_core(db, session_id, npc_id, **direct_fields)
        except Exception:
            pass
