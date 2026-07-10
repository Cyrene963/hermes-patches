"""Privacy regression tests for personal Telegram workspace namespaces."""

import importlib.util
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "memory-graph" / "__init__.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("memory_graph_plugin_under_test", PLUGIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_personal_group_uses_private_user_namespace():
    plugin = _load_plugin()
    assert plugin._is_shared_chat(
        chat_type="personal_group", user_id="user-a", chat_id="user-a"
    ) is False
    assert plugin._resolve_namespace(
        chat_type="personal_group",
        user_id="user-a",
        chat_id="user-a",
        platform="telegram",
        thread_id="group:-100",
    ) == "telegram:user-a"


def test_real_group_remains_shared_namespace():
    plugin = _load_plugin()
    assert plugin._is_shared_chat(
        chat_type="group", user_id="user-a", chat_id="-100"
    ) is True
    assert plugin._resolve_namespace(
        chat_type="group",
        user_id="user-a",
        chat_id="-100",
        platform="telegram",
    ) == "telegram:group:-100"
