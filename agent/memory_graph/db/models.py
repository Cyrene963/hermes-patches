"""ORM Models for Memory Graph.

Graph-based memory storage with:
- Node: a conceptual entity (UUID), version-independent
- Memory: a content version of a node (1:N)
- Edge: parent→child relationship, carries priority + disclosure
- Path: materialized URI cache (namespace, domain, path) → edge
- GlossaryKeyword: keyword-to-node bindings for trigger scanning
- SearchDocument: derived search index per reachable path
- MemoryAccessLog: access frequency tracking
- Snapshot: changeset before/after state
"""

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, Index, func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(_uuid.uuid4())


ROOT_NODE_UUID = "00000000-0000-0000-0000-000000000000"


def serialize_row(obj) -> dict:
    """Serialize a SQLAlchemy model instance to a dict."""
    if obj is None:
        return {}
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name, None)
        if isinstance(val, datetime):
            val = val.isoformat()
        result[col.name] = val
    return result


def escape_like_literal(s: str) -> str:
    """Escape special LIKE characters for safe use in LIKE patterns."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Base(DeclarativeBase):
    pass


class Node(Base):
    __tablename__ = "mg_nodes"

    uuid = Column(String(36), primary_key=True, default=new_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)

    memories = relationship("Memory", back_populates="node", cascade="all, delete-orphan")
    child_edges = relationship("Edge", foreign_keys="Edge.child_uuid", back_populates="child_node")
    parent_edges = relationship("Edge", foreign_keys="Edge.parent_uuid", back_populates="parent_node")


class Memory(Base):
    __tablename__ = "mg_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_uuid = Column(String(36), ForeignKey("mg_nodes.uuid", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    deprecated = Column(Boolean, default=False)
    migrated_to = Column(Integer, ForeignKey("mg_memories.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    node = relationship("Node", back_populates="memories")


class Edge(Base):
    __tablename__ = "mg_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_uuid = Column(String(36), ForeignKey("mg_nodes.uuid", ondelete="CASCADE"), nullable=False)
    child_uuid = Column(String(36), ForeignKey("mg_nodes.uuid", ondelete="CASCADE"), nullable=False)
    name = Column(String(256), nullable=False)
    priority = Column(Integer, default=0)
    disclosure = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("parent_uuid", "child_uuid", name="uq_mg_edge_parent_child"),
    )

    parent_node = relationship("Node", foreign_keys=[parent_uuid], back_populates="parent_edges")
    child_node = relationship("Node", foreign_keys=[child_uuid], back_populates="child_edges")
    paths = relationship("Path", back_populates="edge", cascade="all, delete-orphan")


class Path(Base):
    __tablename__ = "mg_paths"

    namespace = Column(String(64), primary_key=True, default="")
    domain = Column(String(64), primary_key=True, default="core")
    path = Column(String(512), primary_key=True)
    edge_id = Column(Integer, ForeignKey("mg_edges.id", ondelete="CASCADE"), nullable=False)
    node_uuid = Column(String(36), ForeignKey("mg_nodes.uuid", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    edge = relationship("Edge", back_populates="paths")
    node = relationship("Node")


class GlossaryKeyword(Base):
    __tablename__ = "mg_glossary_keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(Text, nullable=False)
    node_uuid = Column(String(36), ForeignKey("mg_nodes.uuid", ondelete="CASCADE"), nullable=False)
    namespace = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("keyword", "node_uuid", "namespace", name="uq_mg_glossary_kw_node"),
    )

    node = relationship("Node")


class MemoryAccessLog(Base):
    __tablename__ = "mg_access_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_uuid = Column(String(36), ForeignKey("mg_nodes.uuid", ondelete="CASCADE"), nullable=False, index=True)
    namespace = Column(String(64), nullable=False, default="")
    accessed_at = Column(DateTime(timezone=True), default=utcnow)
    context = Column(String(64), nullable=True)

    node = relationship("Node")


class SearchDocument(Base):
    __tablename__ = "mg_search_documents"

    namespace = Column(String(64), primary_key=True, default="")
    domain = Column(String(64), primary_key=True, default="core")
    path = Column(String(512), primary_key=True)
    node_uuid = Column(String(36), ForeignKey("mg_nodes.uuid", ondelete="CASCADE"), nullable=False, index=True)
    memory_id = Column(Integer, ForeignKey("mg_memories.id", ondelete="CASCADE"), nullable=False)
    uri = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    disclosure = Column(Text, nullable=True)
    search_terms = Column(Text, nullable=False, default="")
    priority = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), default=utcnow)
    search_vector = Column(Text, nullable=True)  # reserved for pg_tsvector


class Snapshot(Base):
    __tablename__ = "mg_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(64), nullable=False, default="")
    node_uuid = Column(String(36), nullable=False)
    uri = Column(Text, nullable=False)
    action = Column(String(32), nullable=False)
    before_content = Column(Text, nullable=True)
    after_content = Column(Text, nullable=True)
    before_meta = Column(Text, nullable=True)  # JSON
    after_meta = Column(Text, nullable=True)   # JSON
    created_at = Column(DateTime(timezone=True), default=utcnow)
    approved = Column(Boolean, nullable=True)
