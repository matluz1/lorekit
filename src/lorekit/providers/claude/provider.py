"""Claude CLI provider for LoreKit — spawns claude subprocesses."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

from lorekit.providers.base import AgentProcess, StreamChunk
from lorekit.providers.claude.parse import collect_text, is_result_line, parse_jsonl_line

_EPHEMERAL_TIMEOUT = 120


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
            chunk = parse_jsonl_line(line)

            # Capture session ID from init message — don't yield it
            if chunk and chunk.type == "system" and not self._session_id:
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
