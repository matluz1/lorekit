"""Tests for Claude stream-json JSONL parser."""

import json

from lorekit.providers.claude.parse import collect_text, is_result_line, parse_jsonl_line

# -- parse_jsonl_line --


def test_parse_empty_line():
    assert parse_jsonl_line("") is None
    assert parse_jsonl_line("  ") is None


def test_parse_invalid_json():
    assert parse_jsonl_line("not json") is None


def test_parse_text_delta():
    line = json.dumps(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "hello"},
            },
        }
    )
    chunk = parse_jsonl_line(line)
    assert chunk is not None
    assert chunk.type == "text"
    assert chunk.content == "hello"


def test_parse_tool_use_start():
    line = json.dumps(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "roll_dice"},
            },
        }
    )
    chunk = parse_jsonl_line(line)
    assert chunk is not None
    assert chunk.type == "tool_use"
    assert chunk.content == "roll_dice"


def test_parse_result_success():
    line = json.dumps({"type": "result", "is_error": False, "result": "done"})
    assert parse_jsonl_line(line) is None


def test_parse_result_error():
    line = json.dumps({"type": "result", "is_error": True, "result": "oops"})
    chunk = parse_jsonl_line(line)
    assert chunk is not None
    assert chunk.type == "error"


def test_parse_system_init():
    line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc123"})
    chunk = parse_jsonl_line(line)
    assert chunk is not None
    assert chunk.type == "system"
    assert chunk.content == "abc123"


def test_parse_unrecognized_event():
    line = json.dumps({"type": "stream_event", "event": {"type": "message_start"}})
    assert parse_jsonl_line(line) is None


# -- is_result_line --


def test_is_result_line_true():
    assert is_result_line(json.dumps({"type": "result"}))


def test_is_result_line_false():
    assert not is_result_line(json.dumps({"type": "stream_event"}))
    assert not is_result_line("bad json")


# -- collect_text --


def test_collect_text():
    lines = "\n".join(
        [
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "The "},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "goblin attacks."},
                    },
                }
            ),
            json.dumps({"type": "result", "is_error": False}),
        ]
    )
    assert collect_text(lines) == "The goblin attacks."
