# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOperatorIssue=false

"""
Glossary (豆辞典) Service for Nocturne Memory System.

Manages keyword-to-node bindings and provides Aho-Corasick-based
content scanning for keyword highlighting.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Any, List, TYPE_CHECKING

from sqlalchemy import select, delete, and_, func
from sqlalchemy.exc import IntegrityError

from .models import (
    Node,
    Path,
    Memory,
    GlossaryKeyword,
    serialize_row,
)

if TYPE_CHECKING:
    from .database import DatabaseManager
    from .search import SearchIndexer


class GlossaryService:
    """Glossary keyword management and content scanning.

    Maintains an Aho-Corasick automaton for efficient multi-pattern
    matching.  The automaton is rebuilt lazily when the DB fingerprint
    (row count + max id + max created_at) changes.
    """

    def __init__(self, db: "DatabaseManager", search_indexer: "SearchIndexer"):
        self._session = db.session
        self._search = search_indexer
        self._automaton = None
        self._fingerprint = None

    async def add_glossary_keyword(
        self, keyword: str, node_uuid: str, namespace: str = ""
    ) -> Dict[str, Any]:
        """Bind a glossary keyword to a node."""
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Glossary keyword cannot be empty")

        async with self._session() as session:
            node = await session.get(Node, node_uuid)
            if not node:
                raise ValueError(f"Node '{node_uuid}' not found")

            entry = GlossaryKeyword(keyword=keyword, node_uuid=node_uuid, namespace=namespace)
            session.add(entry)

            try:
                await session.flush()
            except IntegrityError:
                raise ValueError(f"Keyword '{keyword}' is already bound to this node")

            await self._search.refresh_search_documents_for_node(
                node_uuid, session=session, namespace=namespace, refresh_all_namespaces=True
            )

            row_after = serialize_row(entry)

            return {
                "id": entry.id,
                "keyword": keyword,
                "node_uuid": node_uuid,
                "rows_before": {"glossary_keywords": []},
                "rows_after": {"glossary_keywords": [row_after]},
            }

    async def remove_glossary_keyword(
        self, keyword: str, node_uuid: str, namespace: str = ""
    ) -> Dict[str, Any]:
        """Remove a glossary keyword binding."""
        keyword = keyword.strip()
        async with self._session() as session:
            existing = await session.execute(
                select(GlossaryKeyword).where(
                    GlossaryKeyword.keyword == keyword,
                    GlossaryKeyword.node_uuid == node_uuid,
                    GlossaryKeyword.namespace == namespace,
                )
            )
            entry = existing.scalar_one_or_none()
            if not entry:
                return {
                    "success": False,
                    "rows_before": {"glossary_keywords": []},
                    "rows_after": {"glossary_keywords": []},
                }

            row_before = serialize_row(entry)

            await session.execute(
                delete(GlossaryKeyword).where(
                    GlossaryKeyword.id == entry.id
                )
            )

            await self._search.refresh_search_documents_for_node(
                node_uuid, session=session, namespace=namespace, refresh_all_namespaces=True
            )

            return {
                "success": True,
                "rows_before": {"glossary_keywords": [row_before]},
                "rows_after": {"glossary_keywords": []},
            }

    async def get_glossary_for_node(self, node_uuid: str, namespace: str = "") -> List[str]:
        """Get all keywords bound to a node."""
        async with self._session() as session:
            result = await session.execute(
                select(GlossaryKeyword.keyword)
                .where(
                    GlossaryKeyword.node_uuid == node_uuid,
                    GlossaryKeyword.namespace == namespace
                )
                .order_by(GlossaryKeyword.keyword)
            )
            return [row[0] for row in result.all()]

    async def get_all_glossary(self, namespace: str = "", search_all_namespaces: bool = False) -> List[Dict[str, Any]]:
        """Get all glossary entries grouped by keyword, with node URIs."""
        async with self._session() as session:
            stmt = (
                select(
                    GlossaryKeyword.keyword,
                    GlossaryKeyword.node_uuid,
                    GlossaryKeyword.namespace,
                    Path.domain,
                    Path.path,
                    Memory.content,
                )
                .select_from(GlossaryKeyword)
            )

            if not search_all_namespaces:
                stmt = stmt.outerjoin(
                    Path,
                    and_(
                        Path.node_uuid == GlossaryKeyword.node_uuid,
                        Path.namespace == namespace,
                    ),
                ).where(GlossaryKeyword.namespace == namespace)
            else:
                stmt = stmt.outerjoin(
                    Path,
                    Path.node_uuid == GlossaryKeyword.node_uuid,
                )

            stmt = stmt.outerjoin(
                Memory,
                and_(
                    Memory.node_uuid == GlossaryKeyword.node_uuid,
                    Memory.deprecated == False,
                ),
            ).order_by(GlossaryKeyword.keyword, Path.domain, Path.path)

            result = await session.execute(stmt)

            groups: Dict[str, Dict[tuple, Dict[str, Any]]] = defaultdict(dict)

            for keyword, node_uuid, namespace, domain, path, content in result.all():
                key = (node_uuid, namespace, domain, path)
                if key not in groups[keyword]:
                    snippet = ""
                    if content:
                        snippet = content[:100].replace("\n", " ")
                        if len(content) > 100:
                            snippet += "..."
                    uri = f"{domain}://{path}" if domain is not None and path is not None else f"unlinked://{node_uuid}"
                    groups[keyword][key] = {
                        "node_uuid": node_uuid,
                        "namespace": namespace,
                        "uri": uri,
                        "content_snippet": snippet,
                    }

            return [
                {"keyword": kw, "nodes": list(node_map.values())}
                for kw, node_map in groups.items()
            ]

    async def find_glossary_in_content(
        self, content: str, namespace: str = ""
    ) -> Dict[str, List[Dict[str, str]]]:
        """Scan content for glossary keywords using Aho-Corasick.

        Uses a DB-level fingerprint (row count + max id + max created_at) to detect staleness,
        so cross-process writes (Web API, rollback, cascade delete) are caught
        without relying on in-process flags.

        Returns dict of keyword -> list of {node_uuid, uri} for matches found.
        """
        import ahocorasick

        async with self._session() as session:
            fp_row = await session.execute(
                select(
                    func.count(GlossaryKeyword.id),
                    func.coalesce(func.max(GlossaryKeyword.id), 0),
                    func.max(GlossaryKeyword.created_at),
                )
            )
            current_fp = tuple(fp_row.one())

        if current_fp[0] == 0:
            self._automaton = None
            self._fingerprint = current_fp
            return {}

        if current_fp != self._fingerprint:
            async with self._session() as session:
                kw_result = await session.execute(
                    select(GlossaryKeyword.keyword).distinct()
                )
                all_keywords = [row[0] for row in kw_result.all()]

            if not all_keywords:
                self._automaton = None
            else:
                automaton = ahocorasick.Automaton()
                for kw in all_keywords:
                    automaton.add_word(kw, kw)
                automaton.make_automaton()
                self._automaton = automaton

            self._fingerprint = current_fp

        if self._automaton is None:
            return {}

        found_keywords: set = set()
        for _, kw in self._automaton.iter(content):
            found_keywords.add(kw)

        if not found_keywords:
            return {}

        async with self._session() as session:
            result = await session.execute(
                select(
                    GlossaryKeyword.keyword,
                    GlossaryKeyword.node_uuid,
                    Path.domain,
                    Path.path,
                )
                .select_from(GlossaryKeyword)
                .join(
                    Path,
                    and_(
                        Path.node_uuid == GlossaryKeyword.node_uuid,
                        Path.namespace == namespace,
                    ),
                )
                .where(
                    GlossaryKeyword.keyword.in_(found_keywords),
                    GlossaryKeyword.namespace == namespace
                )
                .order_by(GlossaryKeyword.keyword, Path.domain, Path.path)
            )

            matches: Dict[str, Dict[str, str]] = defaultdict(dict)
            for keyword, node_uuid, domain, path in result.all():
                if node_uuid not in matches[keyword]:
                    matches[keyword][node_uuid] = f"{domain}://{path}" if domain is not None and path is not None else f"unlinked://{node_uuid}"

            return {
                kw: [
                    {"node_uuid": nid, "uri": uri}
                    for nid, uri in node_map.items()
                ]
                for kw, node_map in matches.items()
            }
