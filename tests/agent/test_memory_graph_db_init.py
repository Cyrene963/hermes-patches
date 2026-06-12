import asyncio
import importlib
from types import SimpleNamespace


def test_init_db_uses_admin_rls_context_for_root_bootstrap(monkeypatch):
    db = importlib.import_module("agent.memory_graph.db")

    executed = []
    added = []
    committed = []

    class FakeScalar:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement, params=None):
            executed.append((str(statement), params))
            return FakeScalar()

        def add(self, obj):
            added.append(obj)

        async def commit(self):
            committed.append(True)

    class FakeBegin:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def run_sync(self, fn):
            return None

        async def execute(self, statement, params=None):
            executed.append((str(statement), params))

            class FakeResult:
                def first(self_inner):
                    if "information_schema.columns" in str(statement):
                        return ("USER-DEFINED", "tsvector", "ALWAYS")
                    return None

            return FakeResult()

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    def fake_sessionmaker(*args, **kwargs):
        return lambda: FakeSession()

    monkeypatch.setattr(db, "create_async_engine", lambda *args, **kwargs: FakeEngine())
    monkeypatch.setattr(db, "async_sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(db, "get_db_url", lambda: "postgresql+asyncpg://mg_app@127.0.0.1/hindsight")

    asyncio.run(db.init_db())

    assert any(
        "set_app_context" in statement and params == {"namespace": "", "is_admin": True}
        for statement, params in executed
    )
    assert added
    assert committed


def test_graph_create_memory_binds_explicit_namespace_to_rls(monkeypatch):
    graph_mod = importlib.import_module("agent.memory_graph.services.graph")

    events = []

    class FakeContext:
        def __enter__(self):
            events.append(("enter_rls", "cron:service-canary"))

        def __exit__(self, exc_type, exc, tb):
            events.append(("exit_rls", "cron:service-canary"))

    class FakeSession:
        async def __aenter__(self):
            events.append(("enter_session",))
            return self

        async def __aexit__(self, exc_type, exc, tb):
            events.append(("exit_session",))
            return False

        async def commit(self):
            events.append(("commit",))

    async def fake_get_next_child_number(session, parent_uuid):
        return 1

    async def fake_ensure_node(session, node_uuid):
        return SimpleNamespace(uuid=node_uuid)

    async def fake_create_edge_with_paths(session, parent_uuid, child_uuid, title, priority, disclosure, namespace, domain, parent_path):
        return SimpleNamespace(id=1)

    async def fake_insert_memory(session, node_uuid, content):
        return SimpleNamespace(id=7)

    service = graph_mod.GraphService(session_factory=lambda: FakeSession())
    monkeypatch.setattr(service, "_namespace_session", lambda namespace: FakeContext())
    monkeypatch.setattr(service, "_get_next_child_number", fake_get_next_child_number)
    monkeypatch.setattr(service, "_ensure_node", fake_ensure_node)
    monkeypatch.setattr(service, "_create_edge_with_paths", fake_create_edge_with_paths)
    monkeypatch.setattr(service, "_insert_memory", fake_insert_memory)

    result = asyncio.run(service.create_memory(
        "",
        "content",
        title="leaf",
        namespace="cron:service-canary",
        domain="core",
    ))

    assert result["uri"] == "core://leaf"
    assert events[:2] == [("enter_rls", "cron:service-canary"), ("enter_session",)]
    assert events[-2:] == [("exit_session",), ("exit_rls", "cron:service-canary")]


def test_init_db_rebuilds_search_vector_schema(monkeypatch):
    db = importlib.import_module("agent.memory_graph.db")

    executed = []

    class FakeScalar:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement, params=None):
            executed.append((str(statement), params))
            return FakeScalar()

        def add(self, obj):
            pass

        async def commit(self):
            pass

    class FakeBegin:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def run_sync(self, fn):
            return None

        async def execute(self, statement, params=None):
            executed.append((str(statement), params))

            class FakeResult:
                def first(self_inner):
                    if "information_schema.columns" in str(statement):
                        return ("text", "text", "NEVER")
                    return None

            return FakeResult()

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    def fake_sessionmaker(*args, **kwargs):
        return lambda: FakeSession()

    monkeypatch.setattr(db, "create_async_engine", lambda *args, **kwargs: FakeEngine())
    monkeypatch.setattr(db, "async_sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(db, "get_db_url", lambda: "postgresql+asyncpg://mg_app@127.0.0.1/hindsight")

    asyncio.run(db.init_db())

    statements = "\n".join(stmt for stmt, _params in executed)
    assert "ALTER TABLE mg_search_documents DROP COLUMN IF EXISTS search_vector" in statements
    assert "ADD COLUMN search_vector TSVECTOR GENERATED ALWAYS AS" in statements
    assert "CREATE INDEX IF NOT EXISTS ix_mg_search_vector_gin" in statements
