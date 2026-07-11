from tools.registry import discover_builtin_tools, registry
from tools.temporal_self_tool import _resolve
from toolsets import resolve_toolset


def test_temporal_self_tool_registered_visible_and_executable():
    assert "tools.temporal_self_tool" in discover_builtin_tools()
    entry = registry.get_entry("temporal_self_resolve")
    assert entry is not None
    for bundle in ("hermes-cli", "hermes-telegram", "hermes-cron"):
        assert "temporal_self_resolve" in resolve_toolset(bundle)
    result = _resolve({
        "as_of": "2025-03-01T00:00:00Z",
        "observations": [
            {"value": "earlier", "effective_at": "2025-01-01T00:00:00Z"},
            {"value": "future", "effective_at": "2025-06-01T00:00:00Z"},
        ],
    })
    assert result["status"] == "resolved"
    assert result["value"] == "earlier"


def test_temporal_tool_schema_requires_time_and_observations():
    entry = registry.get_entry("temporal_self_resolve")
    assert set(entry.schema["parameters"]["required"]) == {"as_of", "observations"}
    assert entry.schema["parameters"]["additionalProperties"] is False
