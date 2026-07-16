from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli import oneshot


def _runtime():
    return {
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
        "provider": "custom:test",
        "api_mode": "chat_completions",
        "credential_pool": None,
    }


def _config():
    return {
        "model": {"default": "test-model", "provider": "custom:test"},
        "platform_toolsets": {"cli": []},
    }


def test_run_agent_resumes_same_session_with_loaded_history():
    db = MagicMock()
    db.resolve_resume_session_id.return_value = "session-child"
    db.get_session.return_value = {"id": "session-child"}
    history = [
        {"role": "user", "content": "original goal"},
        {"role": "assistant", "content": "still working"},
    ]
    db.get_messages_as_conversation.return_value = history
    agent = MagicMock()
    agent.run_conversation.return_value = {
        "final_response": "done",
        "completed": True,
    }

    with (
        patch("hermes_cli.config.load_config", return_value=_config()),
        patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value=_runtime()),
        patch.object(oneshot, "_create_session_db_for_oneshot", return_value=db),
        patch("run_agent.AIAgent", return_value=agent) as agent_cls,
        patch.object(oneshot, "get_fallback_chain", return_value=[]),
        patch("hermes_cli.tools_config._get_platform_tools", return_value=set()),
    ):
        response, result = oneshot._run_agent(
            "continue now",
            resume_session_id="session-root",
        )

    assert response == "done"
    assert result["completed"] is True
    assert agent_cls.call_args.kwargs["session_id"] == "session-child"
    agent.run_conversation.assert_called_once_with(
        "continue now",
        conversation_history=history,
    )


def test_run_agent_resume_missing_session_fails_closed():
    db = MagicMock()
    db.resolve_resume_session_id.return_value = "missing"
    db.get_session.return_value = None
    with (
        patch("hermes_cli.config.load_config", return_value=_config()),
        patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value=_runtime()),
        patch.object(oneshot, "_create_session_db_for_oneshot", return_value=db),
        patch.object(oneshot, "get_fallback_chain", return_value=[]),
        patch("hermes_cli.tools_config._get_platform_tools", return_value=set()),
    ):
        with pytest.raises(RuntimeError, match="session not found"):
            oneshot._run_agent("continue", resume_session_id="missing")


def test_run_agent_resume_empty_session_fails_closed():
    db = MagicMock()
    db.resolve_resume_session_id.return_value = "empty"
    db.get_session.return_value = {"id": "empty"}
    db.get_messages_as_conversation.return_value = []
    with (
        patch("hermes_cli.config.load_config", return_value=_config()),
        patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value=_runtime()),
        patch.object(oneshot, "_create_session_db_for_oneshot", return_value=db),
        patch.object(oneshot, "get_fallback_chain", return_value=[]),
        patch("hermes_cli.tools_config._get_platform_tools", return_value=set()),
    ):
        with pytest.raises(RuntimeError, match="session has no messages"):
            oneshot._run_agent("continue", resume_session_id="empty")
