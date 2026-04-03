"""Claude CLI provider for LoreKit — spawns claude subprocesses."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

from lorekit.providers.base import AgentProcess, StreamChunk
from lorekit.providers.claude.parse import collect_text, is_result_line, parse_jsonl_line

_EPHEMERAL_TIMEOUT = 120


_log_cfg = None
_log_path = None
_log_buffer: dict[str, list[str]] = {}  # tag → accumulated chunks
_log_block_type = ""  # current content block type


def _gm_log(line: str) -> None:
    """Log GM activity in human-readable format. Only writes when debug=true."""
    import json
    import os
    from datetime import datetime

    global _log_cfg, _log_path, _log_block_type
    if _log_cfg is None:
        from lorekit.config import load_config

        _log_cfg = load_config()
        if _log_cfg.debug:
            _log_path = os.path.join(str(_log_cfg.campaign_dir or "."), "lorekit.log")

    if not _log_path:
        return

    line = line.strip()
    if not line:
        return

    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return

    ts = datetime.now().strftime("%H:%M:%S.%f")[:12]

    if msg.get("type") == "stream_event":
        evt = msg.get("event", {})
        etype = evt.get("type")

        if etype == "content_block_start":
            block = evt.get("content_block", {})
            _log_block_type = block.get("type", "")
            if _log_block_type == "tool_use":
                _log_write(ts, "TOOL", block.get("name", ""))

        elif etype == "content_block_delta":
            delta = evt.get("delta", {})
            if delta.get("type") == "thinking_delta" and delta.get("thinking"):
                _log_buffer.setdefault("THINK", []).append(delta["thinking"])
            elif delta.get("type") == "input_json_delta" and delta.get("partial_json"):
                _log_buffer.setdefault("ARGS", []).append(delta["partial_json"])
            elif delta.get("type") == "text_delta" and delta.get("text"):
                _log_buffer.setdefault("TEXT", []).append(delta["text"])

        elif etype == "content_block_stop":
            _flush_log_buffer(ts)

    elif msg.get("type") == "user":
        content = (msg.get("message") or {}).get("content")
        if isinstance(content, str):
            _log_write(ts, "USER", content)
        elif isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_result":
                    text = block.get("content", "")
                    if isinstance(text, list):
                        text = "".join(c.get("text", "") for c in text)
                    _log_write(ts, "RESULT", str(text)[:500])


def _flush_log_buffer(ts: str) -> None:
    """Write buffered deltas as single log lines and clear the buffer."""
    for tag in ("THINK", "ARGS", "TEXT"):
        if tag in _log_buffer:
            _log_write(ts, tag, "".join(_log_buffer[tag]))
    _log_buffer.clear()


def _log_write(ts: str, tag: str, text: str) -> None:
    with open(_log_path, "a") as f:
        f.write(f"{ts} GM [{tag}] {text}\n")


def _base_args(model: str, system_prompt: str) -> list[str]:
    """CLI args shared between persistent and ephemeral modes."""
    return [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
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


class EphemeralProcess:
    """One-shot subprocess for NPC interactions."""

    def __init__(self, cmd: list[str], cwd: str | None = None):
        self._cmd = cmd
        self._cwd = cwd

    async def send(self, message: str) -> AsyncIterator[StreamChunk]:
        proc = await asyncio.create_subprocess_exec(
            *self._cmd,
            message,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            cwd=self._cwd,
        )
        async for raw_line in proc.stdout:
            line = raw_line.decode()
            chunk = parse_jsonl_line(line)
            if chunk:
                yield chunk
            if is_result_line(line):
                break
        await proc.wait()

    def stop(self) -> None:
        pass

    @property
    def alive(self) -> bool:
        return True


class PersistentProcess:
    """Long-lived subprocess for the GM agent, with stdin/stdout streaming."""

    def __init__(self, proc: subprocess.Popen):
        self._proc = proc
        self._session_id: str | None = None

    async def send(self, message: str) -> AsyncIterator[StreamChunk]:
        import json

        msg = json.dumps({"type": "user", "message": {"role": "user", "content": message}})
        self._proc.stdin.write((msg + "\n").encode())
        self._proc.stdin.flush()

        loop = asyncio.get_running_loop()
        while True:
            raw_line = await loop.run_in_executor(None, self._proc.stdout.readline)
            if not raw_line:
                break
            line = raw_line.decode()
            _gm_log(line)
            chunk = parse_jsonl_line(line)

            # Capture session ID from init messages — never yield them
            if chunk and chunk.type == "system":
                self._session_id = chunk.content
                continue

            if chunk:
                yield chunk
            if is_result_line(line):
                break

    def stop(self) -> None:
        if self._proc.poll() is None:
            self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)

    @property
    def alive(self) -> bool:
        return self._proc.poll() is None

    @property
    def session_id(self) -> str | None:
        return self._session_id


class ClaudeCLI:
    """AgentProvider implementation that spawns Claude CLI subprocesses."""

    def __init__(self, cwd: str | None = None):
        self._cwd = cwd

    def spawn_persistent(self, system_prompt: str, mcp_config: Path, model: str) -> AgentProcess:
        cmd = [
            *_base_args(model, system_prompt),
            "--input-format",
            "stream-json",
            "--include-partial-messages",
            "--mcp-config",
            str(mcp_config),
            "--strict-mcp-config",
            "--allowedTools",
            "mcp__lorekit__*",
            "--disallowedTools",
            "mcp__lorekit__client_active_session_id",
            "mcp__lorekit__client_unsaved_turn_count",
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._cwd,
        )
        return PersistentProcess(proc)

    def spawn_ephemeral(self, system_prompt: str, model: str) -> AgentProcess:
        cmd = [*_base_args(model, system_prompt), "--no-session-persistence"]
        return EphemeralProcess(cmd, cwd=self._cwd)

    def run_ephemeral_sync(self, system_prompt: str, model: str, message: str) -> str:
        """Blocking one-shot call — used by sync NPC code."""
        cmd = [*_base_args(model, system_prompt), "--no-session-persistence", message]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_EPHEMERAL_TIMEOUT,
            cwd=self._cwd,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "Claude process failed")
        return collect_text(proc.stdout)
