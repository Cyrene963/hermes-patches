"""Multi-namespace support for Memory Graph.

Namespaces provide isolation between different agents, users, or contexts.
Each namespace has its own path tree, glossary keywords, and search index,
while sharing the same underlying Node/Memory/Edge graph.

Key design:
- Path table has composite PK (namespace, domain, path)
- Same node can have paths in multiple namespaces
- Search and glossary are namespace-scoped
- Cross-namespace search available via search_all_namespaces=True
"""

import logging
from typing import Dict, Any, List, Optional

from sqlalchemy import select, func, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Path, Edge, Memory, GlossaryKeyword, SearchDocument, Node, ROOT_NODE_UUID
from ..db import get_session

logger = logging.getLogger(__name__)


class NamespaceService:
    """Namespace management and cross-namespace operations."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session

    async def list_namespaces(self) -> List[Dict[str, Any]]:
        """List all namespaces with their path counts and last activity."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    Path.namespace,
                    func.count(Path.path).label("path_count"),
                    func.max(Path.created_at).label("last_created"),
                )
                .group_by(Path.namespace)
                .order_by(func.count(Path.path).desc())
            )
            return [
                {
                    "namespace": ns or "",
                    "path_count": cnt,
                    "last_activity": last.isoformat() if last else None,
                }
                for ns, cnt, last in result.all()
            ]

    async def get_namespace_stats(self, namespace: str = "") -> Dict[str, Any]:
        """Get detailed stats for a specific namespace."""
        async with self._session_factory() as session:
            # Path count
            path_cnt = await session.execute(
                select(func.count()).select_from(Path).where(Path.namespace == namespace)
            )
            # Domain breakdown
            domain_result = await session.execute(
                select(Path.domain, func.count(Path.path))
                .where(Path.namespace == namespace)
                .group_by(Path.domain)
            )
            domains = {d: c for d, c in domain_result.all()}

            # Glossary keyword count
            kw_cnt = await session.execute(
                select(func.count()).select_from(GlossaryKeyword)
                .where(GlossaryKeyword.namespace == namespace)
            )

            # Search document count
            doc_cnt = await session.execute(
                select(func.count()).select_from(SearchDocument)
                .where(SearchDocument.namespace == namespace)
            )

            return {
                "namespace": namespace or "(default)",
                "path_count": path_cnt.scalar(),
                "domains": domains,
                "glossary_keywords": kw_cnt.scalar(),
                "search_documents": doc_cnt.scalar(),
            }

    async def copy_namespace(self, source: str, target: str,
                              overwrite: bool = False) -> Dict[str, Any]:
        """Copy all paths from one namespace to another.

        Useful for creating per-user copies of a shared namespace.
        """
        async with self._session_factory() as session:
            # Get source paths
            result = await session.execute(
                select(Path).where(Path.namespace == source)
            )
            source_paths = result.scalars().all()

            copied = 0
            skipped = 0
            for sp in source_paths:
                # Check if target path already exists
                existing = await session.execute(
                    select(Path).where(
                        Path.namespace == target,
                        Path.domain == sp.domain,
                        Path.path == sp.path,
                    )
                )
                if existing.scalar_one_or_none():
                    if not overwrite:
                        skipped += 1
                        continue
                    await existing.scalar_one().delete()

                # Copy
                new_path = Path(
                    namespace=target, domain=sp.domain, path=sp.path,
                    edge_id=sp.edge_id, node_uuid=sp.node_uuid,
                )
                session.add(new_path)
                copied += 1

            # Copy glossary keywords
            kw_result = await session.execute(
                select(GlossaryKeyword).where(GlossaryKeyword.namespace == source)
            )
            kw_copied = 0
            for kw in kw_result.scalars().all():
                existing_kw = await session.execute(
                    select(GlossaryKeyword).where(
                        GlossaryKeyword.namespace == target,
                        GlossaryKeyword.keyword == kw.keyword,
                        GlossaryKeyword.node_uuid == kw.node_uuid,
                    )
                )
                if existing_kw.scalar_one_or_none():
                    continue
                session.add(GlossaryKeyword(
                    keyword=kw.keyword, node_uuid=kw.node_uuid, namespace=target,
                ))
                kw_copied += 1

            await session.commit()

            return {
                "source": source, "target": target,
                "paths_copied": copied, "paths_skipped": skipped,
                "glossary_copied": kw_copied,
            }

    async def delete_namespace(self, namespace: str, confirm: bool = False) -> Dict[str, Any]:
        """Delete all data in a namespace. Requires confirm=True.

        Does NOT delete shared Node/Memory/Edge data — only namespace-specific
        paths, glossary keywords, and search documents.
        """
        if not confirm:
            return {"error": "Set confirm=True to delete namespace data"}

        async with self._session_factory() as session:
            # Count before delete
            path_cnt = await session.execute(
                select(func.count()).select_from(Path).where(Path.namespace == namespace)
            )
            paths = path_cnt.scalar()

            kw_cnt = await session.execute(
                select(func.count()).select_from(GlossaryKeyword)
                .where(GlossaryKeyword.namespace == namespace)
            )
            keywords = kw_cnt.scalar()

            doc_cnt = await session.execute(
                select(func.count()).select_from(SearchDocument)
                .where(SearchDocument.namespace == namespace)
            )
            docs = doc_cnt.scalar()

            # Delete
            await session.execute(delete(Path).where(Path.namespace == namespace))
            await session.execute(delete(GlossaryKeyword).where(GlossaryKeyword.namespace == namespace))
            await session.execute(delete(SearchDocument).where(SearchDocument.namespace == namespace))

            await session.commit()

            return {
                "deleted_namespace": namespace or "(default)",
                "paths_deleted": paths,
                "glossary_deleted": keywords,
                "search_docs_deleted": docs,
            }

    async def cross_namespace_search(self, query: str, limit: int = 20,
                                      domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search across ALL namespaces."""
        from .search import SearchIndexer, _format_snippet
        search = SearchIndexer(self._session_factory)

        async with self._session_factory() as session:
            tokens = [t for t in query.lower().strip().split() if t]
            if not tokens:
                return []

            conditions = [SearchDocument.search_terms.ilike(f"%{t}%") for t in tokens]
            stmt = select(SearchDocument).where(and_(*conditions))
            if domain:
                stmt = stmt.where(SearchDocument.domain == domain)
            stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            docs = result.scalars().all()

            return [
                {
                    "node_uuid": doc.node_uuid,
                    "namespace": doc.namespace or "(default)",
                    "domain": doc.domain,
                    "path": doc.path,
                    "uri": doc.uri or f"{doc.domain}://{doc.path}",
                    "snippet": _format_snippet(doc.content, query),
                }
                for doc in docs
            ]
