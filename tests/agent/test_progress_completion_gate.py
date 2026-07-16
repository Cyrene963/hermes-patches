from agent.progress_completion_gate import (
    build_progress_completion_nudge,
    progress_fingerprint,
)


def _nudge(user, response, **kwargs):
    return build_progress_completion_nudge(
        user_message=user,
        final_response=response,
        **kwargs,
    )


def test_explicit_100_percent_goal_continues_from_progress_report():
    result = _nudge(
        "把这个项目进度推进到100%，中途不要停",
        "当前完成 64%。下一步需要实现剩余的回归测试。",
    )
    assert result is not None
    assert "Execute the next concrete step now" in result


def test_active_todo_is_enough_when_response_omits_next_step_wording():
    result = _nudge(
        "完成全部工作，不要中途停下来只汇报",
        "核心功能已经写好。",
        active_todos=[{"status": "pending", "content": "run public smoke"}],
    )
    assert result is not None


def test_ordinary_question_does_not_trigger():
    assert _nudge("解释这个项目现在的进度", "当前完成 64%，下一步是跑测试。") is None


def test_verified_completion_does_not_trigger_without_unfinished_evidence():
    assert _nudge(
        "把项目推进到100%",
        "项目已经全部完成，验收测试 12/12 通过。",
    ) is None


def test_waiting_for_user_does_not_trigger():
    assert _nudge(
        "把项目推进到100%",
        "还需部署，但需要你确认生产域名后才能继续。",
    ) is None


def test_external_or_rate_limit_wait_does_not_trigger():
    assert _nudge(
        "把项目推进到100%",
        "当前 80%，额度限制，需要等待限流恢复。",
    ) is None


def test_terminal_blocker_does_not_trigger():
    assert _nudge(
        "把项目推进到100%",
        "仍未完成，但这是终止性阻塞：上游 API 已永久下线。",
    ) is None


def test_max_attempts_is_hard_bound():
    assert _nudge(
        "把项目推进到100%",
        "当前完成 70%，下一步继续测试。",
        attempts=3,
        max_attempts=3,
    ) is None


def test_no_progress_fingerprint_breaks_repeat_loop():
    fingerprint = (4, ("/tmp/a.py",))
    assert _nudge(
        "把项目推进到100%",
        "当前完成 70%，下一步继续测试。",
        attempts=1,
        current_fingerprint=fingerprint,
        previous_fingerprint=fingerprint,
    ) is None


def test_new_tool_evidence_allows_next_bounded_continuation():
    assert _nudge(
        "把项目推进到100%",
        "当前完成 80%，还需运行集成测试。",
        attempts=1,
        current_fingerprint=(5, ("/tmp/a.py",)),
        previous_fingerprint=(4, ("/tmp/a.py",)),
    ) is not None


def test_progress_fingerprint_counts_tool_results_and_changed_paths():
    messages = [
        {"role": "user", "content": "go"},
        {"role": "tool", "content": "one"},
        {"role": "assistant", "content": "working"},
        {"role": "tool", "content": "two"},
    ]
    assert progress_fingerprint(messages, ["b.py", "a.py", "b.py"]) == (
        2,
        ("a.py", "b.py"),
    )
