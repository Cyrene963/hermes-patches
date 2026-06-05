"""Standalone web server for Memory Graph dashboard.

Run:  python -m agent.memory_graph.server [--port 8900] [--host 0.0.0.0]
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def create_app(graph_service=None, search_indexer=None, glossary_service=None):
    """Create the full FastAPI app with dashboard + API + auth."""
    try:
        from fastapi import FastAPI, Query, HTTPException, Request, Response, Depends
        from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        logger.error("FastAPI not installed. pip install fastapi uvicorn")
        return None

    from .auth import authenticate, create_session_token, verify_session_token, get_user, USERS_FILE

    # Lazy-init services
    if graph_service is None:
        from .services.graph import GraphService
        graph_service = GraphService()
    if search_indexer is None:
        from .services.search import SearchIndexer
        search_indexer = SearchIndexer()
    if glossary_service is None:
        from .services.glossary import GlossaryService
        glossary_service = GlossaryService()

    from .services.snapshot import ChangesetStore
    changeset_store = ChangesetStore()

    from .db.models import ROOT_NODE_UUID

    app = FastAPI(title="Memory Graph", docs_url="/docs")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    async def health():
        """Unauthenticated liveness endpoint for systemd/watchdogs."""
        return {"status": "healthy", "service": "memory-graph"}

    # ─── Auth helpers ──────────────────────────────────────────────
    COOKIE_NAME = "mg_session"

    def get_current_user(request: Request) -> Optional[dict]:
        """Extract user from session cookie. Returns user dict or None."""
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return None
        username = verify_session_token(token)
        if not username:
            return None
        return get_user(username)

    def require_auth(request: Request) -> dict:
        """Dependency: require valid session. Returns user dict."""
        user = get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        return user

    def require_admin(request: Request) -> dict:
        """Dependency: require admin user."""
        user = get_current_user(request)
        if not user or user.get("username") != "admin":
            raise HTTPException(403, "Admin only")
        return user

    # ─── Login/Logout ──────────────────────────────────────────────
    from .web.dashboard import LOGIN_HTML, DASHBOARD_HTML

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        user = get_current_user(request)
        if user:
            return RedirectResponse("/", status_code=302)
        return LOGIN_HTML

    @app.post("/api/auth/login")
    async def api_login(request: Request, response: Response):
        body = await request.json()
        username = body.get("username", "").strip()
        password = body.get("password", "")
        if not username or not password:
            raise HTTPException(400, "Username and password required")
        user = authenticate(username, password)
        if not user:
            raise HTTPException(401, "Invalid credentials")
        token = create_session_token(username)
        response = JSONResponse({"ok": True, "username": username, "namespace": user.get("namespace", "")})
        response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=86400 * 7, path="/")
        return response

    @app.post("/api/auth/logout")
    async def api_logout(response: Response):
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @app.get("/api/auth/me")
    async def api_me(request: Request):
        user = get_current_user(request)
        if not user:
            return {"authenticated": False}
        return {"authenticated": True, **user}

    # ─── Dashboard ─────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        user = get_current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=302)
        return DASHBOARD_HTML

    # ─── Read API (auth-gated, namespace-filtered) ─────────────────
    @app.get("/api/memory-graph/read")
    async def api_read(request: Request, uri: str = Query(""), domain: str = Query("core")):
        user = require_auth(request)
        ns = user.get("namespace", "")
        if "://" in uri:
            domain, path = uri.split("://", 1)
        else:
            path = uri
        if domain == "system":
            from .services.system_views import handle_system_uri
            return await handle_system_uri(path, graph_service, search_indexer)
        result = await graph_service.get_memory_by_path(path, domain=domain, namespace=ns)
        if result is None:
            raise HTTPException(404, f"Not found: {domain}://{path}")
        if result.get("node_uuid") and result["node_uuid"] != ROOT_NODE_UUID:
            await graph_service.log_access(result["node_uuid"])
        return result

    @app.get("/api/memory-graph/list")
    async def api_list(request: Request, uri: str = Query(""), domain: str = Query("core")):
        user = require_auth(request)
        ns = user.get("namespace", "")
        if "://" in uri:
            domain, path = uri.split("://", 1)
        else:
            path = uri
        if path:
            node = await graph_service.get_memory_by_path(path, domain=domain, namespace=ns)
            if not node:
                raise HTTPException(404, "Not found")
            node_uuid = node["node_uuid"]
        else:
            node_uuid = ROOT_NODE_UUID
        return await graph_service.get_children(node_uuid, domain=domain, context_path=path, namespace=ns)

    @app.get("/api/memory-graph/paths")
    async def api_paths(request: Request, domain: str = Query(None)):
        user = require_auth(request)
        ns = user.get("namespace", "")
        from .db import get_session
        from .db.models import Path
        from sqlalchemy import select
        async with get_session() as session:
            q = select(Path)
            if ns:
                q = q.where(Path.namespace == ns)
            result = await session.execute(q.order_by(Path.namespace, Path.domain, Path.path))
            rows = []
            for row in result.scalars().all():
                if domain and row.domain != domain:
                    continue
                rows.append({
                    "namespace": row.namespace,
                    "domain": row.domain,
                    "path": row.path,
                    "node_uuid": row.node_uuid,
                    "edge_id": row.edge_id,
                })
            return rows

    @app.get("/api/memory-graph/search")
    async def api_search(request: Request, q: str = Query(""), query: str = Query(""),
                          domain: str = Query(None), limit: int = Query(20)):
        user = require_auth(request)
        ns = user.get("namespace", "")
        search_term = q or query
        return await search_indexer.search(search_term, domain=domain, namespace=ns or "", limit=limit)

    # ─── Write API ─────────────────────────────────────────────────
    @app.post("/api/memory-graph/create")
    async def api_create(request: Request):
        user = require_auth(request)
        ns = user.get("namespace", "")
        body = await request.json()
        try:
            result = await graph_service.create_memory(
                parent_path=body.get("parent_uri") or body.get("parent_path", ""),
                content=body["content"],
                priority=body.get("priority", 0),
                title=body.get("title") or None,
                disclosure=body.get("disclosure"),
                domain=body.get("domain", "core"),
                namespace=ns,
            )
            changeset_store.record_change(
                "memories", result["uri"], result["node_uuid"],
                after={"content": body["content"]},
            )
            await search_indexer.refresh_search_documents_for_node(result["node_uuid"], namespace=ns)
            return result
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e))

    @app.put("/api/memory-graph/update")
    async def api_update(request: Request):
        user = require_auth(request)
        ns = user.get("namespace", "")
        body = await request.json()
        try:
            uri = body.get("uri", "")
            domain, path = uri.split("://", 1) if "://" in uri else (body.get("domain", "core"), uri)
            before = await graph_service.get_memory_by_path(path, domain=domain, namespace=ns)
            result = await graph_service.update_memory(
                path=path, content=body.get("content"), priority=body.get("priority"),
                domain=domain, namespace=ns,
            )
            changeset_store.record_change(
                "memories", uri, result.get("node_uuid", ""),
                before={"content": before["content"]} if before else None,
                after={"content": body.get("content")},
            )
            return result
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/memory-graph/delete")
    async def api_delete(request: Request, uri: str = Query(...), domain: str = Query("core")):
        user = require_auth(request)
        ns = user.get("namespace", "")
        if "://" in uri:
            domain, path = uri.split("://", 1)
        else:
            path = uri
        try:
            before = await graph_service.get_memory_by_path(path, domain=domain, namespace=ns)
            node_uuid = before["node_uuid"] if before else ""
            success = await graph_service.delete_memory(path, domain=domain, namespace=ns)
            if not success:
                raise HTTPException(404, f"Not found: {domain}://{path}")
            if node_uuid:
                changeset_store.record_change(
                    "memories", f"{domain}://{path}", node_uuid,
                    before={"content": before["content"]} if before else None,
                    after=None,
                )
            return {"deleted": True, "node_uuid": node_uuid, "uri": f"{domain}://{path}"}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/memory-graph/alias")
    async def api_alias(request: Request):
        user = require_auth(request)
        ns = user.get("namespace", "")
        body = await request.json()
        try:
            return await graph_service.add_alias(
                path=body["new_path"], alias_path=body["target_path"],
                domain=body.get("new_domain", "core"),
                alias_domain=body.get("target_domain", "core"),
                namespace=ns,
            )
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e))

    # ─── Review API ────────────────────────────────────────────────
    @app.get("/api/memory-graph/review/changes")
    async def api_review_changes(request: Request, changeset_id: str = Query("active")):
        require_auth(request)
        return changeset_store.get_changes(changeset_id)

    @app.get("/api/memory-graph/review/list")
    async def api_review_list(request: Request):
        require_auth(request)
        return changeset_store.list_changesets()

    @app.post("/api/memory-graph/review/rollback")
    async def api_review_rollback(request: Request):
        user = require_auth(request)
        ns = user.get("namespace", "")
        body = await request.json()
        try:
            target_id = body["memory_id"]
            from .db import get_session
            from .db.models import Memory
            from sqlalchemy import select
            async with get_session() as session:
                target = await session.get(Memory, target_id)
                if not target:
                    raise HTTPException(404, f"Memory ID {target_id} not found")
                if not target.deprecated:
                    return {"message": "Memory is already active", "memory_id": target_id}
                active_result = await session.execute(
                    select(Memory).where(Memory.node_uuid == target.node_uuid, Memory.deprecated == False)
                )
                for active in active_result.scalars().all():
                    active.deprecated = True
                    active.migrated_to = target_id
                target.deprecated = False
                target.migrated_to = None
                await session.commit()
                await search_indexer.refresh_search_documents_for_node(target.node_uuid, namespace=ns)
                return {"restored_memory_id": target_id, "node_uuid": target.node_uuid}
        except HTTPException:
            raise
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.post("/api/memory-graph/review/approve")
    async def api_review_approve(request: Request):
        require_auth(request)
        body = await request.json()
        changeset_id = body.get("changeset_id", "active")
        changeset_store.clear(changeset_id)
        return {"approved": True, "changeset_id": changeset_id}

    @app.delete("/api/memory-graph/review/clear")
    async def api_review_clear(request: Request, changeset_id: str = Query("active")):
        require_auth(request)
        changeset_store.clear(changeset_id)
        return {"cleared": True}

    # ─── Glossary API ──────────────────────────────────────────────
    @app.post("/api/memory-graph/glossary/add")
    async def api_glossary_add(request: Request):
        require_auth(request)
        body = await request.json()
        try:
            return await glossary_service.add_keyword(
                body["keyword"], body["node_uuid"],
                namespace=body.get("namespace", ""),
            )
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e))

    @app.post("/api/memory-graph/glossary/scan")
    async def api_glossary_scan(request: Request):
        user = require_auth(request)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(422, 'Invalid or empty JSON body')
        if not body or "content" not in body:
            raise HTTPException(422, 'Missing required field: content')
        matches = await glossary_service.scan_content(body["content"])
        from .db import get_session
        from .db.models import Path, Memory
        from sqlalchemy import select
        enriched = []
        ns = user.get("namespace", "")
        async with get_session() as session:
            for m in matches:
                node_uuid = m.get("node_uuid", "")
                path_row = (await session.execute(
                    select(Path).where(Path.node_uuid == node_uuid).limit(1)
                )).scalars().first()
                uri = f"{path_row.domain}://{path_row.path}" if path_row else node_uuid
                mem = (await session.execute(
                    select(Memory).where(Memory.node_uuid == node_uuid, Memory.deprecated == False).limit(1)
                )).scalars().first()
                snippet = (mem.content[:100] + "...") if mem and len(mem.content) > 100 else (mem.content if mem else "")
                enriched.append({
                    "keyword": m.get("keyword", ""),
                    "uri": uri,
                    "snippet": snippet,
                    "context": m.get("context", ""),
                    "position": m.get("position", 0),
                })
        return enriched

    # ─── Disclosure API ────────────────────────────────────────────
    @app.get("/api/memory-graph/disclosure")
    async def api_disclosure(request: Request, uri: str = Query(""), domain: str = Query("core")):
        user = require_auth(request)
        ns = user.get("namespace", "")
        if "://" in uri:
            domain, path = uri.split("://", 1)
        else:
            path = uri
        if path:
            node = await graph_service.get_memory_by_path(path, domain=domain, namespace=ns)
            if not node:
                raise HTTPException(404, "Not found")
            node_uuid = node["node_uuid"]
        else:
            node_uuid = ROOT_NODE_UUID
        children = await graph_service.get_children(node_uuid, domain=domain, context_path=path, namespace=ns)
        disclosures = []
        for child in children:
            if child.get("disclosure"):
                disclosures.append({
                    "name": child["name"],
                    "uri": f"{child['domain']}://{child['path']}",
                    "disclosure": child["disclosure"],
                    "priority": child["priority"],
                })
        return {"parent_uri": uri or f"{domain}://", "children_count": len(children), "disclosures": disclosures}

    # ─── Maintenance API ────────────────────────────────────────────
    @app.get("/api/memory-graph/maintenance/orphans")
    async def api_orphans(request: Request):
        require_auth(request)
        ns = request.query_params.get("namespace", "")
        return await graph_service.get_all_orphan_memories(namespace=ns)

    @app.get("/api/memory-graph/maintenance/orphans/{memory_id}")
    async def api_orphan_detail(request: Request, memory_id: int):
        require_auth(request)
        detail = await graph_service.get_orphan_detail(memory_id)
        if not detail:
            raise HTTPException(404, f"Memory {memory_id} not found")
        return detail

    @app.delete("/api/memory-graph/maintenance/orphans/{memory_id}")
    async def api_delete_orphan(request: Request, memory_id: int):
        require_auth(request)
        try:
            return await graph_service.permanently_delete_memory(memory_id)
        except ValueError as e:
            raise HTTPException(404, str(e))
        except PermissionError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/memory-graph/maintenance/diagnostics")
    async def api_diagnostics(request: Request, domain: str = "core"):
        require_auth(request)
        return await graph_service.get_diagnostics(domain=domain)

    @app.get("/api/memory-graph/random")
    async def api_random(request: Request, domain: str = None):
        require_auth(request)
        ns = request.query_params.get("namespace", "")
        result = await graph_service.get_random_memory(namespace=ns, domain=domain)
        if not result:
            raise HTTPException(404, "No memories available")
        return result

    # ─── Admin API ─────────────────────────────────────────────────
    @app.get("/api/admin/users")
    async def api_admin_users(request: Request):
        require_admin(request)
        from .auth import list_users
        return list_users()

    return app


async def _init_db():
    """Initialize the database connection."""
    from .db import init_db
    await init_db()


def main():
    parser = argparse.ArgumentParser(description="Memory Graph Web Server")
    parser.add_argument("--port", type=int, default=8900, help="Port (default 8900)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default 127.0.0.1)")
    args = parser.parse_args()

    asyncio.run(_init_db())

    app = create_app()
    if app is None:
        sys.exit(1)

    import uvicorn
    print(f"Memory Graph dashboard: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
