"""Tests for Claude CLI provider."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lorekit.providers.base import AgentProvider
from lorekit.providers.claude.provider import ClaudeCLI

# -- run_ephemeral_sync --


def test_run_ephemeral_sync_extracts_text():
    stream_output = "\n".join(
        [
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "YES"},
                    },
                }
            ),
            json.dumps({"type": "result", "is_error": False}),
        ]
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = stream_output
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        provider = ClaudeCLI()
        result = provider.run_ephemeral_sync("You are an NPC.", "sonnet", "Do you attack?")

    assert result == "YES"
    args = mock_run.call_args
    cmd = args[0][0]
    assert "claude" == cmd[0]
    assert "--no-session-persistence" in cmd
    assert "--model" in cmd


def test_run_ephemeral_sync_error_raises():
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stderr = "command not found"

    with patch("subprocess.run", return_value=mock_proc):
        provider = ClaudeCLI()
        with pytest.raises(RuntimeError, match="command not found"):
            provider.run_ephemeral_sync("sys", "sonnet", "msg")


def test_run_ephemeral_sync_timeout_raises():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 120)):
        provider = ClaudeCLI()
        with pytest.raises(subprocess.TimeoutExpired):
            provider.run_ephemeral_sync("sys", "sonnet", "msg")


# -- Protocol conformance --


def test_claude_cli_satisfies_provider_protocol():
    assert isinstance(ClaudeCLI(), AgentProvider)


# -- spawn_ephemeral --


@pytest.mark.asyncio
async def test_spawn_ephemeral_yields_chunks():
    stream_output = (
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "The goblin attacks."},
                },
            }
        )
        + "\n"
        + json.dumps({"type": "result", "is_error": False})
        + "\n"
    )

    mock_proc = MagicMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.__aiter__ = lambda self: _aiter_lines(stream_output)

    async def fake_wait():
        return 0

    mock_proc.wait = fake_wait
    mock_proc.returncode = 0

    async def fake_exec(*args, **kwargs):
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        provider = ClaudeCLI()
        process = provider.spawn_ephemeral("You are an NPC.", "sonnet")
        chunks = []
        async for chunk in process.send("Attack the hero"):
            chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0].type == "text"
    assert chunks[0].content == "The goblin attacks."


# -- Helpers --


async def _aiter_lines(text: str):
    for line in text.splitlines():
        yield line.encode() + b"\n"
