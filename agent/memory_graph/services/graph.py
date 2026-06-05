"""Graph Service — URI Tree memory operations.

Ported from Nocturne Memory's GraphService with adaptations for Hermes:
- Uses SQLAlchemy async with PostgreSQL (shared with Hindsight)
- Simplified namespace model (single namespace for now)
- Integrated with Hermes memory tool
"""

import uuid as uuid_lib
import logging
from collections import defaultdict
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import random

from sqlalchemy import select, update, delete, func, and_, or_, not_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    ROOT_NODE_UUID, Node, Memory, Edge, Path, GlossaryKeyword,
    MemoryAccessLog, SearchDocument, serialize_row, escape_like_literal,
)
from ..db import get_session

logger = logging.getLogger(__name__)


def _serialize_memory_ref(memory) -> Dict[str, Any]:
    return {
        "id": memory.id,
        "node_uuid": memory.node_uuid,
        "deprecated": memory.deprecated,
        "migrated_to": memory.migrated_to,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
    }


class GraphService:
    """Graph-domain service for memory CRUD, traversal, and path management."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session

    # =====================================================================
    # Row-Level Primitives (Layer 0)
    # =====================================================================

    async def _ensure_node(self, session: AsyncSession, node_uuid: str):
        result = await session.execute(select(Node).where(Node.uuid == node_uuid))
        node = result.scalar_one_or_none()
        if node:
            return node
        node = Node(uuid=node_uuid)
        session.add(node)
        await session.flush()
        return node

    async def _insert_memory(self, session: AsyncSession, node_uuid: str,
                              content: str, *, deprecated: bool = False):
        from .text_patch import normalize_text
        content = normalize_text(content)
        memory = Memory(content=content, node_uuid=node_uuid, deprecated=deprecated)
        session.add(memory)
        await session.flush()
        return memory

    async def _get_or_create_edge(self, session: AsyncSession, parent_uuid: str,
                                   child_uuid: str, name: str, priority: int = 0,
                                   disclosure: Optional[str] = None):
        result = await session.execute(
            select(Edge).where(Edge.parent_uuid == parent_uuid, Edge.child_uuid == child_uuid)
        )
        edge = result.scalar_one_or_none()
        if edge:
            return edge, False
        edge = Edge(parent_uuid=parent_uuid, child_uuid=child_uuid,
                     name=name, priority=priority, disclosure=disclosure)
        session.add(edge)
        await session.flush()
        return edge, True

    async def _insert_path(self, session: AsyncSession, namespace: str, domain: str,
                            path: str, edge_id: int, node_uuid: str):
        p = Path(namespace=namespace, domain=domain, path=path,
                 edge_id=edge_id, node_uuid=node_uuid)
        session.add(p)
        await session.flush()
        return p

    async def _resolve_path(self, session: AsyncSession, namespace: str, domain: str,
                             path: str):
        """Resolve a URI path to (edge, node_uuid) or None."""
        result = await session.execute(
            select(Path).where(
                Path.namespace == namespace, Path.domain == domain, Path.path == path
            )
        )
        p = result.scalar_one_or_none()
        if not p:
            return None
        return {"edge_id": p.edge_id, "node_uuid": p.node_uuid, "path_obj": p}

    async def _count_paths_for_edge(self, session: AsyncSession, edge_id: int) -> int:
        result = await session.execute(
            select(func.count()).select_from(Path).where(Path.edge_id == edge_id)
        )
        return result.scalar() or 0

    async def _count_incoming_paths(self, session: AsyncSession, node_uuid: str) -> int:
        result = await session.execute(
            select(func.count()).select_from(Path).where(Path.node_uuid == node_uuid)
        )
        return result.scalar() or 0

    async def _count_memories_for_node(self, session: AsyncSession, node_uuid: str) -> int:
        result = await session.execute(
            select(func.count()).select_from(Memory).where(
                Memory.node_uuid == node_uuid, Memory.deprecated == False
            )
        )
        return result.scalar() or 0

    async def _get_next_child_number(self, session: AsyncSession, parent_uuid: str) -> int:
        result = await session.execute(
            select(func.count()).select_from(Edge).where(Edge.parent_uuid == parent_uuid)
        )
        return (result.scalar() or 0) + 1

    async def _deprecate_node_memories(self, session: AsyncSession, node_uuid: str):
        await session.execute(
            update(Memory).where(Memory.node_uuid == node_uuid, Memory.deprecated == False)
            .values(deprecated=True)
        )

    # =====================================================================
    # Layer 1: Composite Operations
    # =====================================================================

    async def _cascade_create_paths(self, session: AsyncSession, namespace: str,
                                     domain: str, parent_path: str,
                                     child_edge: Edge, child_node_uuid: str,
                                     title: str):
        """Create path entries for a new child and recursively for its subtree."""
        child_uri = f"{parent_path}/{title}" if parent_path else title
        await self._insert_path(session, namespace, domain, child_uri, child_edge.id, child_node_uuid)

        # Cascade to grandchildren
        grandchild_edges = await session.execute(
            select(Edge).where(Edge.parent_uuid == child_node_uuid)
        )
        for gc_edge in grandchild_edges.scalars().all():
            gc_paths = await session.execute(
                select(Path).where(Path.edge_id == gc_edge.id)
            )
            for gc_path in gc_paths.scalars().all():
                gc_title = gc_edge.name
                new_gc_uri = f"{child_uri}/{gc_title}"
                await self._insert_path(
                    session, namespace, gc_path.domain, new_gc_uri, gc_edge.id, gc_edge.child_uuid
                )

    async def _create_edge_with_paths(self, session: AsyncSession, parent_uuid: str,
                                       child_uuid: str, name: str, priority: int,
                                       disclosure: Optional[str], namespace: str,
                                       domain: str, parent_path: str):
        """Create an edge and all its path entries."""
        edge, created = await self._get_or_create_edge(
            session, parent_uuid, child_uuid, name, priority, disclosure
        )
        if created:
            await self._cascade_create_paths(
                session, namespace, domain, parent_path, edge, child_uuid, name
            )
        return edge

    async def _delete_subtree_paths(self, session: AsyncSession, node_uuid: str,
                                     namespace: str, domain: str):
        """Delete all path entries in a subtree rooted at node_uuid."""
        # Get all edges where this node is parent
        edges = await session.execute(
            select(Edge).where(Edge.parent_uuid == node_uuid)
        )
        for edge in edges.scalars().all():
            # Delete paths for this edge
            await session.execute(
                delete(Path).where(Path.edge_id == edge.id)
            )
            # Recurse
            await self._delete_subtree_paths(session, edge.child_uuid, namespace, domain)

    async def _cascade_delete_edge(self, session: AsyncSession, edge: Edge,
                                    namespace: str, domain: str):
        """Delete an edge and clean up orphaned nodes."""
        child_uuid = edge.child_uuid
        parent_uuid = edge.parent_uuid

        # Delete paths for this edge
        await session.execute(delete(Path).where(Path.edge_id == edge.id))
        # Delete subtree paths
        await self._delete_subtree_paths(session, child_uuid, namespace, domain)

        # Delete the edge
        await session.delete(edge)
        await session.flush()

        # GC: if child has no more incoming paths and no memories, delete it
        incoming = await self._count_incoming_paths(session, child_uuid)
        if incoming == 0:
            mem_count = await self._count_memories_for_node(session, child_uuid)
            if mem_count == 0:
                # Delete all edges where child is parent (orphans)
                orphan_edges = await session.execute(
                    select(Edge).where(Edge.parent_uuid == child_uuid)
                )
                for oe in orphan_edges.scalars().all():
                    await self._cascade_delete_edge(session, oe, namespace, domain)
                # Delete the node
                await session.execute(delete(Node).where(Node.uuid == child_uuid))

    # =====================================================================
    # Public API
    # =====================================================================

    async def get_memory_by_path(self, path: str, domain: str = "core",
                                   namespace: str = "") -> Optional[Dict[str, Any]]:
        """Read a memory by its URI path."""
        async with self._session_factory() as session:
            resolved = await self._resolve_path(session, namespace, domain, path)
            if not resolved:
                return None

            node_uuid = resolved["node_uuid"]
            # Get active memory
            result = await session.execute(
                select(Memory).where(Memory.node_uuid == node_uuid, Memory.deprecated == False)
                .order_by(Memory.created_at.desc())
            )
            memory = result.scalars().first()
            if not memory:
                return None

            # Get edge for metadata
            edge_result = await session.execute(select(Edge).where(Edge.id == resolved["edge_id"]))
            edge = edge_result.scalar_one_or_none()

            # Get all paths for this node (aliases)
            paths_result = await session.execute(
                select(Path).where(Path.node_uuid == node_uuid)
            )
            aliases = [f"{p.domain}://{p.path}" for p in paths_result.scalars().all()]

            return {
                "node_uuid": node_uuid,
                "memory_id": memory.id,
                "content": memory.content,
                "domain": domain,
                "path": path,
                "uri": f"{domain}://{path}",
                "name": edge.name if edge else path.split("/")[-1],
                "priority": edge.priority if edge else 0,
                "disclosure": edge.disclosure if edge else None,
                "aliases": aliases,
                "created_at": memory.created_at.isoformat() if memory.created_at else None,
            }

    async def get_memory_by_node_uuid(self, node_uuid: str) -> Optional[Dict[str, Any]]:
        """Read a memory by node UUID directly."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.node_uuid == node_uuid, Memory.deprecated == False)
                .order_by(Memory.created_at.desc())
            )
            memory = result.scalars().first()
            if not memory:
                return None

            paths_result = await session.execute(
                select(Path).where(Path.node_uuid == node_uuid)
            )
            paths = paths_result.scalars().all()
            primary_path = paths[0] if paths else None

            return {
                "node_uuid": node_uuid,
                "memory_id": memory.id,
                "content": memory.content,
                "domain": primary_path.domain if primary_path else "core",
                "path": primary_path.path if primary_path else "",
                "uri": f"{primary_path.domain}://{primary_path.path}" if primary_path else "",
                "aliases": [f"{p.domain}://{p.path}" for p in paths],
                "created_at": memory.created_at.isoformat() if memory.created_at else None,
            }

    async def get_children(self, node_uuid: str, domain: str = "core",
                            context_path: Optional[str] = None,
                            namespace: str = "") -> List[Dict[str, Any]]:
        """List children of a node."""
        async with self._session_factory() as session:
            edges = await session.execute(
                select(Edge).where(Edge.parent_uuid == node_uuid)
                .order_by(Edge.priority.desc(), Edge.name)
            )
            children = []
            for edge in edges.scalars().all():
                # Get active memory for child
                mem_result = await session.execute(
                    select(Memory).where(Memory.node_uuid == edge.child_uuid, Memory.deprecated == False)
                    .order_by(Memory.created_at.desc())
                )
                memory = mem_result.scalars().first()

                # Get path for child
                path_result = await session.execute(
                    select(Path).where(Path.edge_id == edge.id, Path.namespace == namespace)
                )
                path_obj = path_result.scalars().first()

                child_path = path_obj.path if path_obj else edge.name
                child_domain = path_obj.domain if path_obj else domain

                children.append({
                    "node_uuid": edge.child_uuid,
                    "name": edge.name,
                    "priority": edge.priority,
                    "disclosure": edge.disclosure,
                    "domain": child_domain,
                    "path": child_path,
                    "uri": f"{child_domain}://{child_path}",
                    "content_snippet": (memory.content[:120] + "...") if memory and len(memory.content) > 120 else (memory.content if memory else ""),
                    "has_memory": memory is not None,
                })

            return children

    async def get_all_paths(self, node_uuid: str, namespace: str = "") -> List[Dict[str, Any]]:
        """Get all path entries for a node."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Path).where(Path.node_uuid == node_uuid)
            )
            return [
                {"namespace": p.namespace, "domain": p.domain, "path": p.path,
                 "uri": f"{p.domain}://{p.path}", "edge_id": p.edge_id}
                for p in result.scalars().all()
            ]

    async def create_memory(self, parent_path: str, content: str,
                              priority: int = 0, title: Optional[str] = None,
                              domain: str = "core", namespace: str = "",
                              disclosure: Optional[str] = None,
                              auto_create_parents: bool = True) -> Dict[str, Any]:
        """Create a new memory node under a parent path.

        If auto_create_parents=True and parent_path contains multiple segments
        (e.g. "a/b/c"), missing intermediate nodes are created automatically.
        """
        async with self._session_factory() as session:
            # Strip domain prefix if parent_path includes it (e.g. "core://项目" → "项目")
            if "://" in parent_path:
                parent_path = parent_path.split("://", 1)[1]
            # Resolve parent — with auto-segmentation
            if parent_path:
                segments = [s for s in parent_path.split("/") if s]
                if auto_create_parents and len(segments) > 1:
                    # Walk from root, creating missing segments
                    parent_uuid = ROOT_NODE_UUID
                    current_path = ""
                    for seg in segments:
                        next_path = f"{current_path}/{seg}" if current_path else seg
                        resolved = await self._resolve_path(session, namespace, domain, next_path)
                        if resolved:
                            parent_uuid = resolved["node_uuid"]
                        else:
                            # Create intermediate node.  Under RLS, mg_memories
                            # visibility is inherited from mg_paths, so create
                            # the edge/path before inserting the node memory.
                            mid_uuid = str(uuid_lib.uuid4())
                            await self._ensure_node(session, mid_uuid)
                            edge, _ = await self._get_or_create_edge(
                                session, parent_uuid, mid_uuid, seg, priority=0
                            )
                            await self._insert_path(session, namespace, domain, next_path, edge.id, mid_uuid)
                            await self._insert_memory(session, mid_uuid, f"[auto-created: {next_path}]")
                            parent_uuid = mid_uuid
                        current_path = next_path
                else:
                    parent_resolved = await self._resolve_path(session, namespace, domain, parent_path)
                    if not parent_resolved:
                        raise ValueError(f"Parent path not found: {domain}://{parent_path}")
                    parent_uuid = parent_resolved["node_uuid"]
            else:
                parent_uuid = ROOT_NODE_UUID

            # Generate title if not provided
            if not title:
                num = await self._get_next_child_number(session, parent_uuid)
                title = f"node-{num}"

            # Create node, path, then memory.  mg_memories RLS derives access
            # from mg_paths; inserting memory before the path exists is rejected
            # for least-privileged mg_app sessions.
            child_uuid = str(uuid_lib.uuid4())
            await self._ensure_node(session, child_uuid)

            # Create edge + paths
            edge = await self._create_edge_with_paths(
                session, parent_uuid, child_uuid, title, priority,
                disclosure, namespace, domain, parent_path
            )
            memory = await self._insert_memory(session, child_uuid, content)

            await session.commit()
            try:
                from .search import SearchIndexer
                await SearchIndexer(self._session_factory).refresh_search_documents_for_node(
                    child_uuid, namespace=namespace
                )
            except Exception as exc:
                logger.warning("Failed to refresh search documents for created memory %s: %s", child_uuid, exc)

            return {
                "node_uuid": child_uuid,
                "memory_id": memory.id,
                "domain": domain,
                "path": f"{parent_path}/{title}" if parent_path else title,
                "uri": f"{domain}://{parent_path}/{title}" if parent_path else f"{domain}://{title}",
                "name": title,
                "priority": priority,
            }

    async def update_memory(self, path: str, content: str,
                              domain: str = "core", namespace: str = "",
                              priority: Optional[int] = None,
                              disclosure: Optional[str] = None) -> Dict[str, Any]:
        """Update a memory's content (creates new version, deprecates old)."""
        async with self._session_factory() as session:
            resolved = await self._resolve_path(session, namespace, domain, path)
            if not resolved:
                raise ValueError(f"Path not found: {domain}://{path}")

            node_uuid = resolved["node_uuid"]

            # Deprecate old memories
            await self._deprecate_node_memories(session, node_uuid)

            # Insert new memory version
            memory = await self._insert_memory(session, node_uuid, content)

            # Update edge metadata if provided
            edge_result = await session.execute(select(Edge).where(Edge.id == resolved["edge_id"]))
            edge = edge_result.scalar_one_or_none()
            if edge:
                if priority is not None:
                    edge.priority = priority
                if disclosure is not None:
                    edge.disclosure = disclosure

            await session.commit()
            try:
                from .search import SearchIndexer
                await SearchIndexer(self._session_factory).refresh_search_documents_for_node(
                    node_uuid, namespace=namespace
                )
            except Exception as exc:
                logger.warning("Failed to refresh search documents for updated memory %s: %s", node_uuid, exc)

            return {
                "node_uuid": node_uuid,
                "memory_id": memory.id,
                "domain": domain,
                "path": path,
                "uri": f"{domain}://{path}",
                "updated": True,
            }

    async def delete_memory(self, path: str, domain: str = "core",
                              namespace: str = "") -> bool:
        """Delete a memory node and its subtree."""
        async with self._session_factory() as session:
            resolved = await self._resolve_path(session, namespace, domain, path)
            if not resolved:
                return False

            edge_id = resolved["edge_id"]
            node_uuid = resolved["node_uuid"]

            # Get the edge
            edge_result = await session.execute(select(Edge).where(Edge.id == edge_id))
            edge = edge_result.scalar_one_or_none()
            if not edge:
                return False

            # Cascade delete
            await self._cascade_delete_edge(session, edge, namespace, domain)

            # Delete memories for this node
            await session.execute(delete(Memory).where(Memory.node_uuid == node_uuid))
            # Delete search docs
            await session.execute(delete(SearchDocument).where(SearchDocument.node_uuid == node_uuid))
            # Delete glossary
            await session.execute(delete(GlossaryKeyword).where(GlossaryKeyword.node_uuid == node_uuid))

            # Check if node is orphaned
            incoming = await self._count_incoming_paths(session, node_uuid)
            if incoming == 0:
                await session.execute(delete(Node).where(Node.uuid == node_uuid))

            await session.commit()
            return True

    async def add_alias(self, path: str, alias_path: str,
                         domain: str = "core", alias_domain: str = "core",
                         namespace: str = "") -> Dict[str, Any]:
        """Add an alias path pointing to an existing node."""
        async with self._session_factory() as session:
            resolved = await self._resolve_path(session, namespace, domain, path)
            if not resolved:
                raise ValueError(f"Path not found: {domain}://{path}")

            node_uuid = resolved["node_uuid"]
            edge_id = resolved["edge_id"]

            # Check alias doesn't already exist
            existing = await self._resolve_path(session, namespace, alias_domain, alias_path)
            if existing:
                raise ValueError(f"Alias path already exists: {alias_domain}://{alias_path}")

            await self._insert_path(session, namespace, alias_domain, alias_path, edge_id, node_uuid)
            await session.commit()

            return {
                "node_uuid": node_uuid,
                "original": f"{domain}://{path}",
                "alias": f"{alias_domain}://{alias_path}",
            }

    async def log_access(self, node_uuid: str, namespace: str = ""):
        """Log memory access for frequency tracking."""
        async with self._session_factory() as session:
            await session.execute(
                update(Node).where(Node.uuid == node_uuid)
                .values(last_accessed_at=datetime.now(timezone.utc))
            )
            session.add(MemoryAccessLog(node_uuid=node_uuid, namespace=namespace))
            await session.commit()

    async def weighted_random_recall(self, namespace: str = "",
                                       domain: str = "core",
                                       limit: int = 5,
                                       stale_days_multiplier: float = 1.0) -> List[Dict[str, Any]]:
        """Recall memories weighted by staleness × priority.

        Stale memories (not accessed recently) get higher weight.
        Priority 0 = 1x, priority 1 = 0.5x, priority 2 = 0.25x.
        Returns a random sample biased toward forgotten-but-important content.
        """
        async with self._session_factory() as session:
            # Get all active nodes with paths
            stmt = (
                select(Node, Edge, Path, Memory)
                .join(Edge, Edge.child_uuid == Node.uuid)
                .join(Path, Path.edge_id == Edge.id)
                .join(Memory, Memory.node_uuid == Node.uuid)
                .where(
                    Memory.deprecated == False,
                    Path.namespace == namespace,
                    Path.domain == domain,
                    Node.uuid != ROOT_NODE_UUID,
                )
            )
            result = await session.execute(stmt)
            rows = result.all()

            if not rows:
                return []

            now = datetime.now(timezone.utc)
            weighted = []
            for node, edge, path, memory in rows:
                # Calculate staleness (days since last access)
                last = node.last_accessed_at or node.created_at
                if last:
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    stale_days = (now - last).days
                else:
                    stale_days = 365

                # Priority weight: lower priority = higher weight (more likely to surface)
                priority_weight = 1.0 / (1.0 + edge.priority * 0.5)

                # Staleness weight
                stale_weight = 1.0 + stale_days * stale_days_multiplier

                weight = priority_weight * stale_weight
                weighted.append({
                    "node_uuid": node.uuid,
                    "name": edge.name,
                    "uri": f"{path.domain}://{path.path}",
                    "content_snippet": memory.content[:150] if memory.content else "",
                    "priority": edge.priority,
                    "stale_days": stale_days,
                    "weight": round(weight, 2),
                })

            # Weighted random sampling
            weights = [w["weight"] for w in weighted]
            total = sum(weights)
            if total == 0:
                return weighted[:limit]

            # Sample without replacement using weights
            selected = []
            remaining = list(range(len(weighted)))
            for _ in range(min(limit, len(remaining))):
                r = random.random() * sum(weights[i] for i in remaining)
                cumulative = 0
                for idx in remaining:
                    cumulative += weights[idx]
                    if cumulative >= r:
                        selected.append(weighted[idx])
                        remaining.remove(idx)
                        break

            return selected

    # =========================================================================
    # Nocturne Memory parity: orphan management, random recall, diagnostics
    # =========================================================================

    async def _resolve_migration_chain(
        self, session: AsyncSession, start_id: int, max_hops: int = 50
    ) -> Optional[Dict[str, Any]]:
        """Follow the migrated_to chain to the final target."""
        current_id = start_id
        for _ in range(max_hops):
            result = await session.execute(
                select(Memory).where(Memory.id == current_id)
            )
            memory = result.scalar_one_or_none()
            if not memory:
                return None
            if memory.migrated_to is None:
                paths = []
                if memory.node_uuid:
                    paths_result = await session.execute(
                        select(Path.domain, Path.path)
                        .where(Path.node_uuid == memory.node_uuid)
                    )
                    paths = list({f"{r[0]}://{r[1]}" for r in paths_result.all()})
                return {
                    "id": memory.id,
                    "content": memory.content,
                    "content_snippet": memory.content[:200] + "..."
                    if len(memory.content) > 200
                    else memory.content,
                    "created_at": memory.created_at.isoformat()
                    if memory.created_at
                    else None,
                    "deprecated": memory.deprecated,
                    "paths": paths,
                }
            current_id = memory.migrated_to
        return None

    async def get_all_orphan_memories(self, namespace: str = "") -> List[Dict[str, Any]]:
        """Get all orphan memories (deprecated=True).

        Two sub-categories:
        - deprecated: migrated_to is set — old version replaced by update_memory
        - orphaned: migrated_to is NULL — node lost all paths
        """
        async with self._session_factory() as session:
            orphans = []
            result = await session.execute(
                select(Memory)
                .where(Memory.deprecated == True)
                .order_by(Memory.created_at.desc())
            )
            for memory in result.scalars().all():
                category = "deprecated" if memory.migrated_to else "orphaned"
                item = {
                    "id": memory.id,
                    "content_snippet": memory.content[:200] + "..."
                    if len(memory.content) > 200
                    else memory.content,
                    "created_at": memory.created_at.isoformat()
                    if memory.created_at
                    else None,
                    "deprecated": True,
                    "migrated_to": memory.migrated_to,
                    "category": category,
                    "migration_target": None,
                }
                if memory.migrated_to:
                    target = await self._resolve_migration_chain(
                        session, memory.migrated_to
                    )
                    if target:
                        item["migration_target"] = {
                            "id": target["id"],
                            "paths": target["paths"],
                            "content_snippet": target["content_snippet"],
                        }
                orphans.append(item)
            return orphans

    async def get_orphan_detail(self, memory_id: int) -> Optional[Dict[str, Any]]:
        """Get full detail of an orphan memory for content viewing and diff."""
        async with self._session_factory() as session:
            result = await session.execute(select(Memory).where(Memory.id == memory_id))
            memory = result.scalar_one_or_none()
            if not memory:
                return None
            if not memory.deprecated:
                category = "active"
            elif memory.migrated_to:
                category = "deprecated"
            else:
                category = "orphaned"
            detail = {
                "id": memory.id,
                "content": memory.content,
                "created_at": memory.created_at.isoformat()
                if memory.created_at
                else None,
                "deprecated": memory.deprecated,
                "migrated_to": memory.migrated_to,
                "category": category,
                "migration_target": None,
            }
            if memory.migrated_to:
                target = await self._resolve_migration_chain(
                    session, memory.migrated_to
                )
                if target:
                    detail["migration_target"] = {
                        "id": target["id"],
                        "content": target["content"],
                        "paths": target["paths"],
                        "created_at": target["created_at"],
                    }
            return detail

    async def permanently_delete_memory(self, memory_id: int) -> Dict[str, Any]:
        """Permanently delete a deprecated memory version.

        Repairs the version chain. Refuses to delete active memories.
        If this was the last memory for the node, hard-GCs the node.
        """
        async with self._session_factory() as session:
            mem_result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            mem = mem_result.scalar_one_or_none()
            if not mem:
                raise ValueError(f"Memory {memory_id} not found")
            if not mem.deprecated:
                raise PermissionError(
                    f"Memory {memory_id} is active. Cannot delete active memories."
                )

            # Repair predecessor pointers
            successor_id = mem.migrated_to
            await session.execute(
                update(Memory)
                .where(Memory.migrated_to == memory_id)
                .values(migrated_to=successor_id)
            )

            # Delete the memory row
            await session.execute(delete(Memory).where(Memory.id == memory_id))

            # If node has no more memories, GC the node
            node_uuid = mem.node_uuid
            remaining_result = await session.execute(
                select(func.count()).select_from(Memory).where(Memory.node_uuid == node_uuid)
            )
            remaining_count = remaining_result.scalar() or 0
            node_gc = None
            if remaining_count == 0:
                # Delete edges and paths, then the node
                await session.execute(
                    delete(Edge).where(
                        or_(Edge.parent_uuid == node_uuid, Edge.child_uuid == node_uuid)
                    )
                )
                await session.execute(delete(Path).where(Path.node_uuid == node_uuid))
                await session.execute(
                    delete(GlossaryKeyword).where(GlossaryKeyword.node_uuid == node_uuid)
                )
                await session.execute(delete(Node).where(Node.uuid == node_uuid))
                node_gc = node_uuid

            await session.commit()
            return {
                "deleted_memory_id": memory_id,
                "chain_repaired_to": successor_id,
                "node_gc": node_gc,
            }

    async def get_random_memory(
        self, namespace: str = "", domain: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Pick a weighted-random memory node.

        Weight = staleness * priority_multiplier.
        Returns dict with node_uuid, uri, priority, last_accessed_at.
        """
        async with self._session_factory() as session:
            stmt = (
                select(
                    Node.uuid,
                    Node.last_accessed_at,
                    Node.created_at,
                    func.min(func.coalesce(Edge.priority, 2)).label("best_priority"),
                )
                .select_from(Path)
                .join(Edge, Path.edge_id == Edge.id)
                .join(Node, Node.uuid == Edge.child_uuid)
                .where(Path.namespace == namespace)
                .where(Node.uuid != ROOT_NODE_UUID)
                .group_by(Node.uuid, Node.last_accessed_at, Node.created_at)
            )
            if domain:
                stmt = stmt.where(Path.domain == domain)
            else:
                stmt = stmt.where(Path.domain != "system")

            result = await session.execute(stmt)
            rows = result.all()
            if not rows:
                return None

            now = datetime.now(timezone.utc)
            weights = []
            for row in rows:
                last = row.last_accessed_at or row.created_at or now
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                stale_days = max((now - last).total_seconds() / 86400.0, 0.5)
                priority = row.best_priority if row.best_priority is not None else 2
                mult = max(0.5 ** max(0, priority), 1e-12)
                weights.append(stale_days * mult)

            chosen = random.choices(rows, weights=weights, k=1)[0]

            # Get a URI for the chosen node
            uri_stmt = (
                select(Path.domain, Path.path)
                .join(Edge, Path.edge_id == Edge.id)
                .where(Edge.child_uuid == chosen.uuid)
                .where(Path.namespace == namespace)
            )
            if domain:
                uri_stmt = uri_stmt.where(Path.domain == domain)
            else:
                uri_stmt = uri_stmt.where(Path.domain != "system")

            uri_result = await session.execute(uri_stmt)
            uri_rows = uri_result.all()
            if not uri_rows:
                return None

            chosen_domain, chosen_path = random.choice(uri_rows)
            return {
                "node_uuid": chosen.uuid,
                "uri": f"{chosen_domain}://{chosen_path}",
                "priority": chosen.best_priority,
                "last_accessed_at": chosen.last_accessed_at.isoformat()
                if chosen.last_accessed_at
                else None,
            }

    async def get_recent_memories(
        self, namespace: str = "", limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recently modified memories with their URIs."""
        async with self._session_factory() as session:
            stmt = (
                select(Node, Memory, Edge, Path)
                .join(Memory, Memory.node_uuid == Node.uuid)
                .join(Edge, Edge.child_uuid == Node.uuid)
                .join(Path, Path.edge_id == Edge.id)
                .where(Memory.deprecated == False)
                .where(Path.namespace == namespace)
                .where(Node.uuid != ROOT_NODE_UUID)
                .order_by(Memory.created_at.desc())
                .limit(limit * 3)  # extra to dedupe
            )
            result = await session.execute(stmt)
            rows = result.all()

            seen = set()
            items = []
            for node, memory, edge, path in rows:
                if node.uuid in seen:
                    continue
                seen.add(node.uuid)
                items.append({
                    "node_uuid": node.uuid,
                    "uri": f"{path.domain}://{path.path}",
                    "priority": edge.priority,
                    "disclosure": edge.disclosure,
                    "created_at": memory.created_at.isoformat()
                    if memory.created_at
                    else None,
                    "content_snippet": memory.content[:150] if memory.content else "",
                })
                if len(items) >= limit:
                    break
            return items

    async def get_diagnostics(
        self,
        namespace: str = "",
        days_stale: int = 30,
        max_children: int = 10,
        priority_thresholds: Dict[int, int] = None,
        domain: str = None,
    ) -> Dict[str, Any]:
        """Diagnostic report: stale nodes, crowded parents, orphaned paths, duplicate aliases."""
        from datetime import timedelta

        if priority_thresholds is None:
            priority_thresholds = {0: 3, 1: 7, 2: 14}

        async with self._session_factory() as session:
            # 1. Stale nodes
            tracking_stmt = select(func.min(Node.last_accessed_at)).where(
                Node.last_accessed_at != None
            )
            tracking_result = await session.execute(tracking_stmt)
            tracking_start_date = tracking_result.scalar_one_or_none()
            if not tracking_start_date:
                tracking_start_date = datetime.now(timezone.utc)

            all_nodes_stmt = (
                select(Path, Node, Edge, Memory)
                .select_from(Path)
                .join(Edge, Path.edge_id == Edge.id)
                .join(Node, Node.uuid == Edge.child_uuid)
                .join(Memory, and_(Memory.node_uuid == Node.uuid, Memory.deprecated == False))
                .where(Path.namespace == namespace)
            )
            if domain:
                all_nodes_stmt = all_nodes_stmt.where(Path.domain == domain)

            all_nodes_result = await session.execute(all_nodes_stmt)
            stale_nodes = {}
            for path_obj, node, edge, memory in all_nodes_result.all():
                if node.last_accessed_at:
                    effective_date = node.last_accessed_at
                else:
                    node_created = node.created_at or datetime.now(timezone.utc)
                    effective_date = max(node_created, tracking_start_date)

                prio = edge.priority if edge.priority is not None else 999
                threshold_days = priority_thresholds.get(prio, days_stale)
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=threshold_days)

                if effective_date < cutoff_date:
                    key = node.uuid
                    existing_prio = 999
                    if key in stale_nodes:
                        existing_val = stale_nodes[key].get("priority")
                        existing_prio = existing_val if existing_val is not None else 999

                    if key not in stale_nodes or prio < existing_prio:
                        stale_days_calc = round(
                            (datetime.now(timezone.utc) - effective_date).total_seconds() / 86400.0, 1
                        )
                        stale_nodes[key] = {
                            "uuid": node.uuid,
                            "uri": f"{path_obj.domain}://{path_obj.path}",
                            "created_at": node.created_at.isoformat() if node.created_at else None,
                            "last_accessed_at": node.last_accessed_at.isoformat() if node.last_accessed_at else None,
                            "stale_days": stale_days_calc,
                            "threshold_days": threshold_days,
                            "priority": edge.priority,
                            "memory_id": memory.id,
                        }

            # 2. Crowded parents
            crowded_stmt = (
                select(Edge.parent_uuid, func.count(Edge.child_uuid.distinct()).label("child_count"))
                .join(Path, Path.edge_id == Edge.id)
                .where(Path.namespace == namespace)
            )
            if domain:
                crowded_stmt = crowded_stmt.where(Path.domain == domain)
            crowded_stmt = crowded_stmt.group_by(Edge.parent_uuid).having(
                func.count(Edge.child_uuid.distinct()) > max_children
            )
            crowded_result = await session.execute(crowded_stmt)

            crowded_parents = {}
            for parent_uuid, count in crowded_result.all():
                if parent_uuid == ROOT_NODE_UUID:
                    crowded_parents[parent_uuid] = {
                        "uuid": parent_uuid,
                        "uri": f"{domain if domain else 'core'}://",
                        "child_count": count,
                    }
                else:
                    path_stmt = select(Path).where(
                        Path.node_uuid == parent_uuid, Path.namespace == namespace
                    )
                    if domain:
                        path_stmt = path_stmt.where(Path.domain == domain)
                    path_stmt = path_stmt.limit(1)
                    path_res = await session.execute(path_stmt)
                    path_obj = path_res.scalar_one_or_none()
                    if path_obj:
                        crowded_parents[parent_uuid] = {
                            "uuid": parent_uuid,
                            "uri": f"{path_obj.domain}://{path_obj.path}",
                            "child_count": count,
                        }

            # 3. Orphaned paths (parent path doesn't exist)
            all_paths_stmt = (
                select(Path.domain, Path.path, Path.node_uuid)
                .where(Path.namespace == namespace)
            )
            if domain:
                all_paths_stmt = all_paths_stmt.where(Path.domain == domain)
            all_paths_result = await session.execute(all_paths_stmt)
            paths_dict = {}
            for d, p, nid in all_paths_result.all():
                paths_dict[(d, p)] = nid

            orphaned_nodes = []
            for (d, p), nid in paths_dict.items():
                if "/" in p:
                    parent_path = p.rsplit("/", 1)[0]
                    if (d, parent_path) not in paths_dict:
                        orphaned_nodes.append({
                            "uuid": nid,
                            "uri": f"{d}://{p}",
                        })

            return {
                "stale_nodes": sorted(
                    list(stale_nodes.values()),
                    key=lambda x: x.get("last_accessed_at") or x.get("created_at") or "",
                ),
                "crowded_nodes": sorted(
                    list(crowded_parents.values()),
                    key=lambda x: x["child_count"],
                    reverse=True,
                ),
                "orphaned_nodes": orphaned_nodes,
            }
