"""Provider protocol types for LoreKit agent integration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class StreamChunk:
    """A single piece of output from an agent process."""

    type: str  # "text", "tool_use", "tool_result", "npc_tool_use", "error", "system"
    content: str


@dataclass(slots=True)
class GameEvent:
    """A curated event emitted by the orchestrator."""

    type: str  # "narration", "narration_delta", "tool_activity", "npc_activity", "error", "system"
    content: str


@runtime_checkable
class AgentProcess(Protocol):
    """A running agent process that accepts messages and streams responses."""

    async def send(self, message: str) -> AsyncIterator[StreamChunk]: ...

    def stop(self) -> None: ...

    @property
    def alive(self) -> bool: ...


@runtime_checkable
class AgentProvider(Protocol):
    """Factory for agent processes — one implementation per CLI tool."""

    def spawn_persistent(self, system_prompt: str, mcp_config: Path, model: str) -> AgentProcess: ...

    def spawn_ephemeral(self, system_prompt: str, model: str) -> AgentProcess: ...

    def run_ephemeral_sync(self, system_prompt: str, model: str, message: str) -> str:
        """Blocking one-shot call. Used by sync NPC code (reactions, reflections)."""
        ...
