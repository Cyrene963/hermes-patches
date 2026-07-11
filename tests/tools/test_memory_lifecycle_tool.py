import json
from tools.memory_lifecycle_tool import _delete
from tools.registry import discover_builtin_tools, registry
from toolsets import resolve_toolset


def test_lifecycle_tools_registered_and_visible():
    discover_builtin_tools()
    for name in ("memory_lifecycle_delete","memory_lifecycle_rollback"):
        assert registry.get_entry(name) is not None
        assert name in resolve_toolset("memory_graph")
        assert name in resolve_toolset("hermes-cli")


def test_delete_handler_refuses_missing_namespace_without_graph_call():
    discover_builtin_tools()
    result=json.loads(_delete({"uri":"core://neutral/item","namespace":"","delete_grant":"fabricated","candidate_count":1}))
    assert result["ok"] is False
    assert result["error"] == "invalid_delete_grant"
