"""Tests for provider loading."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from lorekit.providers import load_provider
from lorekit.providers.base import AgentProcess, AgentProvider, StreamChunk

# -- Protocol conformance --


class _MockProcess:
    async def send(self, message: str) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="text", content="hi")

    def stop(self) -> None:
        pass

    @property
    def alive(self) -> bool:
        return True


class _MockProvider:
    def spawn_persistent(self, system_prompt: str, mcp_config: Path, model: str) -> AgentProcess:
        return _MockProcess()

    def spawn_ephemeral(self, system_prompt: str, model: str) -> AgentProcess:
        return _MockProcess()

    def run_ephemeral_sync(self, system_prompt: str, model: str, message: str) -> str:
        return "ok"


def test_mock_process_satisfies_protocol():
    assert isinstance(_MockProcess(), AgentProcess)


def test_mock_provider_satisfies_protocol():
    assert isinstance(_MockProvider(), AgentProvider)


# -- Loading --


def test_load_provider_unknown():
    with pytest.raises(ValueError, match="Unknown provider 'nonexistent'"):
        load_provider("nonexistent")


def test_load_provider_claude():
    provider = load_provider("claude")
    assert isinstance(provider, AgentProvider)
