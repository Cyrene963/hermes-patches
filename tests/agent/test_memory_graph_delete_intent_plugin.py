import importlib.util
from pathlib import Path


PLUGIN = Path.home() / ".hermes" / "plugins" / "memory-graph" / "__init__.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("memory_graph_delete_intent_test", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_private_leaf_delete_issues_turn_bound_grant(monkeypatch):
    plugin = _load_plugin()
    monkeypatch.setattr(plugin, "_async_scoped_search", lambda *args, **kwargs: _empty_async())
    monkeypatch.setattr(plugin, "get_current_namespace", lambda: "test:private")

    from tools import memory_graph_tool

    monkeypatch.setattr(memory_graph_tool, "_read", lambda *_args, **_kwargs: '{"content":"fixture"}')
    monkeypatch.setattr(memory_graph_tool, "_list", lambda *_args, **_kwargs: '{"children":[]}')
    result = plugin._pre_llm_call(
        user_message="delete core://fixture/exact",
        session_id="session-a",
        platform="cli",
    )
    assert "Authorized memory deletion" in result["context"]
    assert "delete_grant=" in result["context"]


def test_grouped_delete_request_abstains(monkeypatch):
    plugin = _load_plugin()
    monkeypatch.setattr(plugin, "_async_scoped_search", lambda *args, **kwargs: _empty_async())
    monkeypatch.setattr(plugin, "get_current_namespace", lambda: "test:private")
    plugin._protocol_turn_count = plugin._PROTOCOL_MAX_TURNS
    result = plugin._pre_llm_call(
        user_message="delete core://fixture/one and core://fixture/two",
        session_id="session-a",
        platform="cli",
    )
    assert result is None or "Authorized memory deletion" not in result.get("context", "")


async def _empty_async():
    return []