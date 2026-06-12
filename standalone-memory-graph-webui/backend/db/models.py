# pyright: reportArgumentType=false, reportAttributeAccessIssue=false

"""
ORM Models and shared utilities for Memory Graph System.

Graph-based memory storage with:
- Node: a conceptual entity (UUID), version-independent
- Memory: a content version of a node
- Edge: parent→child relationship between nodes, carrying metadata
- Path: materialized URI cache (domain://path → edge)
"""

from datetime import datetime, timezone
from typing import Dict, Any, List

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    Computed,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# Sentinel root node — parent_uuid of all top-level edges.
ROOT_NODE_UUID = "00000000-0000-0000-0000-000000000000"


# =============================================================================
# Shared Utilities
# =============================================================================


def escape_like_literal(value: str) -> str:
    """Escape special chars in SQL LIKE patterns for literal matching."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def serialize_row(obj) -> Dict[str, Any]:
    """Convert an ORM model instance to a plain dict for snapshot storage."""
    d = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d


def serialize_memory_ref(obj) -> Dict[str, Any]:
    """Serialize a Memory row as a pointer (no content).

    The actual content stays in the DB and is resolved at review time.
    """
    d = serialize_row(obj)
    d.pop("content", None)
    return d


# =============================================================================
# ORM Models
# =============================================================================


def _utcnow():
    return datetime.now(timezone.utc)


class Node(Base):
    """A conceptual entity whose UUID persists across content versions."""

    __tablename__ = "mg_nodes"

    uuid = Column(String(36), primary_key=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)

    memories = relationship("Memory", back_populates="node")
    child_edges = relationship(
        "Edge", foreign_keys="Edge.child_uuid", back_populates="child_node"
    )
    parent_edges = relationship(
        "Edge", foreign_keys="Edge.parent_uuid", back_populates="parent_node"
    )


class Memory(Base):
    """A single content version of a node."""

    __tablename__ = "mg_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_uuid = Column(String(36), ForeignKey("mg_nodes.uuid"), nullable=True)
    content = Column(Text, nullable=False)
    deprecated = Column(Boolean, default=False)
    migrated_to = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    security_level = Column(String(32), nullable=True, default="public")

    node = relationship("Node", back_populates="memories")


class Edge(Base):
    """Directed parent→child relationship between two nodes."""

    __tablename__ = "mg_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_uuid = Column(String(36), ForeignKey("mg_nodes.uuid"), nullable=False)
    child_uuid = Column(String(36), ForeignKey("mg_nodes.uuid"), nullable=False)
    name = Column(String(256), nullable=False)
    priority = Column(Integer, default=0)
    disclosure = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("parent_uuid", "child_uuid", name="uq_edge_parent_child"),
    )

    parent_node = relationship(
        "Node", foreign_keys=[parent_uuid], back_populates="parent_edges"
    )
    child_node = relationship(
        "Node", foreign_keys=[child_uuid], back_populates="child_edges"
    )
    paths = relationship("Path", back_populates="edge")


class Path(Base):
    """Materialized URI cache: (namespace, domain, path_string) → edge."""

    __tablename__ = "mg_paths"

    namespace = Column(String(64), primary_key=True, default="")
    domain = Column(String(64), primary_key=True, default="core")
    path = Column(String(512), primary_key=True)
    edge_id = Column(Integer, ForeignKey("mg_edges.id"), nullable=True)
    node_uuid = Column(
        String(36),
        ForeignKey("mg_nodes.uuid"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    edge = relationship("Edge", back_populates="paths")
    node = relationship("Node")


class GlossaryKeyword(Base):
    """Glossary keyword-to-node binding."""

    __tablename__ = "mg_glossary_keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(Text, nullable=False)
    node_uuid = Column(
        String(36),
        ForeignKey("mg_nodes.uuid", ondelete="CASCADE"),
        nullable=False,
    )
    namespace = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("keyword", "node_uuid", "namespace", name="uq_glossary_keyword_node"),
    )

    node = relationship("Node")


class SearchDocument(Base):
    """Derived search row for one reachable path of an active node."""

    __tablename__ = "mg_search_documents"

    namespace = Column(String(64), primary_key=True, default="")
    domain = Column(String(64), primary_key=True, default="core")
    path = Column(String(512), primary_key=True)
    node_uuid = Column(
        String(36),
        ForeignKey("mg_nodes.uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    memory_id = Column(
        Integer,
        ForeignKey("mg_memories.id", ondelete="CASCADE"),
        nullable=False,
    )
    uri = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    disclosure = Column(Text, nullable=True)
    search_terms = Column(Text, nullable=False, default="")
    priority = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), default=_utcnow)
    search_vector = Column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(path, '') || ' ' || coalesce(uri, '') || ' ' || coalesce(content, '') || ' ' || coalesce(disclosure, '') || ' ' || coalesce(search_terms, ''))",
            persisted=True,
        ),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_mg_search_vector_gin", search_vector, postgresql_using="gin"),
    )


class MemoryAccessLog(Base):
    """Asynchronous access log for tracking memory reading frequency."""

    __tablename__ = "mg_access_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_uuid = Column(
        String(36),
        ForeignKey("mg_nodes.uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    namespace = Column(String(64), nullable=False, default="")
    accessed_at = Column(DateTime(timezone=True), default=_utcnow, index=True)
    context = Column(String(64), nullable=True)

    node = relationship("Node")


# =============================================================================
# Change Collector
# =============================================================================


class ChangeCollector:
    """Accumulates serialized row data before mutations for changeset recording."""

    def __init__(self):
        self.nodes: List[Dict[str, Any]] = []
        self.memories: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []
        self.paths: List[Dict[str, Any]] = []
        self.glossary_keywords: List[Dict[str, Any]] = []

    def record(self, table: str, row_data: Dict[str, Any]):
        if table == "memories":
            row_data = {k: v for k, v in row_data.items() if k != "content"}
        getattr(self, table).append(row_data)

    def to_dict(self) -> Dict[str, list]:
        return {
            "nodes": self.nodes,
            "memories": self.memories,
            "edges": self.edges,
            "paths": self.paths,
            "glossary_keywords": self.glossary_keywords,
        }
