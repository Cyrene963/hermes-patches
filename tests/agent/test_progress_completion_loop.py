from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _response(content):
    message = SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning_content=None,
        reasoning=None,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        model="test/model",
        usage=None,
    )


def test_same_turn_continues_after_progress_only_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://example.invalid/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )

    requests = []

    def create(**kwargs):
        requests.append(kwargs["messages"])
        if len(requests) == 1:
            return _response("当前完成 60%，下一步需要跑完回归测试。")
        return _response("已经完成 100%，回归测试 12/12 通过。")

    agent.client = MagicMock()
    agent.client.chat.completions.create.side_effect = create
    agent._cached_system_prompt = "You are helpful."
    agent._use_prompt_caching = False
    agent.tool_delay = 0
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent._progress_completion_gate = True
    agent._max_progress_completion_nudges = 3

    result = agent.run_conversation("把这个项目推进到100%，中途不要停")

    assert result["completed"] is True
    assert result["final_response"] == "已经完成 100%，回归测试 12/12 通过。"
    assert len(requests) == 2
    second_contents = [str(message.get("content") or "") for message in requests[1]]
    assert any("Do not send another progress-only final answer" in text for text in second_contents)
    durable_contents = [str(message.get("content") or "") for message in result["messages"]]
    assert not any("Do not send another progress-only final answer" in text for text in durable_contents)
    assert not any("当前完成 60%" in text for text in durable_contents)
