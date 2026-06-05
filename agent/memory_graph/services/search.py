# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOperatorIssue=false, reportReturnType=false

"""
Search Indexer and Query Engine for Memory Graph System.

PostgreSQL full-text search using tsvector + ts_rank_cd with BM25-style
ranking.  Falls back to ILIKE for very short queries (< 3 chars) where
websearch_to_tsquery produces empty tsqueries.
"""

from typing import Optional, Dict, Any, List, TYPE_CHECKING

from sqlalchemy import select, delete, text, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    Memory,
    Edge,
    Path,
    GlossaryKeyword,
    SearchDocument,
    escape_like_literal,
)
from ..db import get_session
from .search_terms import build_document_search_terms, expand_query_terms

if TYPE_CHECKING:
    from collections.abc import Callable, AsyncIterator
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession


class SearchIndexer:
    """Search index maintenance and query engine (PostgreSQL tsvector + ILIKE fallback)."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session
        self.db_type = "postgresql"

    def _optional_session(self, session: Optional[AsyncSession]):
        if session is not None:
            class _ExistingSession:
                async def __aenter__(self_inner):
                    return session
                async def __aexit__(self_inner, exc_type, exc, tb):
                    return False
            return _ExistingSession()
        return self._session_factory()

    # -----------------------------------------------------------------
    # Query helpers (stateless)
    # -----------------------------------------------------------------

    @staticmethod
    def _format_search_snippet(content: str, query: str) -> str:
        """Build a short content snippet around the first literal hit or token hit."""
        if not content:
            return ""

        content_lower = content.lower()
        query_lower = query.lower()

        pos = content_lower.find(query_lower)
        match_len = len(query)

        if pos < 0:
            tokens = expand_query_terms(query).split()
            for token in tokens:
                if not token:
                    continue
                pos = content_lower.find(token.lower())
                if pos >= 0:
                    match_len = len(token)
                    break

        if pos < 0:
            fallback = content[:80]
            return fallback + ("..." if len(content) > 80 else "")

        start = max(0, pos - 30)
        end = min(len(content), pos + match_len + 30)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        return prefix + content[start:end] + suffix

    # -----------------------------------------------------------------
    # Index maintenance
    # -----------------------------------------------------------------

    async def _build_search_documents_for_node(
        self, session: AsyncSession, node_uuid: str, *, namespace: str = "", search_all_namespaces: bool = False
    ) -> List[Dict[str, Any]]:
        """Materialize search rows for every reachable path of a node."""
        memory = (
            await session.execute(
                select(Memory)
                .where(Memory.node_uuid == node_uuid, Memory.deprecated == False)
                .limit(1)
            )
        ).scalar_one_or_none()
        if not memory:
            return []

        path_stmt = (
            select(Path.namespace, Path.domain, Path.path, Edge.priority, Edge.disclosure)
            .select_from(Path)
            .join(Edge, Path.edge_id == Edge.id)
            .where(Path.node_uuid == node_uuid)
        )
        if not search_all_namespaces:
            path_stmt = path_stmt.where(
                or_(Path.namespace == namespace, Path.namespace == "", Path.namespace.is_(None))
            )
        path_stmt = path_stmt.order_by(Path.domain, Path.path)
        path_rows = (await session.execute(path_stmt)).all()
        if not path_rows:
            return []

        keyword_stmt = select(GlossaryKeyword.keyword, GlossaryKeyword.namespace).where(
            GlossaryKeyword.node_uuid == node_uuid
        )
        if not search_all_namespaces:
            keyword_stmt = keyword_stmt.where(
                or_(GlossaryKeyword.namespace == namespace, GlossaryKeyword.namespace == "", GlossaryKeyword.namespace.is_(None))
            )

        keyword_rows = await session.execute(keyword_stmt)

        from collections import defaultdict
        keywords_by_ns = defaultdict(list)
        for kw, ns in keyword_rows:
            if kw:
                keywords_by_ns[ns].append(kw)

        documents = []
        for row in path_rows:
            uri = f"{row.domain}://{row.path}"
            ns_keywords = keywords_by_ns.get(row.namespace, [])
            glossary_text = " ".join(sorted(ns_keywords))
            documents.append(
                {
                    "namespace": row.namespace,
                    "domain": row.domain,
                    "path": row.path,
                    "node_uuid": node_uuid,
                    "memory_id": memory.id,
                    "uri": uri,
                    "content": memory.content,
                    "disclosure": row.disclosure,
                    "search_terms": build_document_search_terms(
                        row.path,
                        uri,
                        memory.content,
                        row.disclosure,
                        glossary_text,
                    ),
                    "priority": row.priority,
                }
            )
        return documents

    async def _delete_search_documents_for_node(
        self, session: AsyncSession, node_uuid: str, *, namespace: str = "", search_all_namespaces: bool = False
    ) -> None:
        """Remove derived search rows for a node."""
        if not search_all_namespaces:
            await session.execute(
                delete(SearchDocument).where(
                    SearchDocument.node_uuid == node_uuid,
                    SearchDocument.namespace == namespace,
                )
            )
        else:
            await session.execute(
                delete(SearchDocument).where(SearchDocument.node_uuid == node_uuid)
            )

    async def _insert_search_documents(
        self, session: AsyncSession, documents: List[Dict[str, Any]]
    ) -> None:
        """Insert fresh derived search rows for one node."""
        if not documents:
            return
        session.add_all(SearchDocument(**doc) for doc in documents)
        await session.flush()

    async def refresh_search_documents_for_node(
        self, node_uuid: str, session: Optional[AsyncSession] = None, namespace: str = "", refresh_all_namespaces: bool = False
    ) -> None:
        """Rebuild derived search rows for one node."""
        owns_session = session is None
        async with self._optional_session(session) as session:
            documents = await self._build_search_documents_for_node(
                session, node_uuid, namespace=namespace, search_all_namespaces=refresh_all_namespaces
            )
            await self._delete_search_documents_for_node(
                session, node_uuid, namespace=namespace, search_all_namespaces=refresh_all_namespaces
            )
            await self._insert_search_documents(session, documents)
            if owns_session:
                await session.commit()

    async def get_node_uuids_for_prefix(
        self, session: AsyncSession, domain: str, base_path: str, namespace: str = ""
    ) -> List[str]:
        """Collect unique node UUIDs for a path and all descendants."""
        safe = escape_like_literal(base_path)
        result = await session.execute(
            select(Path.node_uuid)
            .where(Path.namespace == namespace)
            .where(Path.domain == domain)
            .where(
                or_(
                    Path.path == base_path,
                    Path.path.like(f"{safe}/%", escape="\\"),
                )
            )
            .distinct()
        )
        return [row[0] for row in result.all()]

    async def rebuild_all_search_documents(
        self, session: Optional[AsyncSession] = None
    ) -> None:
        """Fully rebuild the derived search index from live graph state."""
        async with self._optional_session(session) as session:
            await session.execute(delete(SearchDocument))

            result = await session.execute(
                select(Path.node_uuid).distinct()
            )
            for (node_uuid,) in result.all():
                documents = await self._build_search_documents_for_node(
                    session, node_uuid, search_all_namespaces=True
                )
                await self._insert_search_documents(session, documents)

    # -----------------------------------------------------------------
    # Public search API (PostgreSQL tsvector + ILIKE fallback)
    # -----------------------------------------------------------------

    # Columns that form the tsvector search text
    _SEARCH_TEXT_EXPR = (
        "coalesce(sd.path, '') || ' ' || "
        "coalesce(sd.uri, '') || ' ' || "
        "coalesce(sd.content, '') || ' ' || "
        "coalesce(sd.disclosure, '') || ' ' || "
        "coalesce(sd.search_terms, '')"
    )

    @staticmethod
    def _to_or_tsquery(normalized_query: str) -> str:
        """Convert normalized whitespace-delimited tokens into a safe OR tsquery.

        PostgreSQL websearch/plainto parsing effectively behaves too narrowly for
        multi-facet memory questions: one unrelated token can make a stored fact
        disappear. Memory recall should prefer broad candidate retrieval followed
        by ranking, so we OR unique sanitized tokens here.
        """
        tokens = []
        seen = set()
        for raw in (normalized_query or "").split():
            token = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
            if not token or token in seen:
                continue
            seen.add(token)
            tokens.append(token)
        return " | ".join(tokens)

    async def search(
        self, query: str, limit: int = 10, domain: Optional[str] = None, namespace: str = ""
    ) -> List[Dict[str, Any]]:
        """Search memories using PostgreSQL tsvector with broad candidate recall.

        Multi-token memory questions are converted into an OR tsquery so a
        canonical fact can still surface when the user's message contains
        several facets. Ranking, path priority, and snippets decide the final
        order. Very short / unsafely tokenized queries fall back to ILIKE.
        """
        if not query.strip():
            return []

        # Normalize query for tsvector
        normalized = expand_query_terms(query)
        or_ts_query = self._to_or_tsquery(normalized)

        # For very short queries or empty tokenization, fall back to ILIKE
        use_ilike = len(query.strip()) < 3 or not or_ts_query

        async with self._session_factory() as session:
            if use_ilike:
                # ILIKE fallback for short queries
                like_pattern = f"%{query}%"
                ilike_cond = or_(
                    SearchDocument.content.ilike(like_pattern),
                    SearchDocument.path.ilike(like_pattern),
                    SearchDocument.uri.ilike(like_pattern),
                    SearchDocument.search_terms.ilike(like_pattern),
                    SearchDocument.disclosure.ilike(like_pattern),
                )
                stmt = (
                    select(SearchDocument)
                    .where(or_(SearchDocument.namespace == namespace, SearchDocument.namespace == "", SearchDocument.namespace.is_(None)))
                    .where(ilike_cond)
                    .order_by(SearchDocument.priority.asc())
                    .limit(limit * 5)
                )
                if domain is not None:
                    stmt = stmt.where(SearchDocument.domain == domain)
                result = await session.execute(stmt)
                rows = result.scalars().all()
            else:
                # tsvector full-text search with broad OR ranking
                search_text = self._SEARCH_TEXT_EXPR
                domain_clause = ""
                params: dict = {"namespace": namespace, "ts_query": or_ts_query, "raw_query": query, "candidate_limit": limit * 5}
                if domain is not None:
                    domain_clause = "AND sd.domain = :domain"
                    params["domain"] = domain

                result = await session.execute(
                    text(
                        f"""
                        SELECT
                            sd.domain,
                            sd.path,
                            sd.node_uuid,
                            sd.uri,
                            sd.priority,
                            sd.content,
                            sd.disclosure,
                            ts_rank_cd(
                                to_tsvector('simple', {search_text}),
                                to_tsquery('simple', :ts_query)
                            ) AS score,
                            CASE
                                WHEN sd.namespace = :namespace AND sd.namespace <> '' THEN 0
                                WHEN sd.namespace = '' OR sd.namespace IS NULL THEN 1
                                ELSE 2
                            END AS namespace_rank
                        FROM {SearchDocument.__tablename__} AS sd
                        WHERE (sd.namespace = :namespace OR sd.namespace = '' OR sd.namespace IS NULL)
                          AND to_tsvector('simple', {search_text})
                              @@ to_tsquery('simple', :ts_query)
                          {domain_clause}
                        ORDER BY
                            CASE WHEN sd.path ILIKE '%' || :raw_query || '%' OR sd.content ILIKE '%' || :raw_query || '%' THEN 0 ELSE 1 END ASC,
                            namespace_rank ASC,
                            score DESC,
                            CASE
                                WHEN sd.path LIKE '用户档案%' THEN 0
                                WHEN sd.path LIKE '项目%' THEN 1
                                WHEN sd.path LIKE '系统架构%' THEN 2
                                WHEN sd.path LIKE '工具与配置%' THEN 3
                                WHEN sd.path LIKE '经验教训%' THEN 4
                                ELSE 5
                            END ASC,
                            sd.priority ASC,
                            char_length(sd.path) ASC
                        LIMIT :candidate_limit
                        """
                    ),
                    params,
                )
                rows = result.all()

            # Determine result type
            is_tsvector = not use_ilike

            # Deduplicate by node_uuid
            matches = []
            seen_nodes: set = set()
            for row in rows:
                if is_tsvector:
                    mapping = row._mapping
                    node_uuid = mapping.get("node_uuid")
                else:
                    mapping = None
                    node_uuid = row.node_uuid
                if node_uuid in seen_nodes:
                    continue
                seen_nodes.add(node_uuid)

                if mapping is not None:
                    # RowProxy (tsvector path)
                    matches.append({
                        "domain": mapping["domain"],
                        "path": mapping["path"],
                        "uri": mapping["uri"],
                        "name": mapping["path"].rsplit("/", 1)[-1],
                        "snippet": self._format_search_snippet(mapping["content"], query),
                        "priority": mapping["priority"],
                        "disclosure": mapping["disclosure"],
                        "score": float(mapping.get("score", 0)),
                    })
                else:
                    # ORM object (ILIKE path)
                    matches.append({
                        "domain": row.domain,
                        "path": row.path,
                        "uri": row.uri,
                        "name": row.path.rsplit("/", 1)[-1],
                        "snippet": self._format_search_snippet(row.content, query),
                        "priority": row.priority,
                        "disclosure": row.disclosure,
                    })

            terms = [t for t in expand_query_terms(query).split() if len(t) >= 2]

            def _path_rank(path: str) -> int:
                if path.startswith("用户档案"):
                    return 0
                if path.startswith("项目"):
                    return 1
                if path.startswith("系统架构"):
                    return 2
                if path.startswith("工具与配置"):
                    return 3
                if path.startswith("经验教训"):
                    return 4
                return 5

            def _semantic_rank(item: Dict[str, Any]):
                hay = f"{item.get('uri','')} {item.get('path','')} {item.get('snippet','')}".lower()
                hit_count = sum(1 for t in terms if t.lower() in hay)
                long_hit_count = sum(1 for t in terms if len(t) >= 4 and t.lower() in hay)
                exact_phrase = 1 if query.strip().lower() in hay else 0
                return (
                    -exact_phrase,
                    -long_hit_count,
                    -hit_count,
                    -float(item.get("score", 0) or 0),
                    _path_rank(str(item.get("path", ""))),
                    int(item.get("priority", 0) or 0),
                    len(str(item.get("path", ""))),
                )

            matches.sort(key=_semantic_rank)
            return matches[:limit]
