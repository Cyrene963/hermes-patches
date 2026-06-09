"""Tests for conversation-loop API message request construction."""

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


def test_run_conversation_sends_memory_context_to_model_request_only():
    """Full loop boundary: final API request sees anchors; persisted history stays clean."""
    from run_agent import AIAgent

    captured = {}

    def fake_api_call(self, api_kwargs):
        captured["messages"] = api_kwargs["messages"]
        mock_choice = MagicMock()
        mock_choice.message.content = "Physics, Economics, ICT."
        mock_choice.message.tool_calls = None
        mock_choice.message.refusal = None
        mock_choice.message.reasoning_content = None
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        mock_response.model = "test-model"
        mock_response.id = "test-id"
        return mock_response

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
