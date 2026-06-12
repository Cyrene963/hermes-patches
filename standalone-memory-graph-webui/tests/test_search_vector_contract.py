import asyncio
import sys
import types
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_standalone_init_db_rebuilds_search_vector_schema(monkeypatch):
    from db.database import DatabaseManager

    executed = []

    class FakeScalar:
        def scalar_one_or_none(self):
            return object()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement, params=None):
            executed.append((str(statement), params))
            return FakeScalar()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    class FakeBegin:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def run_sync(self, fn):
            return True

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

    manager = DatabaseManager.__new__(DatabaseManager)
    manager.engine = FakeEngine()
    manager.async_session = lambda: FakeSession()

    asyncio.run(manager.init_db())

    statements = "\n".join(stmt for stmt, _params in executed)
    assert "ALTER TABLE mg_search_documents DROP COLUMN IF EXISTS search_vector" in statements
    assert "ADD COLUMN search_vector TSVECTOR GENERATED ALWAYS AS" in statements
    assert "CREATE INDEX IF NOT EXISTS ix_mg_search_vector_gin" in statements


def test_standalone_search_uses_generated_search_vector_column():
    if "jieba" not in sys.modules:
        fake_jieba = types.ModuleType("jieba")
        fake_jieba.cut = lambda text: text.split()
        sys.modules["jieba"] = fake_jieba

    from db.search import SearchIndexer

    class FakeSession:
        def __init__(self):
            self.statements = []

        async def execute(self, stmt, params=None):
            self.statements.append((str(stmt), params or {}))

            class Result:
                def all(self):
                    return []

            return Result()

    class FakeDb:
        def __init__(self):
            self.db_type = "postgresql"
            self.fake_session = FakeSession()

        def session(self):
            outer = self

            class Ctx:
                async def __aenter__(self):
                    return outer.fake_session

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            return Ctx()

        def _optional_session(self, session=None):
            return self.session()

    db = FakeDb()
    indexer = SearchIndexer(db)
    asyncio.run(indexer.search("alpha beta gamma", namespace="telegram:u1", limit=3))

    sql, params = db.fake_session.statements[0]
    assert "sd.search_vector" in sql
    assert "to_tsvector('simple'" not in sql
    assert "plainto_tsquery('simple', :ts_query)" in sql
    assert params["ts_query"]
