"""Privacy regression tests for personal Telegram workspace namespaces."""

import importlib.util
from pathlib import Path


PLUGIN = Path.home() / ".hermes" / "plugins" / "memory-graph" / "__init__.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("memory_graph_plugin_under_test", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_personal_group_uses_private_user_namespace():
    plugin = _load_plugin()
    assert plugin._is_shared_chat(
        chat_type="personal_group",
        user_id="user-a",
        chat_id="user-a",
    ) is False
    assert plugin._resolve_namespace(
        chat_type="personal_group",
        user_id="user-a",
        chat_id="user-a",
        platform="telegram",
        thread_id="group:-100",
    ) == "telegram:user-a"


def test_personal_group_is_not_treated_as_shared_recall_scope(monkeypatch):
    plugin = _load_plugin()
    captured = {}

    async def fake_search(query, namespace="", include_core=True, shared_scope=False, limit=3):
        captured.update(namespace=namespace, include_core=include_core, shared_scope=shared_scope)
        return [{"uri": "core://project", "content": "project memory"}]

    monkeypatch.setattr(plugin, "_async_scoped_search", fake_search)
    monkeypatch.setattr(plugin, "_hydrate_recall_content", lambda items, namespace="": _async_value(items))
    result = plugin._pre_llm_call(
        user_message="continue private task",
        session_id="s-personal",
        platform="telegram",
        user_id="user-a",
        chat_id="user-a",
        chat_type="personal_group",
        thread_id="group:-100",
    )
    assert result and "project memory" in result["context"]
    assert captured == {
        "namespace": "telegram:user-a",
        "include_core": True,
        "shared_scope": False,
    }


async def _async_value(value):
    return value


def test_real_group_remains_shared_namespace():
    plugin = _load_plugin()
    assert plugin._is_shared_chat(
        chat_type="group",
        user_id="user-a",
        chat_id="-100",
    ) is True
    assert plugin._resolve_namespace(
        chat_type="group",
        user_id="user-a",
        chat_id="-100",
        platform="telegram",
    ) == "telegram:group:-100"
