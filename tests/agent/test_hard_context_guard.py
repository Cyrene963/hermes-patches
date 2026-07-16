import copy
import json

from agent.conversation_loop import (
    _compact_historical_tool_message_content,
    _fit_api_messages_to_hard_context_budget,
)
from agent.model_metadata import estimate_request_tokens_rough


def _tool_call(call_id: str = "call_1") -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": "vision_analyze", "arguments": "{}"},
        }],
    }


def _assert_tool_pairs(messages: list[dict]) -> None:
    call_ids = {
        tc["id"]
        for msg in messages
        for tc in (msg.get("tool_calls") or [])
        if isinstance(tc, dict) and tc.get("id")
    }
    result_ids = {
        msg.get("tool_call_id")
        for msg in messages
        if msg.get("role") == "tool" and msg.get("tool_call_id")
    }
    assert call_ids == result_ids


def test_consumed_tail_tool_batch_is_compacted_after_new_user_message():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "review screenshots"},
        _tool_call(),
        {"role": "tool", "tool_call_id": "call_1", "content": "x" * 100_000},
        {"role": "user", "content": "background process finished"},
    ]
    assert _compact_historical_tool_message_content(messages) == 1
    assert len(messages[3]["content"]) < 20_000


def test_truly_pending_tail_tool_batch_is_preserved_until_hard_guard():
    messages = [
        {"role": "user", "content": "review screenshot"},
        _tool_call(),
        {"role": "tool", "tool_call_id": "call_1", "content": "x" * 100_000},
    ]
    original = messages[-1]["content"]
    assert _compact_historical_tool_message_content(messages) == 0
    assert messages[-1]["content"] == original


def test_hard_guard_keeps_system_and_largest_recent_complete_suffix():
    messages = [{"role": "system", "content": "system"}]
    for index in range(5):
        call_id = f"call_{index}"
        messages.extend([
            {"role": "user", "content": f"task {index} " + "u" * 4_000},
            _tool_call(call_id),
            {"role": "tool", "tool_call_id": call_id, "content": "t" * 40_000},
            {"role": "assistant", "content": f"done {index}"},
        ])
    messages.append({"role": "user", "content": "latest state must survive"})
    fitted, dropped = _fit_api_messages_to_hard_context_budget(
        copy.deepcopy(messages), tools=[], budget_tokens=18_000, budget_chars=25_000
    )
    assert dropped > 0
    assert fitted[0]["role"] == "system"
    assert fitted[-1]["content"] == "latest state must survive"
    assert "Earlier conversation omitted" in fitted[1]["content"]
    assert estimate_request_tokens_rough(fitted, tools=None) <= 18_000
    assert sum(len(json.dumps(m)) for m in fitted) <= 25_000
    _assert_tool_pairs(fitted)
