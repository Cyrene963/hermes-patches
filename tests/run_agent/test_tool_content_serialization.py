import json

from agent.conversation_loop import _stringify_tool_message_content


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
