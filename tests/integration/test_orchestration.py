"""Integration test verifying the orchestration API matches the spec example."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lorekit.orchestrator import GameSession
from lorekit.providers.base import AgentProvider, GameEvent, StreamChunk


class FakeProcess:
    """Test double that simulates a GM agent."""

    def __init__(self):
        self._alive = True

    async def send(self, message):
        yield StreamChunk(type="tool_use", content="rules_resolve")
        yield StreamChunk(type="text", content="The goblin ")
        yield StreamChunk(type="text", content="snarls and attacks!")

    def stop(self):
        self._alive = False

    @property
    def alive(self):
        return self._alive


class FakeProvider:
    def spawn_persistent(self, system_prompt, mcp_config, model):
        return FakeProcess()

    def spawn_ephemeral(self, system_prompt, model):
        return FakeProcess()

    def run_ephemeral_sync(self, system_prompt, model, message):
        return "YES"


@pytest.mark.asyncio
async def test_game_session_send_produces_events(tmp_path):
    """Matches the spec usage example: send message, get narration events."""
    with (
        patch("lorekit.orchestrator.load_config") as mock_cfg,
        patch("lorekit.orchestrator.load_provider", return_value=FakeProvider()),
        patch("lorekit.orchestrator._load_guidelines", return_value="You are a GM."),
        patch("subprocess.Popen"),
        patch.object(GameSession, "_wait_for_mcp_server"),
    ):
        mock_cfg.return_value = MagicMock(provider="fake", model="test", port=8765, campaign_dir=None, debug=False)
        session = GameSession(campaign_dir=tmp_path, provider="fake", model="test")
        await session.start()

        events = []
        async for event in session.send("I attack the goblin"):
            events.append(event)

        await session.stop()

    types = [e.type for e in events]
    assert "narration" in types
    narration = next(e for e in events if e.type == "narration")
    assert "goblin" in narration.content


@pytest.mark.asyncio
async def test_game_session_verbose_includes_tool_activity(tmp_path):
    """Verbose mode includes tool_activity and narration_delta events."""
    with (
        patch("lorekit.orchestrator.load_config") as mock_cfg,
        patch("lorekit.orchestrator.load_provider", return_value=FakeProvider()),
        patch("lorekit.orchestrator._load_guidelines", return_value="You are a GM."),
        patch("subprocess.Popen"),
        patch.object(GameSession, "_wait_for_mcp_server"),
    ):
        mock_cfg.return_value = MagicMock(provider="fake", model="test", port=8765, campaign_dir=None, debug=False)
        session = GameSession(campaign_dir=tmp_path, provider="fake", model="test")
        await session.start()

        events = []
        async for event in session.send("I attack the goblin", verbose=True):
            events.append(event)

        await session.stop()

    types = [e.type for e in events]
    assert "tool_activity" in types
    assert "narration_delta" in types
    assert "narration" in types
