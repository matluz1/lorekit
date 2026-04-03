"""GameSession — public Python API for LoreKit orchestration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from lorekit.config import load_config
from lorekit.providers import load_provider
from lorekit.providers.base import AgentProcess, GameEvent, StreamChunk


async def _transform_events(
    chunks: AsyncIterator[StreamChunk],
    verbose: bool = False,
) -> AsyncIterator[GameEvent]:
    """Transform raw StreamChunks into curated GameEvents."""
    text_parts: list[str] = []
    got_any = False

    async for chunk in chunks:
        got_any = True
        if chunk.type == "text":
            text_parts.append(chunk.content)
            if verbose:
                yield GameEvent(type="narration_delta", content=chunk.content)
        elif chunk.type == "tool_use":
            if verbose:
                yield GameEvent(type="tool_activity", content=chunk.content)
        elif chunk.type == "npc_tool_use":
            if verbose:
                yield GameEvent(type="npc_activity", content=chunk.content)
        elif chunk.type == "error":
            yield GameEvent(type="error", content=chunk.content)
        elif chunk.type == "system":
            yield GameEvent(type="system", content=chunk.content)

    # Emit accumulated narration at the end
    if text_parts:
        yield GameEvent(type="narration", content="".join(text_parts))
    elif not got_any:
        yield GameEvent(type="error", content="GM agent process terminated unexpectedly")


class GameSession:
    """Orchestrates a LoreKit game session."""

    def __init__(
        self,
        campaign_dir: Path,
        provider: str | None = None,
        model: str | None = None,
    ):
        cfg = load_config()
        self._campaign_dir = Path(campaign_dir)
        self._provider_name = provider or cfg.provider
        self._model = model or cfg.model

        if not self._provider_name:
            raise ValueError("No provider configured. Set [agent] provider in config.toml or pass provider=.")
        if not self._model:
            raise ValueError("No model configured. Set [agent] model in config.toml or pass model=.")

        self._mcp_proc: subprocess.Popen | None = None
        self._gm_process: AgentProcess | None = None

    async def start(self) -> None:
        """Start the MCP server and spawn the GM agent."""
        import asyncio

        self._mcp_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "lorekit.server",
                "--http",
                "--provider",
                self._provider_name,
                "--model",
                self._model,
                "--campaign-dir",
                str(self._campaign_dir),
            ],
            env={**os.environ, "LOREKIT_DB_DIR": str(self._campaign_dir)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Wait for MCP server to be ready on port 3847
        await self._wait_for_mcp_server()

        # Load guidelines for GM system prompt
        system_prompt = _load_guidelines()

        # Write temporary MCP config for the GM agent
        mcp_config = self._campaign_dir / ".mcp.json"
        mcp_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "lorekit": {
                            "url": "http://127.0.0.1:3847/mcp",
                        }
                    }
                }
            )
        )

        agent_provider = load_provider(self._provider_name)
        self._gm_process = agent_provider.spawn_persistent(
            system_prompt=system_prompt,
            mcp_config=mcp_config,
            model=self._model,
        )

    async def _wait_for_mcp_server(self, timeout: float = 30) -> None:
        """Wait for the MCP server to accept connections on port 3847."""
        import asyncio
        import socket

        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            # Check if process died
            if self._mcp_proc and self._mcp_proc.poll() is not None:
                stderr = self._mcp_proc.stderr.read().decode() if self._mcp_proc.stderr else ""
                raise RuntimeError(f"MCP server failed to start: {stderr.strip()}")
            try:
                with socket.create_connection(("127.0.0.1", 3847), timeout=1):
                    return
            except OSError:
                await asyncio.sleep(0.5)
        raise RuntimeError("MCP server did not start within 30 seconds")

    async def send(self, message: str, verbose: bool = False) -> AsyncIterator[GameEvent]:
        """Send a player message and stream back GameEvents."""
        if not self._gm_process or not self._gm_process.alive:
            yield GameEvent(type="error", content="GM process is not running.")
            return
        async for event in _transform_events(self._gm_process.send(message), verbose=verbose):
            yield event

    async def command(self, cmd: str, **kwargs) -> str:
        """Execute a direct MCP command (save, load, etc.) bypassing the GM agent."""
        import asyncio
        import urllib.request

        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": cmd, "arguments": kwargs},
                "id": 1,
            }
        ).encode()

        req = urllib.request.Request(
            "http://127.0.0.1:3847/mcp",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        loop = asyncio.get_running_loop()

        def _do_call():
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())

        data = await loop.run_in_executor(None, _do_call)
        if "error" in data:
            return f"ERROR: {data['error'].get('message', data['error'])}"
        content = data.get("result", {}).get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "")
        return json.dumps(data.get("result", ""))

    async def stop(self) -> None:
        """Shut down the GM agent and MCP server."""
        if self._gm_process:
            self._gm_process.stop()
            self._gm_process = None
        if self._mcp_proc and self._mcp_proc.poll() is None:
            self._mcp_proc.terminate()
            self._mcp_proc.wait(timeout=5)
            self._mcp_proc = None


def _load_guidelines() -> str:
    """Load GM guidelines from the project's guidelines/ directory."""
    from lorekit.rules import project_root

    guidelines_dir = os.path.join(project_root(), "guidelines")
    parts = []
    for name in ("SHARED_GUIDE.md", "GM_GUIDE.md"):
        path = os.path.join(guidelines_dir, name)
        if os.path.isfile(path):
            with open(path) as f:
                parts.append(f.read())
    return "\n\n".join(parts) if parts else "You are a tabletop RPG game master."
