"""
Configuration management via environment variables.

No config.json required. All settings read from environment with sensible defaults.
"""

import json
import os
import sys
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://postgres:postgres@127.0.0.1/hindsight",
    "valid_domains": ["core", "writer", "game", "notes", "narrative"],
    "boot_uris": {"": ["core://agent", "core://my_user", "core://agent/my_user"]},
    "host": "127.0.0.1",
    "web_port": 8233,
    "auto_open_browser": True,
    "api_token": None,
    "cors_origins": None,
    "public_readonly_mcp": False,
}

_ENV_MAP: dict[str, str] = {
    "database_url": "DATABASE_URL",
    "valid_domains": "VALID_DOMAINS",
    "host": "HOST",
    "web_port": "WEB_PORT",
    "auto_open_browser": "AUTO_OPEN_BROWSER",
    "api_token": "API_TOKEN",
    "cors_origins": "CORS_ORIGINS",
    "public_readonly_mcp": "PUBLIC_READONLY_MCP",
}

_cache: Optional[dict] = None


def _coerce(key: str, raw: str) -> Any:
    if key == "valid_domains":
        return [d.strip() for d in raw.split(",") if d.strip()]
    if key == "web_port":
        return int(raw)
    if key in ("auto_open_browser", "public_readonly_mcp"):
        return raw.lower() not in ("false", "0", "no")
    return raw


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache

    cfg = dict(DEFAULTS)

    for cfg_key, env_key in _ENV_MAP.items():
        val = os.environ.get(env_key)
        if cfg_key == "web_port" and not val:
            val = os.environ.get("PORT")
        if val:
            cfg[cfg_key] = _coerce(cfg_key, val)

    # Boot URIs from env
    if "CORE_MEMORY_URIS" in os.environ:
        base = os.environ["CORE_MEMORY_URIS"] or ""
        cfg["boot_uris"] = {"": [u.strip() for u in base.split(",") if u.strip()]}
    for key, val in os.environ.items():
        if key.startswith("CORE_MEMORY_URIS__"):
            ns = key[len("CORE_MEMORY_URIS__"):]
            val_str = val or ""
            cfg["boot_uris"][ns] = [u.strip() for u in val_str.split(",") if u.strip()]

    _cache = cfg
    return _cache


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get(key: str) -> Any:
    """Get a config value."""
    return _load().get(key, DEFAULTS.get(key))


def get_boot_uris(namespace: str = "") -> list[str]:
    """Get boot URIs for a namespace."""
    boot = _load().get("boot_uris", {})
    if namespace in boot:
        return boot[namespace]
    if "" in boot:
        return boot[""]
    return []


def get_all_boot_uris() -> dict[str, list[str]]:
    """Get the full boot_uris dict (all namespaces)."""
    return dict(_load().get("boot_uris", {}))


def set_boot_uris(uris: list[str], namespace: str = "") -> None:
    cfg = _load()
    if "boot_uris" not in cfg:
        cfg["boot_uris"] = {}
    cfg["boot_uris"][namespace] = uris


def delete_boot_uris(namespace: str) -> bool:
    """Remove a namespace override. Returns True if it existed."""
    cfg = _load()
    boot = cfg.get("boot_uris", {})
    if namespace not in boot:
        return False
    del boot[namespace]
    return True


def set_value(key: str, value: Any) -> None:
    cfg = _load()
    cfg[key] = value


def get_all() -> dict:
    """Get all settings for the UI."""
    return dict(_load())


def ensure_config_exists() -> None:
    _load()
