"""
Browse API - Clean URI-based memory navigation

This replaces the old Entity/Relation/Chapter conceptual split with a simple
hierarchical browser. Every path is just a node with content and children.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import config
from db import get_graph_service, get_glossary_service, get_db_manager, get_search_indexer
from db.models import Path as PathModel, Edge as EdgeModel, ROOT_NODE_UUID
from db.namespace import get_namespace
from sqlalchemy import select, distinct

router = APIRouter(prefix="/api/browse", tags=["browse"])


class NodeUpdate(BaseModel):
    content: str | None = None
    priority: int | None = None
    disclosure: str | None = None


class GlossaryAdd(BaseModel):
    keyword: str
    node_uuid: str


class GlossaryRemove(BaseModel):
    keyword: str
    node_uuid: str


@router.get("/namespaces")
async def list_namespaces():
    """Return all distinct namespaces that exist in the paths table.

    Used by the Admin Dashboard namespace selector so the user can switch
    between agent memory spaces without knowing the exact strings upfront.
    An empty-string namespace is returned as "" and corresponds to the
    default (single-agent) namespace.
    """
    db = get_db_manager()
    async with db.session() as session:
        result = await session.execute(
            select(distinct(PathModel.namespace)).order_by(PathModel.namespace)
        )
        return [row[0] for row in result.all()]


@router.get("/domains")
async def list_domains():
    """Return all domains that contain at least one root-level path."""
    from sqlalchemy import func, distinct

    db = get_db_manager()
    async with db.session() as session:
        result = await session.execute(
            select(
                PathModel.domain,
                func.count(distinct(PathModel.path)).label("node_count"),
            )
            .where(PathModel.namespace == get_namespace())
            .where(~PathModel.path.contains("/"))
            .group_by(PathModel.domain)
            .order_by(PathModel.domain)
        )
        return [
            {"domain": row.domain, "root_count": row.node_count}
            for row in result.all()
        ]


@router.get("/node")
async def get_node(
    path: str = Query("", description="URI path like 'nocturne' or 'nocturne/salem'"),
    domain: str = Query("core"),
    uri: Optional[str] = Query(None, description="Optional full URI like 'core://nocturne/salem'"),
    nav_only: bool = Query(False, description="Skip expensive processing if only navigating tree")
):
    """
    Get a node's content and its direct children.
    
    This is the only read endpoint you need - it gives you:
    - The current node's full content (or virtual root)
    - Preview of all children (next level)
    - Breadcrumb trail for navigation
    """
    if uri:
        if "://" not in uri:
            raise HTTPException(status_code=422, detail="Invalid uri; expected domain://path")
        domain, path = uri.split("://", 1)
        path = path.strip("/")
    graph = get_graph_service()
    
    if not path:
        # Check if there is an actual memory stored at the root path
        memory = await graph.get_memory_by_path("", domain=domain, namespace=get_namespace())
        
        children_raw = await graph.get_children(
            ROOT_NODE_UUID,
            context_domain=domain,
            context_path=path,
            namespace=get_namespace()
        )
        
        if memory:
            # Hide the actual root node from the root directory listing.
            children_raw = [
                c for c in children_raw
                if c.get("node_uuid") != memory["node_uuid"]
            ]
        else:
            # Virtual Root Node
            memory = {
                "content": "",
                "priority": 0,
                "disclosure": None,
                "created_at": None,
                "node_uuid": ROOT_NODE_UUID,
            }
            
        breadcrumbs = [{"path": "", "label": "root"}]
    else:
        # Get the node itself
        memory = await graph.get_memory_by_path(path, domain=domain, namespace=get_namespace())
        
        if not memory:
            raise HTTPException(status_code=404, detail=f"Path not found: {domain}://{path}")
        
        children_raw = await graph.get_children(
            memory["node_uuid"],
            context_domain=domain,
            context_path=path,
            namespace=get_namespace()
        )
        
        # Build breadcrumbs
        segments = path.split("/")
        breadcrumbs = [{"path": "", "label": "root"}]
        accumulated = ""
        for seg in segments:
            accumulated = f"{accumulated}/{seg}" if accumulated else seg
            breadcrumbs.append({"path": accumulated, "label": seg})
    
    children = [
        {
            "domain": c["domain"],
            "path": c["path"],
            "uri": f"{c['domain']}://{c['path']}",
            "namespace": c.get("namespace"),
            "visibility_label": "Shared" if c.get("namespace", "") == "" else "Private",
            "security_level": c.get("security_level", "public"),
            "name": c["path"].split("/")[-1],  # Last segment
            "priority": c["priority"],
            "disclosure": c.get("disclosure"),
            "content_snippet": c["content_snippet"],
            "approx_children_count": c.get("approx_children_count", 0)
        }
        for c in children_raw
        if c["domain"] == domain
    ]
    children.sort(key=lambda x: (x["priority"] if x["priority"] is not None else 999, x["path"]))
    
    # Get all aliases (other paths pointing to the same node)
    aliases = []
    if memory.get("node_uuid") and memory["node_uuid"] != ROOT_NODE_UUID:
        async with get_db_manager().session() as session:
            result = await session.execute(
                select(PathModel.domain, PathModel.path)
                .select_from(PathModel)
                .join(EdgeModel, PathModel.edge_id == EdgeModel.id)
                .where(PathModel.namespace == get_namespace())
                .where(EdgeModel.child_uuid == memory["node_uuid"])
            )
            aliases = [
                f"{row[0]}://{row[1]}"
                for row in result.all()
                if not (row[0] == domain and row[1] == path)
            ]
    
    # Get glossary keywords for this node
    glossary_keywords = []
    glossary_matches = []
    node_uuid = memory.get("node_uuid")

    if not nav_only:
        _glossary = get_glossary_service()
        if node_uuid and node_uuid != ROOT_NODE_UUID:
            glossary_keywords = await _glossary.get_glossary_for_node(node_uuid, namespace=get_namespace())

        # Get all glossary matches for the node content using Aho-Corasick
        if memory.get("content"):
            matches_dict = await _glossary.find_glossary_in_content(memory["content"], namespace=get_namespace())
            if matches_dict:
                glossary_matches = [
                    {"keyword": kw, "nodes": nodes}
                    for kw, nodes in matches_dict.items()
                ]

    return {
        "node": {
            "path": path,
            "domain": domain,
            "uri": f"{domain}://{path}",
            "namespace": memory.get("namespace", get_namespace()),
            "visibility_label": "Shared" if memory.get("namespace", get_namespace()) == "" else "Private",
            "security_level": memory.get("security_level", "public"),
            "name": path.split("/")[-1] if path else "root",
            "content": memory["content"],
            "priority": memory["priority"],
            "disclosure": memory["disclosure"],
            "created_at": memory["created_at"],
            "is_virtual": memory.get("created_at") is None,
            "aliases": aliases,
            "node_uuid": node_uuid,
            "glossary_keywords": glossary_keywords,
            "glossary_matches": glossary_matches,
        },
        "children": children,
        "breadcrumbs": breadcrumbs
    }


@router.put("/node")
async def update_node(
    path: str = Query(...),
    domain: str = Query("core"),
    body: NodeUpdate = ...
):
    """
    Update a node's content.
    """
    # Namespace protection: user data cannot be written to core
    ns = get_namespace()
    user_paths = ["用户档案", "user_profile", "个人", "偏好", "成绩", "家庭"]
    if any(p in path for p in user_paths) and not ns:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="User data cannot be written to core namespace")
    
    graph = get_graph_service()
    
    # Check exists
    memory = await graph.get_memory_by_path(path, domain=domain, namespace=get_namespace())
    if not memory:
        raise HTTPException(status_code=404, detail=f"Path not found: {domain}://{path}")
    
    # Update (creates new version if content changed, updates path metadata otherwise)
    try:
        result = await graph.update_memory(
            path=path,
            domain=domain,
            content=body.content,
            priority=body.priority,
            disclosure=body.disclosure,
            namespace=get_namespace(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    
    return {"success": True, "memory_id": result["new_memory_id"]}


# =============================================================================
# Glossary Endpoints
# =============================================================================


@router.get("/glossary")
async def get_glossary():
    """Get all glossary keywords with their associated nodes."""
    glossary = get_glossary_service()
    raw_entries = await glossary.get_all_glossary(namespace=get_namespace(), search_all_namespaces=False)
    
    return {"glossary": raw_entries}


@router.post("/glossary")
async def add_glossary_keyword(body: GlossaryAdd):
    """Bind a keyword to a node."""
    # Human-facing direct edit endpoint: intentionally bypasses changeset/review.
    # The review queue tracks AI-authored mutations only.
    glossary = get_glossary_service()
    try:
        result = await glossary.add_glossary_keyword(body.keyword, body.node_uuid, namespace=get_namespace())
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/glossary")
async def remove_glossary_keyword(body: GlossaryRemove):
    """Remove a keyword binding from a node."""
    # Human-facing direct edit endpoint: intentionally bypasses changeset/review.
    # The review queue tracks AI-authored mutations only.
    glossary = get_glossary_service()
    result = await glossary.remove_glossary_keyword(body.keyword, body.node_uuid, namespace=get_namespace())
    if not result.get("success"):
        raise HTTPException(status_code=404, detail="Keyword binding not found")
    return {"success": True}


# =============================================================================
# Delete Endpoint
# =============================================================================


@router.delete("/node")
async def delete_node(
    path: str = Query(...),
    domain: str = Query("core"),
):
    """
    Delete a memory by removing its URI path.

    Human-facing direct delete: bypasses changeset/review queue.
    Calls graph.remove_path() which handles orphan prevention.
    """
    graph = get_graph_service()

    memory = await graph.get_memory_by_path(path, domain=domain, namespace=get_namespace())
    if not memory:
        raise HTTPException(status_code=404, detail=f"Path not found: {domain}://{path}")

    try:
        await graph.remove_path(path, domain, namespace=get_namespace())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    deleted_uri = f"{domain}://{path}"
    subtree_prefix = deleted_uri + "/"
    ns = get_namespace()
    boot_uris = config.get_boot_uris(ns)
    cleaned = [u for u in boot_uris if u != deleted_uri and not u.startswith(subtree_prefix)]
    if len(cleaned) != len(boot_uris):
        config.set_boot_uris(cleaned, ns)

    return {"success": True, "uri": deleted_uri}


# =============================================================================
# Search Endpoint
# =============================================================================


@router.get("/search")
async def search_memories(
    q: str = Query(..., min_length=1, description="Search query"),
    domain: Optional[str] = Query(None, description="Optional domain filter"),
    limit: int = Query(20, ge=1, le=100),
):
    """Full-text search with entity-anchored query decomposition and intent-aware ranking."""
    import re as _re
    from query_planner import plan_query, get_entity_path
    
    # Strip question marks
    _qstrip = _re.sub(r'[\uff1f?!！]$', '', q.strip())
    _noise = r'(是谁|是什么|怎么样|怎么办|在哪里|什么时候|几岁|多少|怎么|如何|什么样|有没有|是不是|能不能|可以吗|吗|呢|啊|吧|呀)'
    _cleaned = _re.sub(_noise, '', _qstrip).strip()
    q_clean = _cleaned if _cleaned else _qstrip
    
    # Use QueryPlanner to decompose
    plan = plan_query(q_clean)
    search = get_search_indexer()
    ns = get_namespace()
    
    # Inventory query — return empty, let Router handle
    if plan.get('mode') == 'inventory_query':
        return {"query": q_clean, "plan": "inventory_query", "results": [], "count": 0, "note": "Use memory_graph_inventory instead"}
    
    # Search with entity anchoring
    all_results = []
    seen_uris = set()
    entity_path = plan.get('entity_path', '')
    
    for sq in plan['search_queries']:
        results = await search.search(sq, limit=limit * 2, domain=domain, namespace=ns)
        for r in results:
            uri = r.get('uri', '')
            path = r.get('path', '')
            
            # Entity anchoring: if we have an entity_path, filter results
            if entity_path:
                # Boost results within entity subtree
                if path.startswith(entity_path):
                    r['_rank'] = 0  # entity subtree — highest priority
                elif any(e.lower() in path.lower() for e in plan.get('entities', [])):
                    r['_rank'] = 1  # entity-related
                else:
                    r['_rank'] = 2  # unrelated — lower priority
            else:
                r['_rank'] = 2
            
            if uri not in seen_uris:
                seen_uris.add(uri)
                all_results.append(r)
    
    # Sort by rank, then priority
    all_results.sort(key=lambda r: (r.get('_rank', 2), r.get('priority', 99)))
    
    # Remove _rank from output
    for r in all_results:
        r.pop('_rank', None)
    
    return {"query": q_clean, "plan": plan['mode'], "results": all_results[:limit], "count": len(all_results[:limit])}
