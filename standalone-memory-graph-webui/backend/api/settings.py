"""
Settings API — read and update server configuration.
"""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from db.namespace import get_namespace

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SettingsUpdate(BaseModel):
    database_url: str | None = None
    valid_domains: list[str] | None = None
    host: str | None = None
    web_port: int | None = None
    auto_open_browser: bool | None = None
    api_token: str | None = None
    cors_origins: str | None = None
    public_readonly_mcp: bool | None = None


class BootUriUpdate(BaseModel):
    uris: list[str]


class DatabaseCreate(BaseModel):
    path: str


class DatabaseTest(BaseModel):
    database_url: str


# ---------------------------------------------------------------------------
# Settings CRUD
# ---------------------------------------------------------------------------

def _sanitize_settings(settings: dict) -> dict:
    """Return settings safe for UI/API responses; never expose secrets."""
    safe = dict(settings or {})
    if safe.get("database_url"):
        safe["database_url"] = _mask_password(str(safe["database_url"]))
    if safe.get("api_token"):
        safe["api_token"] = "****"
    return safe


@router.get("")
async def get_settings():
    """Return current settings safe for display in the WebUI."""
    return {
        "settings": _sanitize_settings(config.get_all()),
    }


_URI_RE = re.compile(r"^[a-zA-Z0-9_-]+://[^\r\n]+$")
_DEFAULT_NS_SENTINEL = "_ns_default_0x7f3a9e"


@router.put("")
async def update_settings(body: SettingsUpdate):
    """Update one or more settings."""
    updated = []
    needs_restart = False

    fields = body.model_dump(exclude_none=True)

    if "web_port" in fields:
        port = fields["web_port"]
        if not (1 <= port <= 65535):
            raise HTTPException(status_code=422, detail=f"Invalid port {port}.")

    for field_name, value in fields.items():
        config.set_value(field_name, value)
        updated.append(field_name)
        if field_name in ("database_url", "host", "web_port", "api_token", "valid_domains"):
            needs_restart = True

    return {
        "success": True,
        "updated": updated,
        "needs_restart": needs_restart,
    }


# ---------------------------------------------------------------------------
# Boot URI management
# ---------------------------------------------------------------------------

@router.get("/boot-uris")
async def get_boot_uris():
    """Return boot URIs for the current namespace."""
    ns = get_namespace()
    return {"uris": config.get_boot_uris(ns)}


@router.put("/boot-uris")
async def set_boot_uris(body: BootUriUpdate):
    """Replace the full boot URI list."""
    ns = get_namespace()

    for uri in body.uris:
        if not _URI_RE.match(uri):
            raise HTTPException(status_code=422, detail=f"Invalid URI format: {uri}")

    config.set_boot_uris(body.uris, ns)
    return {"success": True, "uris": body.uris}


class BootUriToggle(BaseModel):
    uri: str
    enabled: bool


@router.patch("/boot-uris")
async def toggle_boot_uri(body: BootUriToggle):
    """Add or remove a single URI from the boot list."""
    ns = get_namespace()
    current = config.get_boot_uris(ns)
    uri = body.uri.strip()
    if not uri:
        raise HTTPException(status_code=422, detail="URI cannot be empty")
    if not _URI_RE.match(uri):
        raise HTTPException(status_code=422, detail="Invalid URI format")

    if body.enabled:
        if uri not in current:
            current.append(uri)
    else:
        current = [u for u in current if u != uri]

    config.set_boot_uris(current, ns)
    return {"success": True, "uris": current}


@router.get("/boot-uris/all")
async def get_all_boot_uris():
    """Return boot URIs for every namespace at once."""
    return {"boot_uris": config.get_all_boot_uris()}


@router.put("/boot-uris/ns/{namespace_slug}")
async def set_boot_uris_for_namespace(namespace_slug: str, body: BootUriUpdate):
    """Replace boot URIs for a specific namespace.

    The frontend uses `_ns_default_0x7f3a9e` as the empty/default namespace slug.
    """
    ns = "" if namespace_slug == _DEFAULT_NS_SENTINEL else namespace_slug
    for uri in body.uris:
        if not _URI_RE.match(uri):
            raise HTTPException(status_code=422, detail=f"Invalid URI format: {uri}")
    config.set_boot_uris(body.uris, ns)
    return {"success": True, "namespace": ns, "uris": body.uris}


@router.delete("/boot-uris/ns/{namespace_slug}")
async def delete_boot_uris_for_namespace(namespace_slug: str):
    """Delete a namespace-specific boot URI override."""
    ns = "" if namespace_slug == _DEFAULT_NS_SENTINEL else namespace_slug
    if ns == "":
        raise HTTPException(status_code=422, detail="Cannot delete default boot URI list")
    all_boot = config.get_all_boot_uris()
    if ns in all_boot:
        del all_boot[ns]
        config.set_value("boot_uris", all_boot)
    return {"success": True, "namespace": ns}


# ---------------------------------------------------------------------------
# Database management
# ---------------------------------------------------------------------------

@router.get("/database/status")
async def database_status():
    """Return current DB info."""
    url = config.get("database_url") or ""
    info: dict = {"database_url": _mask_password(url), "type": "unknown"}

    if not url:
        return info

    if "postgresql" in url:
        info["type"] = "postgresql"
        info["url_masked"] = _mask_password(url)

    return info


_ALLOWED_DB_SCHEMES = ("postgresql+asyncpg",)


@router.post("/database/test")
async def test_database(body: DatabaseTest):
    """Test if a database URL is connectable."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = body.database_url
    if not any(url.startswith(s + "://") for s in _ALLOWED_DB_SCHEMES):
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported scheme. Allowed: {', '.join(_ALLOWED_DB_SCHEMES)}",
        )

    try:
        engine = create_async_engine(url, echo=False)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return {"success": True, "message": "Connection successful"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_password(url: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", url)
