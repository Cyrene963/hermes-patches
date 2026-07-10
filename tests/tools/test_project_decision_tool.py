from tools.registry import discover_builtin_tools, registry
from tools.project_decision_tool import _assess
from toolsets import TOOLSETS


def test_project_decision_tool_is_discovered_registered_and_platform_visible():
    imported = discover_builtin_tools()
    assert "tools.project_decision_tool" in imported
    entry = registry.get_entry("project_decision_assess")
    assert entry is not None
    assert entry.toolset == "memory_graph"
    definitions = registry.get_definitions({"project_decision_assess"})
    assert [item["function"]["name"] for item in definitions] == ["project_decision_assess"]
    assert "project_decision_assess" in TOOLSETS["hermes-cli"]["tools"]
    assert "project_decision_assess" in TOOLSETS["hermes-telegram"]["tools"]
    assert "project_decision_assess" in TOOLSETS["hermes-cron"]["tools"]


def test_project_decision_tool_executes_real_model():
    result = _assess({
        "pain_frequency": 1,
        "solo_start": 1,
        "dogfood": 1,
        "external_system_data": 1,
        "distribution": 0.8,
        "implementation_scope": 0.4,
        "measurable_experiment": True,
    })
    assert result["decision"] == "accept"
    assert result["score"] >= 3


def test_unknown_features_are_rejected_by_schema():
    entry = registry.get_entry("project_decision_assess")
    assert entry.schema["parameters"]["additionalProperties"] is False
