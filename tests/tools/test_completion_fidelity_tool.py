from tools.completion_fidelity_tool import _assess
from tools.registry import discover_builtin_tools, registry
from toolsets import resolve_toolset


def test_completion_tool_registered_visible_and_executes():
    assert "tools.completion_fidelity_tool" in discover_builtin_tools()
    entry = registry.get_entry("completion_evidence_assess")
    assert entry is not None
    for bundle in ("hermes-cli", "hermes-telegram", "hermes-cron"):
        assert "completion_evidence_assess" in resolve_toolset(bundle)
    result = _assess({
        "requirements": [{"id": "tests", "kind": "command", "command_id": "tests", "output_contains": "passed"}],
        "evidence": {"commands": [{"id": "tests", "exit_code": 0, "output": "7 passed"}]},
    })
    assert result["complete"] is True


def test_completion_tool_fails_closed_for_missing_evidence():
    result = _assess({
        "requirements": [{"id": "artifact", "kind": "artifact", "path": "/tmp/neutral"}],
        "evidence": {},
    })
    assert result["complete"] is False
    assert result["missing"] == ("artifact",)
