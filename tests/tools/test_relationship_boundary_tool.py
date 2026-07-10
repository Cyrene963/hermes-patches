from tools.registry import discover_builtin_tools, registry
from tools.relationship_boundary_tool import _assess
from toolsets import resolve_toolset


def test_relationship_boundary_tool_is_registered_and_visible():
    imported = discover_builtin_tools()
    assert "tools.relationship_boundary_tool" in imported
    entry = registry.get_entry("relationship_boundary_assess")
    assert entry is not None
    assert registry.get_definitions({"relationship_boundary_assess"})[0]["function"]["name"] == "relationship_boundary_assess"
    for bundle in ("hermes-cli", "hermes-telegram", "hermes-cron"):
        assert "relationship_boundary_assess" in resolve_toolset(bundle)


def test_relationship_boundary_tool_executes_real_model():
    result = _assess({
        "reciprocity": 0.1,
        "reliability": 0.3,
        "boundary_respect": 0.2,
        "personal_attack": 0.9,
        "stonewalling": 0.9,
        "independent_observations": 6,
    })
    assert result["tier"] == "distance"
    assert "no core dependence" in result["investment"]
