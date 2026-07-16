from agent.conversation_loop import _retire_multimodal_tool_payloads


def test_retires_consumed_image_payload_but_keeps_text_summary():
    messages = [
        {"role": "user", "content": "inspect this"},
        {
            "role": "tool",
            "name": "browser_vision",
            "tool_call_id": "call_1",
            "content": [
                {"type": "text", "text": "page rendered correctly"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + "A" * 10000},
                },
            ],
        },
    ]

    assert _retire_multimodal_tool_payloads(messages) == 1
    assert messages[1]["content"] == [
        {"type": "text", "text": "page rendered correctly"},
        {"type": "text", "text": "[screenshot]"},
    ]
    assert "base64" not in str(messages)
    assert _retire_multimodal_tool_payloads(messages) == 0


def test_leaves_non_tool_and_text_tool_messages_unchanged():
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "x"}}],
        },
        {"role": "tool", "content": "plain result", "tool_call_id": "call_2"},
    ]

    original = list(messages)
    assert _retire_multimodal_tool_payloads(messages) == 0
    assert messages == original
