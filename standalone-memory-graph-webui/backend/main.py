from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api import review_router, proposal_review_router, browse_router, maintenance_router, settings_router
from auth import (
    authenticate, create_session_token, verify_session_token, get_user,
    enforce_network_auth, USERS_FILE,
)
from namespace_middleware import NamespaceMiddleware
from db import get_db_manager, close_db, ROOT_NODE_UUID
from health import router as health_router
from mcp_server import mcp as mcp_server
import argparse
import os
import config as _cfg


COOKIE_NAME = "mg_session"

# ─── Auth helpers ──────────────────────────────────────────────

def get_current_user(request: Request):
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
    """Dependency: require an authenticated administrator."""
    user = require_auth(request)
    if not (user.get("role") == "admin" or user.get("username") == "admin"):
        raise HTTPException(403, "Admin privileges required")
    return user


# ─── Startup ───────────────────────────────────────────────────

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--host", type=str)
_parser.add_argument("--port", type=int)
_args, _ = _parser.parse_known_args()
_host = _args.host or os.environ.get("UVICORN_HOST") or _cfg.get("host")
enforce_network_auth(host=_host)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    print("Memory Graph API starting...")
    _cfg.ensure_config_exists()

    # Ensure default admin user exists
    if not USERS_FILE.exists():
        from auth import create_user
        try:
            create_user("admin", "admin", namespace="", display_name="Admin")
            print("Created default admin user (username: admin, password: admin)")
            print("CHANGE THE PASSWORD IMMEDIATELY!")
        except Exception:
            pass

    try:
        db_manager = get_db_manager()
        await db_manager.init_db()
        print("Database initialized.")
    except Exception as e:
        print(f"Failed to initialize database: {e}")

    yield

    print("Closing database connections...")
    await close_db()


app = FastAPI(
    title="Memory Graph API",
    description="Knowledge Graph Memory Backend",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
cors_origins = _cfg.get("cors_origins")
if isinstance(cors_origins, str):
    cors_origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
if not cors_origins:
    cors_origins = ["http://127.0.0.1:8233", "http://localhost:8233"]

app.add_middleware(NamespaceMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth routes ───────────────────────────────────────────────

@app.post("/api/auth/login")
async def api_login(request: Request, response: Response = None):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    if not username or not password:
        raise HTTPException(400, "Username and password required")
    user = authenticate(username, password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    token = create_session_token(username)
    resp = JSONResponse({"ok": True, "username": username, "namespace": user.get("namespace", "")})
    secure_cookie = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    resp.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=86400 * 7,
        path="/",
    )
    return resp


@app.post("/api/auth/logout")
async def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@app.get("/api/auth/me")
async def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, **user}


# ─── Register API routers ─────────────────────────────────────

app.include_router(health_router)
app.include_router(review_router)
app.include_router(proposal_review_router)
app.include_router(browse_router, dependencies=[Depends(require_auth)])
app.include_router(maintenance_router, dependencies=[Depends(require_auth)])
app.include_router(settings_router, dependencies=[Depends(require_admin)])

# ─── Mount MCP SSE Server ─────────────────────────────────────
# Mount the MCP server's SSE transport at /mcp (SSE endpoint at /mcp/sse)
try:
    mcp_sse_app = mcp_server.sse_app(mount_path="/mcp")
    app.mount("/mcp", mcp_sse_app)
    print("MCP server mounted at /mcp (SSE at /mcp/sse)")
except Exception as e:
    print(f"Warning: MCP server failed to mount: {e}")


# ─── Serve Frontend Static Files ──────────────────────────────
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles as StarletteStaticFiles

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist")


class ImmutableAssets(StarletteStaticFiles):
    """Serve hashed Vite assets with long immutable cache headers."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        return response

# Mount static assets
_assets_dir = os.path.join(FRONTEND_DIST, "assets")
if os.path.exists(_assets_dir):
    app.mount("/assets", ImmutableAssets(directory=_assets_dir), name="assets")

@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    """Serve frontend SPA - index.html for all non-API routes."""
    # Don't intercept API routes
    _api_prefixes = ("api/", "browse/", "review/", "maintenance/", "settings/", "health", "docs", "openapi.json", "redoc", "mcp/")
    if full_path.startswith(_api_prefixes):
        raise HTTPException(status_code=404, detail="Not Found")
    # Try to serve the file directly
    file_path = os.path.join(FRONTEND_DIST, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    # Fall back to index.html for SPA routing
    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Memory Graph API", "version": "1.0.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    host = _args.host or _cfg.get("host")
    port = _args.port or int(_cfg.get("web_port"))
    enforce_network_auth(host=host)
    uvicorn.run(app, host=host, port=port)
