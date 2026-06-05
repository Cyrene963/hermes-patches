"""Tests for Memory Graph Hermes tool wrappers."""

import json


def test_refresh_search_index_calls_ensure_db_before_indexer(monkeypatch):
    import tools.memory_graph_tool as mg

    calls = []

    class FakeIndexer:
        def refresh_search_documents_for_node(self, node_uuid, namespace):
            calls.append(("refresh", node_uuid, namespace))
            return "coro"

    monkeypatch.setattr(mg, "_ensure_db", lambda: calls.append(("ensure",)))
    monkeypatch.setattr(mg, "_run", lambda coro: calls.append(("run", coro)))

    import agent.memory_graph.services.search as search_mod
    monkeypatch.setattr(search_mod, "SearchIndexer", FakeIndexer)

    mg._refresh_search_index("node-1", "telegram:u1")

    assert calls == [
        ("ensure",),
        ("refresh", "node-1", "telegram:u1"),
        ("run", "coro"),
    ]


def test_create_refreshes_search_index(monkeypatch):
    import tools.memory_graph_tool as mg

    calls = []

    class FakeGraph:
        def create_memory(self, *args, **kwargs):
            calls.append(("create", args, kwargs))
            return {"node_uuid": "node-created", "uri": "core://x"}

    monkeypatch.setattr(mg, "_ensure_db", lambda: None)
    monkeypatch.setattr(mg, "_get_namespace", lambda: "telegram:u1")
    monkeypatch.setattr(mg, "_refresh_search_index", lambda node_uuid, ns: calls.append(("refresh", node_uuid, ns)))
    monkeypatch.setattr(mg, "_run", lambda value: value)

    import agent.memory_graph.services.graph as graph_mod
    monkeypatch.setattr(graph_mod, "GraphService", FakeGraph)

    out = json.loads(mg._create({"parent_uri": "", "content": "hello", "domain": "core", "title": "x"}))

    assert out["node_uuid"] == "node-created"
    assert calls[-1] == ("refresh", "node-created", "telegram:u1")
