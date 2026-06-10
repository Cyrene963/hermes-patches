import importlib.util
import os
from pathlib import Path


def _load_plugin():
    explicit = os.environ.get("MEMORY_GRAPH_PLUGIN_PATH")
    if explicit:
        path = Path(explicit)
    else:
        home = Path(os.environ.get("HERMES_PROFILE_HOME") or os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        # HERMES_HOME may point either to a profile root or to a hermes-agent repo.
        candidate = home / "plugins" / "memory-graph" / "__init__.py"
        path = candidate if candidate.exists() else Path.home() / ".hermes" / "plugins" / "memory-graph" / "__init__.py"
    spec = importlib.util.spec_from_file_location("memory_graph_plugin_content_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_auto_recall_uses_content_not_only_snippet(monkeypatch):
    mod = _load_plugin()
    monkeypatch.setattr(mod, "_resolve_runtime_namespace", lambda kwargs=None: "telegram:example")
    monkeypatch.setattr(mod, "_load_plugin_config", lambda: {
        "auto_recall_max_query_chars": 320,
        "auto_recall_max_tokens": 12,
        "auto_recall_max_results": 1,
        "auto_recall_context_chars": 900,
        "auto_recall_min_message_chars": 5,
    })

    async def fake_search(query, namespace="", include_core=True, shared_scope=False, limit=3):
        return [{
            "uri": "user://tool-route/claude",
            "snippet": "Claude route: Anyr...",
            "content": "Claude Code can be invoked through an API-key provider mode; include --betas context-1m-2025-08-07 and source the operator secret env file. Do not stop at Not logged in.",
        }]

    monkeypatch.setattr(mod, "_async_scoped_search", fake_search)
    result = mod._pre_llm_call(user_message="Claude Code says Not logged in", platform="cli")
    assert result and "context" in result
    assert "--betas context-1m-2025-08-07" in result["context"]
    assert "Do not stop at Not logged in" in result["context"]


def test_learning_event_messages_expand_to_target_function_queries():
    mod = _load_plugin()

    queries = mod._build_recall_queries("我今天英文作文那个复盘你还记得吗")
    joined = "\n".join(queries)

    assert "学习事件" in joined
    assert "考后复盘" in joined
    assert "主动召回" in joined
    assert "target function" in joined
    assert "Paper 2 task coverage" in joined


def test_unrelated_messages_do_not_get_learning_event_expansion():
    mod = _load_plugin()

    queries = mod._build_recall_queries("今天天气怎么样")
    joined = "\n".join(queries)

    assert queries == ["今天天气怎么样"]
    assert "学习事件" not in joined
    assert "target function" not in joined
