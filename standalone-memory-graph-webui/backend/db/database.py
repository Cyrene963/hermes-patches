# pyright: reportArgumentType=false, reportCallIssue=false

"""
Database connection and session management.

PostgreSQL-only with asyncpg. Uses NullPool for lightweight async connections.
"""

import os
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text, select
from sqlalchemy.pool import NullPool

from .models import Base, Node, ROOT_NODE_UUID


DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1/hindsight"


def _resolve_database_url() -> str:
    """Resolve Memory Graph database URL.

    Prefer an explicit DATABASE_URL.  Otherwise use the least-privileged
    mg_app role when MEMORY_GRAPH_DB_PASSWORD is available.  The old
    postgres:postgres fallback is kept only for pristine local development.
    """
    if url := os.environ.get("DATABASE_URL"):
        return url
    if pw := os.environ.get("MEMORY_GRAPH_DB_PASSWORD"):
        from urllib.parse import quote_plus
        return f"postgresql+asyncpg://mg_app:{quote_plus(pw)}@127.0.0.1/hindsight"
    return DEFAULT_DB_URL


def _current_rls_context() -> tuple[str, bool]:
    """Return (namespace, is_admin) for the active request context."""
    from .namespace import get_namespace, get_is_admin
    ns = get_namespace()
    is_admin = get_is_admin()
    return ns, is_admin


class DatabaseManager:
    """Async database connection manager.

    Provides session lifecycle management (commit/rollback) and migration
    running.  All business-logic services receive a ``DatabaseManager``
    via constructor injection and pull ``session`` / ``_optional_session``
    from it.
    """

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or _resolve_database_url()
        self.db_type = "postgresql"

        engine_kwargs = {
            "echo": False,
            "poolclass": NullPool,
            "pool_pre_ping": True,
        }

        self.engine = create_async_engine(self.database_url, **engine_kwargs)

        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    @asynccontextmanager
    async def session(self):
        """Get an async session context manager.

        Every session sets PostgreSQL RLS context from the current WebUI
        request namespace before running business queries. Without this,
        mg_app is correctly least-privileged but ordinary users hit 500s or
        empty/denied results because current_setting('app.current_namespace')
        is unset.
        """
        async with self.async_session() as session:
            try:
                from sqlalchemy import text
                ns, is_admin = _current_rls_context()
                await session.execute(
                    text("SELECT set_app_context(:namespace, :is_admin)"),
                    {"namespace": ns, "is_admin": is_admin},
                )
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def _optional_session(self, session: Optional[AsyncSession] = None):
        """Helper to use an existing session or create a new one."""
        if session:
            yield session
        else:
            async with self.session() as new_session:
                yield new_session

    async def init_db(self):
        """Create tables if they don't exist and bootstrap the global root node."""
        from sqlalchemy import inspect as sa_inspect

        def check_initialized(connection):
            return sa_inspect(connection).has_table("memories")

        async with self.engine.begin() as conn:
            is_initialized = await conn.run_sync(check_initialized)
            if not is_initialized:
                await conn.run_sync(Base.metadata.create_all)

        async with self.async_session() as session:
            await session.execute(
                text("SELECT set_app_context(:namespace, :is_admin)"),
                {"namespace": "", "is_admin": True},
            )
            result = await session.execute(select(Node).where(Node.uuid == ROOT_NODE_UUID))
            if result.scalar_one_or_none() is None:
                session.add(Node(uuid=ROOT_NODE_UUID))
                await session.commit()

    async def close(self):
        """Close the database connection."""
        await self.engine.dispose()
