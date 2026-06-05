"""Regression tests for group-chat memory privacy boundaries."""

import json

from run_agent import AIAgent


def _make_agent(chat_type="group"):
    agent = AIAgent(
        model="dummy",
        provider="openai",
        api_key="test-key",
        base_url="http://127.0.0.1:9/v1",
        platform="telegram",
        user_id="sender-private-user",
        user_name="Sender Name",
        chat_id="sender-private-user" if chat_type in {"dm", "personal_group"} else "-100group",
        chat_name="港大預備役學生交流群" if chat_type not in {"dm", "personal_group"} else None,
        chat_type=chat_type,
        thread_id="group:-100workspace" if chat_type == "personal_group" else None,
        session_id="sess-group" if chat_type not in {"dm", "personal_group"} else "sess-dm",
        skip_context_files=True,
        enabled_toolsets=[],
        quiet_mode=True,
    )
    return agent


def test_group_agent_does_not_load_private_builtin_memory():
    agent = _make_agent("group")

    assert agent._shared_chat_memory_scope is True
    assert agent._memory_store is None
    assert agent._memory_enabled is False
    assert agent._user_profile_enabled is False


def test_group_agent_uses_group_memory_namespace_not_sender_user_id():
    agent = _make_agent("group")

    assert agent._memory_namespace == "telegram:group:-100group"
    assert agent._user_id == "sender-private-user"  # retained only for routing/metadata


def test_dm_agent_keeps_private_user_scope():
    agent = _make_agent("dm")

    assert agent._shared_chat_memory_scope is False
    assert agent._memory_namespace == "telegram:sender-private-user"
    assert agent._memory_store is not None


def test_personal_group_workspace_keeps_private_user_scope_with_separate_window():
    agent = _make_agent("personal_group")

    assert agent._shared_chat_memory_scope is False
    assert agent._personal_workspace_memory_scope is True
    assert agent._memory_namespace == "telegram:sender-private-user"
    assert agent._memory_store is not None
    assert agent._thread_id == "group:-100workspace"


def test_group_session_search_is_blocked():
    agent = _make_agent("group")
    agent._get_session_db_for_recall = lambda: object()

    from agent.agent_runtime_helpers import invoke_tool
    result = json.loads(invoke_tool(agent, "session_search", {"query": "private"}, "task"))

    assert result["success"] is False
    assert "disabled in shared" in result["error"]
