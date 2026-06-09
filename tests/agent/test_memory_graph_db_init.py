import importlib
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_init_db_uses_admin_rls_context_for_root_bootstrap(monkeypatch):
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

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    def fake_sessionmaker(*args, **kwargs):
        return lambda: FakeSession()

    monkeypatch.setattr(db, "create_async_engine", lambda *args, **kwargs: FakeEngine())
    monkeypatch.setattr(db, "async_sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(db, "get_db_url", lambda: "postgresql+asyncpg://mg_app@127.0.0.1/hindsight")

    await db.init_db()

    assert any(
        "set_app_context" in statement and params == {"namespace": "", "is_admin": True}
        for statement, params in executed
    )
    assert added
    assert committed
