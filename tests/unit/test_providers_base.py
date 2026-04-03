"""Tests for provider protocol types."""

from lorekit.providers.base import GameEvent, StreamChunk


def test_stream_chunk_construction():
    chunk = StreamChunk(type="text", content="hello")
    assert chunk.type == "text"
    assert chunk.content == "hello"


def test_game_event_construction():
    event = GameEvent(type="narration", content="The goblin attacks.")
    assert event.type == "narration"
    assert event.content == "The goblin attacks."


def test_stream_chunk_equality():
    a = StreamChunk(type="text", content="x")
    b = StreamChunk(type="text", content="x")
    assert a == b


def test_game_event_equality():
    a = GameEvent(type="error", content="fail")
    b = GameEvent(type="error", content="fail")
    assert a == b
