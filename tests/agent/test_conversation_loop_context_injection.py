"""Tests for conversation-loop API message request construction."""

from agent.conversation_loop import _build_api_message_with_ephemeral_context


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
