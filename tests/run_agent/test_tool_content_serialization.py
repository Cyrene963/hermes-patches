import json

from agent.conversation_loop import (
    _compact_historical_tool_message_content,
    _stringify_tool_message_content,
)


def test_stringify_structured_tool_content_for_chat_completions():
    messages = [
        {"role": "assistant", "content": {"keep": "structured"}},
        {"role": "tool", "tool_call_id": "call_1", "content": {"ok": False, "failed": ["dns"]}},
        {"role": "tool", "tool_call_id": "call_2", "content": ["a", 2]},
        {"role": "tool", "tool_call_id": "call_3", "content": "already text"},
    ]

    _stringify_tool_message_content(messages)

    assert messages[0]["content"] == {"keep": "structured"}
    assert json.loads(messages[1]["content"]) == {"ok": False, "failed": ["dns"]}
    assert json.loads(messages[2]["content"]) == ["a", 2]
    assert messages[3]["content"] == "already text"


def test_stringify_tool_content_falls_back_for_non_json_value():
    messages = [{"role": "tool", "content": {"values": {1, 2}}}]

    _stringify_tool_message_content(messages)

    assert isinstance(messages[0]["content"], str)
    assert "values" in messages[0]["content"]


def test_compacts_only_large_consumed_tool_results():
    old = "old-start" + "x" * 30_000 + "old-end"
    pending = "data:image/png;base64," + "A" * 40_000
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "old"}]},
        {"role": "tool", "content": old, "tool_call_id": "old"},
        {"role": "assistant", "tool_calls": [{"id": "pending"}]},
        {"role": "tool", "content": pending, "tool_call_id": "pending"},
    ]

    assert _compact_historical_tool_message_content(messages) == 1
    assert messages[1]["content"].startswith("old-start")
    assert messages[1]["content"].endswith("old-end")
    assert "historical tool result compacted" in messages[1]["content"]
    assert messages[3]["content"] == pending


def test_does_not_compact_newest_pending_tool_batch():
    pending = "data:image/png;base64," + "A" * 40_000
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "pending"}]},
        {"role": "tool", "content": pending, "tool_call_id": "pending"},
    ]

    assert _compact_historical_tool_message_content(messages) == 0
    assert messages[1]["content"] == pending
