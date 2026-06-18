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

from .models import (
    Memory,
    Edge,
    Path,
    GlossaryKeyword,
    SearchDocument,
    escape_like_literal,
)
from .search_terms import build_document_search_terms, expand_query_terms

if TYPE_CHECKING:
    from .database import DatabaseManager


class SearchIndexer:
    """Search index maintenance and query engine (PostgreSQL tsvector + ILIKE fallback)."""

    def __init__(self, db: "DatabaseManager"):
        self._session = db.session
        self._optional_session = db._optional_session
        self.db_type = db.db_type

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
            path_stmt = path_stmt.where(Path.namespace == namespace)
        path_stmt = path_stmt.order_by(Path.domain, Path.path)
        path_rows = (await session.execute(path_stmt)).all()
        if not path_rows:
            return []

        keyword_stmt = select(GlossaryKeyword.keyword, GlossaryKeyword.namespace).where(
            GlossaryKeyword.node_uuid == node_uuid
        )
        if not search_all_namespaces:
            keyword_stmt = keyword_stmt.where(GlossaryKeyword.namespace == namespace)

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
        async with self._optional_session(session) as session:
            documents = await self._build_search_documents_for_node(
                session, node_uuid, namespace=namespace, search_all_namespaces=refresh_all_namespaces
            )
            await self._delete_search_documents_for_node(
                session, node_uuid, namespace=namespace, search_all_namespaces=refresh_all_namespaces
            )
            await self._insert_search_documents(session, documents)

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

    async def search(
        self, query: str, limit: int = 10, domain: Optional[str] = None, namespace: str = ""
    ) -> List[Dict[str, Any]]:
        """Search memories using PostgreSQL tsvector with ts_rank_cd ranking.

        Uses websearch_to_tsquery('simple', ...) for query parsing (supports
        quoted phrases, AND/OR operators, minus exclusion).  Falls back to
        ILIKE for very short queries (< 3 chars) where tsvector produces
        empty tsqueries.
        """
        if not query.strip():
            return []

        # Normalize query for tsvector
        normalized = expand_query_terms(query)

        # For very short queries, fall back to ILIKE
        use_ilike = len(query.strip()) < 3

        async with self._session() as session:
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
                    select(SearchDocument, Memory.security_level)
                    .outerjoin(Memory, Memory.id == SearchDocument.memory_id)
                    .where(SearchDocument.namespace == namespace)
                    .where(ilike_cond)
                    .order_by(
                    SearchDocument.path.ilike(f'%{query}%').desc(),
                    SearchDocument.priority.asc()
                )
                    .limit(limit * 5)
                )
                if domain is not None:
                    stmt = stmt.where(SearchDocument.domain == domain)
                result = await session.execute(stmt)
                rows = result.all()
            else:
                # tsvector full-text search with ranking
                domain_clause = ""
                params: dict = {"namespace": namespace, "ts_query": normalized, "candidate_limit": limit * 5}
                # Extract first meaningful token for entity matching
                import jieba as _jieba
                tokens = [t for t in _jieba.cut(query.strip()) if len(t) > 1]
                params["exact_entity"] = tokens[0] if tokens else query.strip()
                if domain is not None:
                    domain_clause = "AND sd.domain = :domain"
                    params["domain"] = domain

                result = await session.execute(
                    text(
                        f"""
                        SELECT
                            sd.namespace,
                            sd.domain,
                            sd.path,
                            sd.node_uuid,
                            sd.uri,
                            sd.priority,
                            sd.content,
                            sd.disclosure,
                            COALESCE(m.security_level, 'public') AS security_level,
                            ts_rank_cd(
                                sd.search_vector,
                                plainto_tsquery('simple', :ts_query)
                            ) AS score
                        FROM {SearchDocument.__tablename__} AS sd
                        LEFT JOIN {Memory.__tablename__} AS m ON m.id = sd.memory_id
                        WHERE sd.namespace = :namespace
                          AND sd.search_vector
                              @@ plainto_tsquery('simple', :ts_query)
                          {domain_clause}
                        ORDER BY
                            CASE
                                WHEN sd.path LIKE '%/' || :exact_entity THEN 0
                                WHEN sd.path LIKE '用户档案/%' || :exact_entity || '%' THEN 1
                                WHEN sd.path LIKE '用户档案%' THEN 2
                                WHEN sd.path LIKE '项目%' THEN 3
                                WHEN sd.path LIKE '系统架构%' THEN 4
                                WHEN sd.path LIKE '工具与配置%' THEN 5
                                WHEN sd.path LIKE '经验教训%' THEN 6
                                ELSE 7
                            END ASC,
                            score DESC,
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
                    m = row._mapping
                    node_uuid = m.get("node_uuid")
                else:
                    doc, _security_level = row
                    node_uuid = doc.node_uuid
                if node_uuid in seen_nodes:
                    continue
                seen_nodes.add(node_uuid)

                if is_tsvector:
                    # RowProxy (tsvector path)
                    matches.append({
                        "domain": m["domain"],
                        "path": m["path"],
                        "uri": m["uri"],
                        "namespace": m.get("namespace", namespace),
                        "visibility_label": "Shared" if m.get("namespace", namespace) == "" else "Private",
                        "security_level": m.get("security_level", "public"),
                        "name": m["path"].rsplit("/", 1)[-1],
                        "snippet": self._format_search_snippet(m["content"], query),
                        "priority": m["priority"],
                        "disclosure": m["disclosure"],
                        "score": float(m.get("score", 0)),
                    })
                else:
                    doc, security_level = row
                    # ORM tuple (ILIKE path)
                    row_namespace = doc.namespace or ""
                    matches.append({
                        "domain": doc.domain,
                        "path": doc.path,
                        "uri": doc.uri,
                        "namespace": row_namespace,
                        "visibility_label": "Shared" if row_namespace == "" else "Private",
                        "security_level": security_level or "public",
                        "name": doc.path.rsplit("/", 1)[-1],
                        "snippet": self._format_search_snippet(doc.content, query),
                        "priority": doc.priority,
                        "disclosure": doc.disclosure,
                    })
                if len(matches) >= limit:
                    break

            return matches
