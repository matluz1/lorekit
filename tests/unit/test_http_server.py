"""Tests for the HTTP + SSE server."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lorekit.providers.base import GameEvent


@pytest.fixture
def mock_session():
    session = MagicMock()

    async def fake_send(msg, verbose=False):
        yield GameEvent(type="narration", content="The goblin attacks.")

    session.send = fake_send
    session.command = AsyncMock(return_value="Game saved.")
    return session


def test_message_endpoint_returns_sse(mock_session):
    """POST /message returns SSE stream."""
    from starlette.testclient import TestClient

    with patch("lorekit.http_server._session", mock_session):
        from lorekit.http_server import app

        client = TestClient(app)
        response = client.post("/message", json={"text": "I attack the goblin"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    lines = response.text.strip().split("\n")
    data_lines = [l for l in lines if l.startswith("data: ")]
    assert len(data_lines) >= 1
    event = json.loads(data_lines[0].removeprefix("data: "))
    assert event["type"] == "narration"


def test_command_endpoint_returns_json(mock_session):
    """POST /command returns JSON."""
    from starlette.testclient import TestClient

    with patch("lorekit.http_server._session", mock_session):
        from lorekit.http_server import app

        client = TestClient(app)
        response = client.post("/command", json={"cmd": "manual_save", "name": "test"})

    assert response.status_code == 200
    data = response.json()
    assert data["result"] == "Game saved."


def test_message_missing_text(mock_session):
    """POST /message without text returns 400."""
    from starlette.testclient import TestClient

    with patch("lorekit.http_server._session", mock_session):
        from lorekit.http_server import app

        client = TestClient(app)
        response = client.post("/message", json={})

    assert response.status_code == 400
