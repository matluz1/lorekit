"""Tests for the GameSession orchestrator."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lorekit.orchestrator import GameSession, _transform_events
from lorekit.providers.base import GameEvent, StreamChunk

# -- Event transformation --


@pytest.mark.asyncio
async def test_transform_narration_default():
    """Default mode: only narration (accumulated), error, system."""
    chunks = [
        StreamChunk(type="text", content="The "),
        StreamChunk(type="text", content="goblin attacks."),
    ]

    async def mock_stream():
        for c in chunks:
            yield c

    events = [e async for e in _transform_events(mock_stream(), verbose=False)]
    assert len(events) == 1
    assert events[0] == GameEvent(type="narration", content="The goblin attacks.")


@pytest.mark.asyncio
async def test_transform_verbose_includes_deltas():
    """Verbose mode: includes narration_delta and tool_activity."""
    chunks = [
        StreamChunk(type="tool_use", content="roll_dice"),
        StreamChunk(type="text", content="Hit!"),
    ]

    async def mock_stream():
        for c in chunks:
            yield c

    events = [e async for e in _transform_events(mock_stream(), verbose=True)]
    types = [e.type for e in events]
    assert "tool_activity" in types
    assert "narration_delta" in types
    assert "narration" in types


@pytest.mark.asyncio
async def test_transform_error_always_emitted():
    chunks = [StreamChunk(type="error", content="something broke")]

    async def mock_stream():
        for c in chunks:
            yield c

    events = [e async for e in _transform_events(mock_stream(), verbose=False)]
    assert len(events) == 1
    assert events[0].type == "error"


# -- GameSession init --


def test_session_init_defaults(tmp_path):
    with patch("lorekit.orchestrator.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(provider="claude", model="sonnet", port=8765)
        session = GameSession(campaign_dir=tmp_path)
    assert session._provider_name == "claude"
    assert session._model == "sonnet"


def test_session_init_overrides_config(tmp_path):
    with patch("lorekit.orchestrator.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(provider="claude", model="sonnet", port=8765)
        session = GameSession(campaign_dir=tmp_path, provider="codex", model="opus")
    assert session._provider_name == "codex"
    assert session._model == "opus"


def test_session_init_no_provider_raises(tmp_path):
    with patch("lorekit.orchestrator.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(provider=None, model="sonnet", port=8765)
        with pytest.raises(ValueError, match="No provider configured"):
            GameSession(campaign_dir=tmp_path)


def test_session_init_no_model_raises(tmp_path):
    with patch("lorekit.orchestrator.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(provider="claude", model=None, port=8765)
        with pytest.raises(ValueError, match="No model configured"):
            GameSession(campaign_dir=tmp_path)
