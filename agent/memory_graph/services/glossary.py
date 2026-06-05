"""Glossary Service — keyword-to-node bindings with Aho-Corasick scanning.

When a keyword appears in conversation or memory content, the glossary
surfaces the associated node for context injection.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional

from sqlalchemy import select, delete, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Node, Path, Memory, GlossaryKeyword
from ..db import get_session

logger = logging.getLogger(__name__)


class GlossaryService:
    """Keyword binding and content scanning service."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session
        self._automaton = None
        self._keyword_map: Dict[str, List[str]] = {}  # keyword → [node_uuid, ...]

    async def add_keyword(self, keyword: str, node_uuid: str,
                           namespace: str = "") -> Dict[str, Any]:
        """Bind a keyword to a node."""
        async with self._session_factory() as session:
            # Verify node exists
            node_result = await session.execute(select(Node).where(Node.uuid == node_uuid))
            if not node_result.scalar_one_or_none():
                raise ValueError(f"Node not found: {node_uuid}")

            kw = GlossaryKeyword(
                keyword=keyword.lower().strip(),
                node_uuid=node_uuid,
                namespace=namespace,
            )
            session.add(kw)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return {"keyword": keyword, "node_uuid": node_uuid, "status": "already_exists"}

            self._automaton = None  # invalidate cache
            return {"keyword": keyword, "node_uuid": node_uuid, "status": "added"}

    async def remove_keyword(self, keyword: str, node_uuid: str,
                              namespace: str = "") -> bool:
        """Remove a keyword binding."""
        async with self._session_factory() as session:
            result = await session.execute(
                delete(GlossaryKeyword).where(
                    GlossaryKeyword.keyword == keyword.lower().strip(),
                    GlossaryKeyword.node_uuid == node_uuid,
                    GlossaryKeyword.namespace == namespace,
                )
            )
            await session.commit()
            if result.rowcount > 0:
                self._automaton = None
                return True
            return False

    async def get_keywords_for_node(self, node_uuid: str,
                                     namespace: str = "") -> List[Dict[str, Any]]:
        """Get all keywords bound to a node."""
        async with self._session_factory() as session:
            stmt = select(GlossaryKeyword).where(GlossaryKeyword.node_uuid == node_uuid)
            if namespace:
                stmt = stmt.where(GlossaryKeyword.namespace == namespace)
            result = await session.execute(stmt)
            return [
                {"keyword": kw.keyword, "node_uuid": kw.node_uuid, "namespace": kw.namespace}
                for kw in result.scalars().all()
            ]

    async def scan_content(self, content: str, namespace: str = "") -> List[Dict[str, Any]]:
        """Scan content for glossary keywords and return matching nodes."""
        automaton = await self._get_automaton(namespace)
        if automaton:
            return self._scan_with_automaton(content, automaton)
        return await self._scan_naive(content, namespace)

    async def _get_automaton(self, namespace: str = ""):
        """Get or build Aho-Corasick automaton for fast multi-pattern matching."""
        if self._automaton is not None:
            return self._automaton

        try:
            import ahocorasick
        except ImportError:
            logger.debug("pyahocorasick not installed, using naive scanning")
            return None

        async with self._session_factory() as session:
            stmt = select(GlossaryKeyword.keyword, GlossaryKeyword.node_uuid)
            if namespace:
                stmt = stmt.where(GlossaryKeyword.namespace == namespace)
            result = await session.execute(stmt)
            pairs = result.all()

        if not pairs:
            return None

        automaton = ahocorasick.Automaton()
        self._keyword_map = {}
        for keyword, node_uuid in pairs:
            kw_lower = keyword.lower()
            automaton.add_word(kw_lower, (kw_lower, node_uuid))
            self._keyword_map.setdefault(kw_lower, []).append(node_uuid)

        try:
            automaton.make_automaton()
        except Exception:
            logger.warning("Failed to build Aho-Corasick automaton")
            return None

        self._automaton = automaton
        return automaton

    def _scan_with_automaton(self, content: str, automaton) -> List[Dict[str, Any]]:
        """Scan content using Aho-Corasick automaton."""
        content_lower = content.lower()
        matches = {}
        for end_pos, (keyword, node_uuid) in automaton.iter(content_lower):
            if keyword not in matches:
                start = max(0, end_pos - len(keyword) - 20)
                end = min(len(content), end_pos + 20)
                matches[keyword] = {
                    "keyword": keyword,
                    "node_uuid": node_uuid,
                    "context": content[start:end],
                    "position": end_pos - len(keyword) + 1,
                }
        return list(matches.values())

    async def _scan_naive(self, content: str, namespace: str = "") -> List[Dict[str, Any]]:
        """Fallback: naive keyword scanning without Aho-Corasick."""
        async with self._session_factory() as session:
            stmt = select(GlossaryKeyword.keyword, GlossaryKeyword.node_uuid)
            if namespace:
                stmt = stmt.where(GlossaryKeyword.namespace == namespace)
            result = await session.execute(stmt)
            pairs = result.all()

        content_lower = content.lower()
        matches = {}
        for keyword, node_uuid in pairs:
            kw_lower = keyword.lower()
            if kw_lower in content_lower and kw_lower not in matches:
                pos = content_lower.find(kw_lower)
                start = max(0, pos - 20)
                end = min(len(content), pos + len(kw_lower) + 20)
                matches[kw_lower] = {
                    "keyword": kw_lower,
                    "node_uuid": node_uuid,
                    "context": content[start:end],
                    "position": pos,
                }
        return list(matches.values())
