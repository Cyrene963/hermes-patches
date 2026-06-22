"""Tests for Memory Graph Hermes tool wrappers."""

import json

import pytest


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


def test_create_user_private_path_accepts_resolved_fallback_namespace(monkeypatch):
    import tools.memory_graph_tool as mg

    calls = []

    class FakeGraph:
        def create_memory(self, *args, **kwargs):
            calls.append(("create", args, kwargs))
            return {"node_uuid": "node-created", "uri": "core://用户档案/test"}

    monkeypatch.setattr(mg, "_ensure_db", lambda: None)
    monkeypatch.setattr(mg, "_get_namespace", lambda: "telegram:u1")
    monkeypatch.setattr(mg, "_refresh_search_index", lambda node_uuid, ns: calls.append(("refresh", node_uuid, ns)))
    monkeypatch.setattr(mg, "_run", lambda value: value)

    import agent.request_context as request_context
    import agent.memory_graph.services.graph as graph_mod

    request_context.reset_context()
    monkeypatch.setattr(graph_mod, "GraphService", FakeGraph)

    out = json.loads(mg._create({
        "parent_uri": "core://用户档案",
        "content": "private learning memory",
        "domain": "core",
        "title": "test",
    }))

    assert "error" not in out
    assert calls[0][2]["namespace"] == "telegram:u1"
    assert calls[-1] == ("refresh", "node-created", "telegram:u1")


def test_create_binds_explicit_namespace_to_rls_context(monkeypatch):
    import tools.memory_graph_tool as mg

    calls = []

    class FakeContext:
        def __init__(self, namespace):
            self.namespace = namespace

        def __enter__(self):
            calls.append(("enter_rls", self.namespace))

        def __exit__(self, exc_type, exc, tb):
            calls.append(("exit_rls", self.namespace))

    class FakeGraph:
        def create_memory(self, *args, **kwargs):
            calls.append(("create", kwargs["namespace"]))
            return {"node_uuid": "node-created", "uri": "core://x"}

    monkeypatch.setattr(mg, "_ensure_db", lambda: None)
    monkeypatch.setattr(mg, "_with_rls_namespace", lambda namespace: FakeContext(namespace))
    monkeypatch.setattr(mg, "_refresh_search_index", lambda node_uuid, ns: calls.append(("refresh", ns)))
    monkeypatch.setattr(mg, "_run", lambda value: value)

    import agent.memory_graph.services.graph as graph_mod
    monkeypatch.setattr(graph_mod, "GraphService", FakeGraph)

    out = json.loads(mg._create({
        "parent_uri": "core://_canary",
        "content": "hello",
        "domain": "core",
        "title": "x",
        "namespace": "cron:db99-canary",
    }))

    assert out["node_uuid"] == "node-created"
    assert calls[:3] == [
        ("enter_rls", "cron:db99-canary"),
        ("create", "cron:db99-canary"),
        ("exit_rls", "cron:db99-canary"),
    ]


def test_create_user_private_path_still_rejects_missing_namespace(monkeypatch):
    import tools.memory_graph_tool as mg

    monkeypatch.setattr(mg, "_ensure_db", lambda: None)
    monkeypatch.setattr(mg, "_get_namespace", lambda: "")

    import agent.request_context as request_context

    request_context.reset_context()

    with pytest.raises(RuntimeError, match="explicit namespace"):
        mg._create({
            "parent_uri": "core://用户档案",
            "content": "private learning memory",
            "domain": "core",
            "title": "test",
        })


def test_search_logs_access_for_returned_nodes(monkeypatch):
    import tools.memory_graph_tool as mg

    calls = []

    class FakeIndexer:
        def search(self, *args, **kwargs):
            calls.append(("search", args, kwargs))
            return [
                {"node_uuid": "node-1", "uri": "core://x", "path": "x", "priority": 0},
                {"uri": "core://missing-node", "path": "missing", "priority": 0},
            ]

    class FakeGraph:
        def log_access(self, node_uuid, namespace="", context=None):
            calls.append(("log_access", node_uuid, namespace, context))
            return "logged"

    monkeypatch.setattr(mg, "_ensure_db", lambda: None)
    monkeypatch.setattr(mg, "_get_namespace", lambda: "telegram:u1")
    monkeypatch.setattr(mg, "_run", lambda value: value)

    import agent.memory_graph.services.search as search_mod
    import agent.memory_graph.services.graph as graph_mod
    monkeypatch.setattr(search_mod, "SearchIndexer", FakeIndexer)
    monkeypatch.setattr(graph_mod, "GraphService", FakeGraph)

    out = json.loads(mg._search({"query": "student alpha", "domain": "core", "limit": 2}))

    assert out["count"] == 2
    assert ("log_access", "node-1", "telegram:u1", "tool_search") in calls
    assert not any(call[0] == "log_access" and call[1] == "" for call in calls)
