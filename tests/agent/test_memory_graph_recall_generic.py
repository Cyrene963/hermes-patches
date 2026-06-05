"""Regression tests for generic Memory Graph search and plugin recall behavior."""

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

from agent.memory_graph.services.search import SearchIndexer


_ORIGINAL_HOME = Path(os.environ.get("HOME", "~")).expanduser()


def test_search_indexer_builds_or_tsquery_from_normalized_tokens():
    tsquery = SearchIndexer._to_or_tsquery("alpha beta 误差 以内 alpha")
    assert tsquery == "alpha | beta | 误差 | 以内"


def test_expand_query_terms_preserves_cjk_compounds_for_ranking():
    from agent.memory_graph.services.search_terms import expand_query_terms

    expanded = expand_query_terms("误差以内 未来伴侣 宏观理性")
    assert "误差以内" in expanded
    assert "未来伴侣" in expanded
    assert "宏观理性" in expanded


def test_search_indexer_or_query_allows_partial_memory_matches():
    class FakeSession:
        def __init__(self):
            self.statements = []

        async def execute(self, stmt, params=None):
            self.statements.append((str(stmt), params or {}))

            class Result:
                def all(self):
                    return []

            return Result()

    class SessionFactory:
        def __init__(self):
            self.session = FakeSession()

        def __call__(self):
            outer = self

            class Ctx:
                async def __aenter__(self):
                    return outer.session

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            return Ctx()

    factory = SessionFactory()
    indexer = SearchIndexer(session_factory=factory)
    asyncio.run(indexer.search("alpha beta gamma", namespace="telegram:u1", limit=3))

    sql, params = factory.session.statements[0]
    assert "to_tsquery('simple', :ts_query)" in sql
    assert "sd.namespace = :namespace OR sd.namespace = ''" in sql
    assert "raw_query" in sql
    assert "namespace_rank ASC" in sql
    assert "用户档案" in sql
    assert params["ts_query"] == "alpha | beta | gamma"


def _load_memory_graph_plugin():
    candidates = [
        Path.home() / ".hermes" / "plugins" / "memory-graph" / "__init__.py",
        _ORIGINAL_HOME / ".hermes" / "plugins" / "memory-graph" / "__init__.py",
        _ORIGINAL_HOME / ".hermes" / "patches" / "plugins" / "memory-graph" / "__init__.py",
    ]
    plugin_path = next((p for p in candidates if p.exists()), candidates[0])
    spec = importlib.util.spec_from_file_location("memory_graph_plugin_under_test", plugin_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_plugin_recall_queries_keep_whole_message_and_longest_fallbacks():
    plugin = _load_memory_graph_plugin()
    queries = plugin._build_recall_queries(
        "我们之前聊过误差以内、未来伴侣模型、宏观理性和漫画规划，你还记得吗？",
        max_chars=120,
        max_tokens=6,
    )

    assert queries[0].startswith("我们之前聊过误差以内")
    assert any("未来伴侣模型" in q for q in queries)
    assert any("宏观理性" in q or "宏观理性和漫画规划" in q for q in queries)
    assert len(queries) >= 3


def test_high_signal_short_messages_bypass_length_gate():
    plugin = _load_memory_graph_plugin()

    assert plugin._is_high_signal_short_message("继续") is True
    assert plugin._is_high_signal_short_message("有必要吗") is True
    assert plugin._is_high_signal_short_message("错错错") is True
    assert plugin._is_high_signal_short_message("嗯") is False


def test_cli_auto_recall_uses_default_terminal_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "config.yaml").write_text(
        "memory_graph:\n  default_terminal_user: user-a\n",
        encoding="utf-8",
    )
    plugin = _load_memory_graph_plugin()
    plugin.set_current_namespace("")

    monkeypatch.setattr(plugin, "_apply_turn_namespace_from_kwargs", lambda kwargs: None)
    ns = plugin._resolve_runtime_namespace({"platform": "cli"})

    assert ns == "telegram:user-a"
    assert plugin.get_current_namespace() == "telegram:user-a"
