import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.skill_router import route_skills
from agent.tool_executor import execute_tool_calls_sequential


class _Hints:
    def check_tool_call(self, *_args, **_kwargs):
        return ""


class _Guardrails:
    def before_call(self, *_args, **_kwargs):
        return SimpleNamespace(allows_execution=True)


def _tool_call(name="terminal", args=None, id="tc1"):
    return SimpleNamespace(
        id=id,
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(args or {}),
        ),
    )


def _agent(decision=None):
    a = SimpleNamespace()
    a._interrupt_requested = False
    a.log_prefix = ""
    a.quiet_mode = True
    a.verbose_logging = False
    a.log_prefix_chars = 80
    a.tool_progress_callback = None
    a.tool_start_callback = None
    a.tool_complete_callback = None
    a.tool_delay = 0
    a.session_id = "s1"
    a.valid_tool_names = {"terminal"}
    a._skill_route_decision = decision
    a._tool_guardrails = _Guardrails()
    a._checkpoint_mgr = SimpleNamespace(enabled=False)
    a._subdirectory_hints = _Hints()
    a._context_engine_tool_names = set()
    a._memory_manager = None
    a._shared_chat_memory_scope = False
    a._todo_store = None
    a._memory_store = None
    a._turns_since_memory = 0
    a._iters_since_skill = 0
    a._current_tool = None
    a._should_emit_quiet_tool_messages = lambda: False
    a._should_start_quiet_spinner = lambda: False
    a._touch_activity = lambda *_args, **_kwargs: None
    a._vprint = lambda *_args, **_kwargs: None
    a._safe_print = lambda *_args, **_kwargs: None
    a._wrap_verbose = lambda label, text, indent="": label + text
    a._record_file_mutation_result = lambda *_args, **_kwargs: None
    a._append_guardrail_observation = lambda _name, _args, result, failed=False: result
    a._tool_result_content_for_active_model = lambda _name, result: result
    a._apply_pending_steer_to_tool_results = lambda *_args, **_kwargs: None
    a.clarify_callback = None
    return a


def test_sequential_tool_execution_is_blocked_when_mandatory_skill_not_loaded():
    decision = route_skills("你花一晚上彻底修复 Hermes Agent skills，不准停。", {
        "deep-work", "hermes-agent", "memory-management", "hermes-memory-os", "universal-solutions-for-prs"
    })
    decision.loaded_skills = ["deep-work"]
    agent = _agent(decision)
    messages = []

    execute_tool_calls_sequential(
        agent,
        SimpleNamespace(tool_calls=[_tool_call("terminal", {"command": "echo should-not-run"})]),
        messages,
        "task1",
    )

    assert len(messages) == 1
    assert messages[0]["role"] == "tool"
    payload = json.loads(messages[0]["content"])
    assert "Skill Router blocked tool execution" in payload["error"]
    assert "mandatory_skills_not_loaded" in payload["reason"]


def test_sequential_tool_error_gets_runtime_reroute_guidance(monkeypatch):
    decision = route_skills("你花一晚上把 failing tests 修到能 merge，不准停。", {
        "deep-work", "hermes-agent", "memory-management", "hermes-memory-os", "universal-solutions-for-prs"
    })
    decision.loaded_skills = list(decision.mandatory_skills)
    agent = _agent(decision)
    messages = []

    import run_agent

    monkeypatch.setattr(
        run_agent,
        "handle_function_call",
        lambda *_args, **_kwargs: json.dumps({"output": "pytest failed", "exit_code": 1}),
    )

    execute_tool_calls_sequential(
        agent,
        SimpleNamespace(tool_calls=[_tool_call("terminal", {"command": "pytest"})]),
        messages,
        "task1",
    )

    assert len(messages) == 1
    assert '"exit_code": 1' in messages[0]["content"]
    assert "pytest failed" in messages[0]["content"]
    assert "Hermes Skill Router Runtime Re-Route" in messages[0]["content"]
    assert "do not final" in messages[0]["content"]
