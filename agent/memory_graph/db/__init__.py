"""Database session management for Memory Graph.

Provides async SQLAlchemy session factory using PostgreSQL.
Shares the same database as Hindsight (default: hindsight DB).
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from . import models as Base  # noqa: F401 — ensure models are loaded

logger = logging.getLogger(__name__)

# Do not default to the postgres superuser: PostgreSQL RLS is bypassed by superusers.
# The mg_app role is created by the patch installer/runtime hardening step and uses
# app.current_namespace/app.is_admin for tenant isolation.
DEFAULT_DB_URL = "postgresql+asyncpg://mg_app@127.0.0.1/hindsight"

_engine = None
_session_factory = None


def _read_env_file_value(key: str) -> str:
    """Read a single key from ~/.hermes/.env without logging secrets."""
    env_path = Path.home() / ".hermes" / ".env"
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except Exception as exc:
        logger.debug("Failed to read Memory Graph env key %s: %s", key, exc, exc_info=True)
    return ""


def get_db_url() -> str:
    """Get database URL from environment or the least-privileged mg_app role."""
    explicit = os.environ.get("MEMORY_GRAPH_DB_URL")
    if explicit:
        return explicit
    password = os.environ.get("MEMORY_GRAPH_DB_PASSWORD") or _read_env_file_value("MEMORY_GRAPH_DB_PASSWORD")
    if password:
        return f"postgresql+asyncpg://mg_app:{quote_plus(password)}@127.0.0.1/hindsight"
    return DEFAULT_DB_URL


def _read_config_memory_graph() -> dict:
    """Best-effort read of ~/.hermes/config.yaml memory_graph section."""
    cfg_path = Path.home() / ".hermes" / "config.yaml"
    try:
        import yaml
        data = yaml.safe_load(cfg_path.read_text()) or {}
        mg = data.get("memory_graph") or {}
        return mg if isinstance(mg, dict) else {}
    except Exception as exc:
        logger.debug("Failed to read memory_graph config section: %s", exc, exc_info=True)
        return {}


def _current_rls_context() -> Tuple[str, bool]:
    """Return (namespace, is_admin) for the current request/session.

    Falls back to memory_graph.default_terminal_user for CLI sessions so terminal
    reads/writes do not silently run as shared core with a blank namespace.
    """
    namespace = os.environ.get("MEMORY_GRAPH_NAMESPACE", "")
    is_admin = os.environ.get("MEMORY_GRAPH_IS_ADMIN", "").lower() in {"1", "true", "yes"}

    try:
        from agent.request_context import get_context
        ctx = get_context()
        if ctx:
            namespace = namespace or ctx.namespace
            is_admin = is_admin or bool(ctx.is_admin)
    except Exception as exc:
        logger.debug("RequestContext unavailable while resolving Memory Graph RLS context: %s", exc, exc_info=True)

    mg_cfg = _read_config_memory_graph()
    if not namespace:
        default_user = str(mg_cfg.get("default_terminal_user") or "").strip()
        if default_user:
            namespace = f"telegram:{default_user}"
    admin_ids = set(str(x) for x in (mg_cfg.get("admin_platform_ids") or []))
    # Config stores admin IDs as platform:id (e.g. telegram:735...), while
    # namespace is the same string for DM users. Keep this exact and explicit;
    # an empty namespace must not accidentally become admin.
    if namespace and namespace in admin_ids:
        is_admin = True
    return namespace, is_admin


async def _apply_rls_context(session: AsyncSession) -> None:
    """Set PostgreSQL session variables consumed by RLS policies."""
    namespace, is_admin = _current_rls_context()
    await session.execute(text("SELECT set_app_context(:namespace, :is_admin)"), {
        "namespace": namespace,
        "is_admin": is_admin,
    })


class _ContextSession:
    """Async context manager that applies RLS context before exposing a session."""

    def __init__(self, commit_on_exit: bool = False):
        if _session_factory is None:
            raise RuntimeError("Memory Graph DB not initialized. Call init_db() first.")
        self._session = _session_factory()
        self._commit_on_exit = commit_on_exit

    async def __aenter__(self) -> AsyncSession:
        await self._session.__aenter__()
        await _apply_rls_context(self._session)
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None and self._commit_on_exit:
            await self._session.commit()
        return await self._session.__aexit__(exc_type, exc, tb)


async def init_db(db_url: str = None) -> None:
    """Initialize the async engine and create tables if needed."""
    global _engine, _session_factory
    url = db_url or get_db_url()
    from sqlalchemy.pool import NullPool
    _engine = create_async_engine(url, echo=False, poolclass=NullPool)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    # Create tables
    async with _engine.begin() as conn:
        from .models import Base as ModelBase
        await conn.run_sync(ModelBase.metadata.create_all)

    # Ensure root node exists
    async with _session_factory() as session:
        from .models import ROOT_NODE_UUID, Node
        from sqlalchemy import select
        result = await session.execute(select(Node).where(Node.uuid == ROOT_NODE_UUID))
        if result.scalar_one_or_none() is None:
            session.add(Node(uuid=ROOT_NODE_UUID))
            await session.commit()
            logger.info("Created root node %s", ROOT_NODE_UUID)

    logger.info("Memory Graph DB initialized: %s", url.split("@")[-1] if "@" in url else url)


async def close_db() -> None:
    """Dispose the engine."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_session():
    """Get an RLS-scoped async session. Use as async context manager."""
    return _ContextSession(commit_on_exit=False)


def get_session_no_commit():
    """Get an RLS-scoped session that does NOT auto-commit on __aexit__."""
    return _ContextSession(commit_on_exit=False)


def get_engine():
    """Get the underlying async engine."""
    if _engine is None:
        raise RuntimeError("Memory Graph DB not initialized. Call init_db() first.")
    return _engine
