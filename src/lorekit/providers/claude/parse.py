"""Parse Claude CLI stream-json JSONL output into StreamChunks."""

from __future__ import annotations

import json
import re

from lorekit.providers.base import StreamChunk

_NPC_TOOLS_RE = re.compile(r"^\[NPC_TOOLS:([^:]+):([^\]]+)\]")


def parse_jsonl_line(line: str) -> StreamChunk | None:
    """Parse one JSONL line from --output-format stream-json."""
    line = line.strip()
    if not line:
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None

    if msg.get("type") == "stream_event":
        return _parse_stream_event(msg.get("event") or {})

    if msg.get("type") == "result":
        if msg.get("is_error"):
            errors = "; ".join(msg.get("errors", [])) or msg.get("result", "Unknown error")
            return StreamChunk(type="error", content=errors)
        return None

    if msg.get("type") == "system" and msg.get("subtype") == "init":
        return StreamChunk(type="system", content=msg.get("session_id", ""))

    return _parse_tool_result_message(msg)


def _parse_stream_event(evt: dict) -> StreamChunk | None:
    etype = evt.get("type")
    if etype == "content_block_start":
        block = evt.get("content_block", {})
        if block.get("type") == "tool_use":
            return StreamChunk(type="tool_use", content=block.get("name", ""))
    elif etype == "content_block_delta":
        delta = evt.get("delta", {})
        if delta.get("type") == "text_delta" and delta.get("text"):
            return StreamChunk(type="text", content=delta["text"])
    return None


def _parse_tool_result_message(msg: dict) -> StreamChunk | None:
    content = msg.get("content") or (msg.get("message") or {}).get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if block.get("type") != "tool_result":
            continue
        text = _extract_tool_text(block)
        if block.get("is_error") or text.startswith("ERROR:"):
            return StreamChunk(type="error", content=text)
        m = _NPC_TOOLS_RE.match(text)
        if m:
            return StreamChunk(type="npc_tool_use", content=f"{m.group(1)}:{m.group(2)}")
    return None


def _extract_tool_text(block: dict) -> str:
    raw = block.get("content", "")
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, list):
        text = "".join(c.get("text", "") for c in raw)
    else:
        text = json.dumps(raw)
    try:
        parsed = json.loads(text)
        if isinstance(parsed.get("result"), str):
            return parsed["result"]
    except (json.JSONDecodeError, TypeError):
        pass
    return text


def is_result_line(line: str) -> bool:
    """True if this JSONL line is a result message (end of turn)."""
    try:
        return json.loads(line.strip()).get("type") == "result"
    except (json.JSONDecodeError, AttributeError):
        return False


def collect_text(raw_output: str) -> str:
    """Extract all text content from stream-json output."""
    parts = []
    result_text = ""
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Streaming deltas
        chunk = parse_jsonl_line(line)
        if chunk and chunk.type == "text":
            parts.append(chunk.content)

        # Complete assistant messages (non-streaming)
        if msg.get("type") == "assistant":
            for block in (msg.get("message") or {}).get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])

        # Result fallback
        if msg.get("type") == "result" and msg.get("result") and not parts:
            result_text = msg["result"]

    return "".join(parts) or result_text
