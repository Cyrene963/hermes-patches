"""Regression tests for Memory Preflight dispatch enforcement.

These tests use synthetic policies only. They do not write to Memory Graph,
Hindsight, or user memory stores.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _make_tool_defs(*names: str) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"{name} tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in names
    ]


def _mock_tool_call(name="web_search", arguments="{}", call_id=None):
    return SimpleNamespace(
        id=call_id or f"call_{uuid.uuid4().hex[:8]}",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _make_agent(*tool_names: str) -> AIAgent:
    with (
        patch("run_agent.get_tool_definitions", return_value=_make_tool_defs(*tool_names)),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("hermes_cli.config.load_config", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-placeholder",
            base_url="https://openrouter.ai/api/v1",
            max_iterations=10,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    agent.client = MagicMock()
    agent._cached_system_prompt = "You are helpful."
    agent._use_prompt_caching = False
    agent.tool_delay = 0
    agent.compression_enabled = False
    agent.save_trajectories = False
    return agent


_SYNTHETIC_PREFLIGHT_POLICY = {
    "preflight": {
        "enabled": True,
        "rules": [
            {
                "tool": "web_extract",
                "task_type": "blocked_site_extract",
                "trigger_patterns": ["blocked.example"],
                "block_on_failure": True,
                "checks": [
                    {
                        "type": "field_not_contains",
                        "field": "urls",
                        "value": "blocked.example",
                        "required": True,
                        "error": "blocked.example must use browser fallback",
                    }
                ],
            },
            {
                "tool": "send_message",
                "task_type": "media_text_leak",
                "trigger_patterns": ["MEDIA:"],
                "block_on_failure": True,
                "checks": [
                    {
                        "type": "field_not_contains",
                        "field": "message",
                        "value": "MEDIA:",
                        "required": True,
                        "error": "MEDIA tag must not be sent as plain text",
                    }
                ],
            },
        ],
    }
}


def test_shared_preflight_helper_blocks_policy_match_and_allows_non_match():
    from agent.memory_metacognition import get_tool_preflight_block_message

    with patch("agent.memory_metacognition.load_policy", return_value=_SYNTHETIC_PREFLIGHT_POLICY):
        blocked = get_tool_preflight_block_message(
            "web_extract", {"urls": ["https://blocked.example/t/1"]}
        )
        allowed = get_tool_preflight_block_message(
            "web_extract", {"urls": ["https://github.com/example/repo"]}
        )
        media = get_tool_preflight_block_message(
            "send_message", {"target": "telegram", "message": "MEDIA:/tmp/file.md"}
        )

    assert blocked == "blocked.example must use browser fallback"
    assert allowed is None
    assert media == "MEDIA tag must not be sent as plain text"


def test_invoke_tool_prechecked_still_runs_memory_preflight_before_plugin_gate():
    agent = _make_agent("web_extract")
    with patch("agent.memory_metacognition.load_policy", return_value=_SYNTHETIC_PREFLIGHT_POLICY):
        result = agent._invoke_tool(
            "web_extract",
            {"urls": ["https://blocked.example/t/1"]},
            "task-1",
            "call-1",
            messages=[],
            pre_tool_block_checked=True,
        )

    payload = json.loads(result)
    assert payload["error"] == "blocked.example must use browser fallback"


def test_sequential_executor_blocks_memory_preflight_before_tool_execution():
    agent = _make_agent("web_extract")
    tc = _mock_tool_call(
        "web_extract", json.dumps({"urls": ["https://blocked.example/t/1"]}), "c-block"
    )
    msg = SimpleNamespace(content="", tool_calls=[tc])
    messages = []

    with (
        patch("agent.memory_metacognition.load_policy", return_value=_SYNTHETIC_PREFLIGHT_POLICY),
        patch("run_agent.handle_function_call", return_value="SHOULD_NOT_RUN") as mock_hfc,
    ):
        agent._execute_tool_calls_sequential(msg, messages, "task-1")

    mock_hfc.assert_not_called()
    assert len(messages) == 1
    assert messages[0]["tool_call_id"] == "c-block"
    assert "blocked.example must use browser fallback" in messages[0]["content"]


def test_concurrent_executor_blocks_memory_preflight_before_tool_execution_and_preserves_allowed_call():
    agent = _make_agent("web_extract")
    calls = [
        _mock_tool_call(
            "web_extract", json.dumps({"urls": ["https://blocked.example/t/1"]}), "c-block"
        ),
        _mock_tool_call(
            "web_extract", json.dumps({"urls": ["https://github.com/example/repo"]}), "c-allow"
        ),
    ]
    msg = SimpleNamespace(content="", tool_calls=calls)
    messages = []
    executed = []

    def fake_handle(name, args, task_id, **kwargs):
        executed.append((name, args, kwargs["tool_call_id"]))
        return json.dumps({"ok": args["urls"][0]})

    with (
        patch("agent.memory_metacognition.load_policy", return_value=_SYNTHETIC_PREFLIGHT_POLICY),
        patch("run_agent.handle_function_call", side_effect=fake_handle),
    ):
        agent._execute_tool_calls_concurrent(msg, messages, "task-1")

    assert executed == [("web_extract", {"urls": ["https://github.com/example/repo"]}, "c-allow")]
    assert [m["tool_call_id"] for m in messages] == ["c-block", "c-allow"]
    assert "blocked.example must use browser fallback" in messages[0]["content"]
    assert "https://github.com/example/repo" in messages[1]["content"]


def test_preflight_policy_api_failure_is_logged_and_degrades_open(caplog):
    from agent.memory_metacognition import get_tool_preflight_block_message

    class BrokenPolicy:
        def get_task_type(self, tool_name, tool_args):
            raise AttributeError("synthetic broken policy")

    with patch("agent.memory_metacognition.build_preflight_policy", return_value=BrokenPolicy()):
        result = get_tool_preflight_block_message("web_extract", {"urls": ["https://blocked.example"]})

    assert result is None
    assert "memory preflight policy error for web_extract" in caplog.text
