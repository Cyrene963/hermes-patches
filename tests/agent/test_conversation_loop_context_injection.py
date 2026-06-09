"""Tests for conversation-loop API message request construction."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.conversation_loop import _build_api_message_with_ephemeral_context


class _FakeMemoryManager:
    def on_turn_start(self, **_kwargs):
        return None

    def prefetch_all(self, query, **_kwargs):
        assert query == "What are the student's DSE electives?"
        return (
            "# Hindsight Memory\n\n"
            "## Memory Graph Anchors\n"
            "- core://user-profile/student-dse-electives — Student studies Physics, Economics, ICT.\n\n"
            "## Hindsight Recall\n"
            "- Broad Hindsight long-tail context"
        )


class _NoAnchorMemoryManager:
    def on_turn_start(self, **_kwargs):
        return None

    def prefetch_all(self, query, **_kwargs):
        assert query == "What are the student's DSE electives?"
        return "## Hindsight Recall\n- Broad Hindsight long-tail context without the elective fact"


def _anchor_sensitive_response_from(api_kwargs, captured):
    captured["messages"] = api_kwargs["messages"]
    request_text = "\n\n".join(
        str(message.get("content", "")) for message in captured["messages"]
    )
    anchor_visible = (
        "## Memory Graph Anchors" in request_text
        and "Student studies Physics, Economics, ICT" in request_text
    )

    mock_message = SimpleNamespace(
        content=(
            "Anchor-driven answer: Physics, Economics, ICT."
            if anchor_visible
            else "ANCHOR_MISSING_SENTINEL"
        ),
        tool_calls=None,
        refusal=None,
        reasoning_content=None,
        reasoning=None,
        reasoning_details=None,
    )
    mock_choice = SimpleNamespace(
        message=mock_message,
        finish_reason="stop",
    )

    return SimpleNamespace(
        choices=[mock_choice],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        model="test-model",
        id="test-id",
    )


def test_current_user_message_gets_memory_graph_anchors_in_request_context():
    msg = {"role": "user", "content": "What are the student's DSE electives?"}
    prefetch = (
        "# Hindsight Memory\n\n"
        "## Memory Graph Anchors\n"
        "- core://user-profile/student-dse-electives — Student studies Physics, Economics, ICT.\n\n"
        "## Hindsight Recall\n"
        "- Broad Hindsight long-tail context"
    )

    api_msg = _build_api_message_with_ephemeral_context(
        msg,
        idx=1,
        current_turn_user_idx=1,
        ext_prefetch_cache=prefetch,
        plugin_user_context="",
    )

    content = api_msg["content"]
    assert content.startswith("What are the student's DSE electives?")
    assert "<memory-context>" in content
    assert "authoritative reference data" in content
    assert "## Memory Graph Anchors" in content
    assert "student-dse-electives" in content
    assert "Physics, Economics, ICT" in content
    assert "## Hindsight Recall" in content
    assert content.index("## Memory Graph Anchors") < content.index("## Hindsight Recall")
    assert msg["content"] == "What are the student's DSE electives?"


def test_ephemeral_context_only_injects_current_user_message():
    previous_user = {"role": "user", "content": "Earlier turn"}
    assistant_msg = {"role": "assistant", "content": "Earlier answer"}
    prefetch = "## Memory Graph Anchors\n- should not appear"

    previous_api_msg = _build_api_message_with_ephemeral_context(
        previous_user,
        idx=0,
        current_turn_user_idx=2,
        ext_prefetch_cache=prefetch,
        plugin_user_context="plugin context",
    )
    assistant_api_msg = _build_api_message_with_ephemeral_context(
        assistant_msg,
        idx=1,
        current_turn_user_idx=1,
        ext_prefetch_cache=prefetch,
        plugin_user_context="plugin context",
    )

    assert previous_api_msg == previous_user
    assert assistant_api_msg == assistant_msg


def test_plugin_context_appends_after_memory_context():
    msg = {"role": "user", "content": "Need context"}

    api_msg = _build_api_message_with_ephemeral_context(
        msg,
        idx=0,
        current_turn_user_idx=0,
        ext_prefetch_cache="## Memory Graph Anchors\n- precise fact",
        plugin_user_context="## Plugin Context\n- plugin fact",
    )

    content = api_msg["content"]
    assert content.index("## Memory Graph Anchors") < content.index("## Plugin Context")
    assert "precise fact" in content
    assert "plugin fact" in content


def test_run_conversation_final_response_is_anchor_driven():
    """Full loop boundary: fake model can answer only when anchors reach the request."""
    from run_agent import AIAgent

    captured = {}

    def fake_api_call(self, api_kwargs):
        return _anchor_sensitive_response_from(api_kwargs, captured)

    with patch("run_agent.AIAgent._build_system_prompt", return_value="system prompt"), \
         patch("run_agent.AIAgent._interruptible_api_call", fake_api_call), \
         patch("run_agent.AIAgent._interruptible_streaming_api_call", fake_api_call):
        agent = AIAgent(
            model="test/model",
            api_key="test-key",
            base_url="http://localhost:1234/v1",
            quiet_mode=True,
            skip_memory=True,
            skip_context_files=True,
        )
        agent.client = MagicMock()
        agent._memory_manager = _FakeMemoryManager()

        result = agent.run_conversation(
            user_message="What are the student's DSE electives?",
            conversation_history=[],
        )

    assert result["completed"] is True
    assert result["final_response"] == "Anchor-driven answer: Physics, Economics, ICT."
    assert "ANCHOR_MISSING_SENTINEL" not in result["final_response"]
    request_user_messages = [m for m in captured["messages"] if m.get("role") == "user"]
    assert len(request_user_messages) == 1
    request_content = request_user_messages[0]["content"]
    assert request_content.startswith("What are the student's DSE electives?")
    assert "<memory-context>" in request_content
    assert "## Memory Graph Anchors" in request_content
    assert "Physics, Economics, ICT" in request_content
    assert request_content.index("## Memory Graph Anchors") < request_content.index("## Hindsight Recall")

    persisted_user_messages = [m for m in result["messages"] if m.get("role") == "user"]
    assert persisted_user_messages == [{"role": "user", "content": "What are the student's DSE electives?"}]


def test_run_conversation_without_memory_graph_anchor_returns_sentinel():
    """Negative control: fake model cannot answer from generic Hindsight-only context."""
    from run_agent import AIAgent

    captured = {}

    def fake_api_call(self, api_kwargs):
        return _anchor_sensitive_response_from(api_kwargs, captured)

    with patch("run_agent.AIAgent._build_system_prompt", return_value="system prompt"), \
         patch("run_agent.AIAgent._interruptible_api_call", fake_api_call), \
         patch("run_agent.AIAgent._interruptible_streaming_api_call", fake_api_call):
        agent = AIAgent(
            model="test/model",
            api_key="test-key",
            base_url="http://localhost:1234/v1",
            quiet_mode=True,
            skip_memory=True,
            skip_context_files=True,
        )
        agent.client = MagicMock()
        agent._memory_manager = _NoAnchorMemoryManager()

        result = agent.run_conversation(
            user_message="What are the student's DSE electives?",
            conversation_history=[],
        )

    assert result["completed"] is True
    assert result["final_response"] == "ANCHOR_MISSING_SENTINEL"
    request_user_messages = [m for m in captured["messages"] if m.get("role") == "user"]
    assert len(request_user_messages) == 1
    request_content = request_user_messages[0]["content"]
    assert "<memory-context>" in request_content
    assert "## Hindsight Recall" in request_content
    assert "## Memory Graph Anchors" not in request_content
    assert "Student studies Physics, Economics, ICT" not in request_content
