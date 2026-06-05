"""Memory Graph tools — registered with Hermes Agent tool registry.

Provides 9 tools for URI-tree memory operations:
  memory_graph_read, memory_graph_create, memory_graph_update,
  memory_graph_delete, memory_graph_list, memory_graph_search,
  memory_graph_alias, memory_graph_glossary_add, memory_graph_glossary_scan
"""

import json
import logging
from typing import Optional

from tools.registry import registry

logger = logging.getLogger(__name__)

# Lazy-init DB on first tool call
_db_initialized = False


def _get_namespace() -> str:
    """Get current user's namespace. Uses RequestContext first, env/config fallback last."""
    import os
    # Explicit environment override for tests, cron, and CLI wrappers.
    # During pytest, avoid deployment-specific default-terminal fallback leaking
    # into tests that monkeypatch _get_namespace after importing this module.
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("MEMORY_GRAPH_NAMESPACE"):
        return ""
    ns = os.environ.get("MEMORY_GRAPH_NAMESPACE", "").strip()
    if ns:
        return ns
    # Try RequestContext (zero-default principle)
    try:
        from agent.request_context import get_namespace as _rc_get_ns
        ns = _rc_get_ns()
        if ns:
            return ns
    except ImportError as exc:
        logger.debug("RequestContext namespace provider unavailable: %s", exc)
    # Fallback to plugin context
    try:
        from _hermes_user_memory.memory_graph import get_current_namespace
        ns = get_current_namespace()
        if ns:
            return ns
    except ImportError as exc:
        logger.debug("User memory namespace provider unavailable: %s", exc)
    try:
        from plugins.memory_graph import get_current_namespace
        ns = get_current_namespace()
        if ns:
            return ns
    except ImportError as exc:
        logger.debug("Plugin namespace provider unavailable: %s", exc)
    try:
        import importlib.util
        from pathlib import Path
        plugin_init = Path.home() / ".hermes" / "plugins" / "memory-graph" / "__init__.py"
        if plugin_init.exists():
            spec = importlib.util.spec_from_file_location("memory_graph_plugin", plugin_init)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ns = mod.get_current_namespace()
            if ns:
                return ns
    except Exception as exc:
        logger.debug("Failed to load memory-graph plugin namespace provider: %s", exc, exc_info=True)
    # Terminal/CLI fallback from ~/.hermes/config.yaml.
    try:
        import yaml
        from pathlib import Path
        cfg = yaml.safe_load((Path.home() / ".hermes" / "config.yaml").read_text()) or {}
        default_user = str((cfg.get("memory_graph") or {}).get("default_terminal_user") or "").strip()
        if default_user:
            return f"telegram:{default_user}"
    except Exception as exc:
        logger.debug("Failed to read default terminal namespace from config: %s", exc, exc_info=True)
    return ""


def _ensure_db():
    global _db_initialized
    if _db_initialized:
        return
    import asyncio
    from agent.memory_graph.db import init_db
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, init_db()).result(timeout=30)
    else:
        asyncio.run(init_db())
    _db_initialized = True


def _run(coro):
    """Run async coroutine from sync context."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=60)
    return asyncio.run(coro)



def _resolve_namespace_arg(args) -> str:
    """Respect an explicitly supplied namespace, including the empty core namespace.

    `args.get('namespace') or _get_namespace()` makes it impossible for tests,
    admin tools, and maintenance code to intentionally query shared core because
    an explicit empty string falls through to the terminal/default user. Use this
    helper anywhere a tool accepts an optional namespace override.
    """
    sentinel = object()
    explicit = args.get("namespace", sentinel)
    return _get_namespace() if explicit is sentinel else (explicit or "")


def _refresh_search_index(node_uuid: str, namespace: str) -> None:
    """Best-effort sync of derived Memory Graph search rows after tool writes."""
    if not node_uuid:
        return
    try:
        _ensure_db()
        from agent.memory_graph.services.search import SearchIndexer
        _run(SearchIndexer().refresh_search_documents_for_node(node_uuid, namespace=namespace))
    except Exception as exc:
        logger.warning("Failed to refresh Memory Graph search index for %s: %s", node_uuid, exc)

def _parse_uri(uri: str, default_domain: str = "core"):
    if "://" in uri:
        domain, path = uri.split("://", 1)
        return domain, path
    return default_domain, uri


def _read(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    from agent.memory_graph.services.system_views import handle_system_uri
    uri = args.get("uri", "")
    domain, path = _parse_uri(uri, args.get("domain", "core"))
    ns = _resolve_namespace_arg(args)
    if domain == "system":
        result = _run(handle_system_uri(path, GraphService(), None))
        return json.dumps(result, ensure_ascii=False, default=str)
    result = _run(GraphService().get_memory_by_path(path, domain=domain, namespace=ns))
    if result is None:
        return json.dumps({"error": f"Path '{domain}://{path}' not found"})
    return json.dumps(result, ensure_ascii=False, default=str)


def _create(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    parent_uri = args.get("parent_uri", "")
    domain, parent_path = _parse_uri(parent_uri, args.get("domain", "core"))
    ns = _resolve_namespace_arg(args)
    content = args["content"]

    # Zero-default: user data MUST have namespace
    try:
        from agent.request_context import require_namespace_for_path
        required_ns = require_namespace_for_path(parent_path)
        if required_ns:
            ns = required_ns
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    result = _run(GraphService().create_memory(
        parent_path, content, priority=args.get("priority", 0),
        title=args.get("title") or None, domain=domain, namespace=ns,
    ))
    _refresh_search_index(result.get("node_uuid", ""), ns)
    return json.dumps(result, ensure_ascii=False, default=str)


def _update(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    uri = args.get("uri", "")
    domain, path = _parse_uri(uri, args.get("domain", "core"))
    ns = _resolve_namespace_arg(args)
    result = _run(GraphService().update_memory(
        path, args["content"], domain=domain, namespace=ns,
        priority=args.get("priority"),
    ))
    _refresh_search_index(result.get("node_uuid", ""), ns)
    return json.dumps(result, ensure_ascii=False, default=str)


def _delete(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    uri = args.get("uri", "")
    domain, path = _parse_uri(uri, args.get("domain", "core"))
    ns = _resolve_namespace_arg(args)
    node = _run(GraphService().get_memory_by_path(path, domain=domain, namespace=ns))
    node_uuid = (node or {}).get("node_uuid", "")
    result = _run(GraphService().delete_memory(path, domain=domain, namespace=ns))
    if node_uuid:
        _refresh_search_index(node_uuid, ns)
    return json.dumps({"deleted": result, "uri": f"{domain}://{path}"})


def _list(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    from agent.memory_graph.db.models import ROOT_NODE_UUID
    uri = args.get("uri", "")
    domain, path = _parse_uri(uri, args.get("domain", "core"))
    ns = _resolve_namespace_arg(args)
    graph = GraphService()
    if path:
        node = _run(graph.get_memory_by_path(path, domain=domain, namespace=ns))
        if not node:
            return json.dumps({"error": f"Not found: {domain}://{path}"})
        node_uuid = node["node_uuid"]
    else:
        node_uuid = ROOT_NODE_UUID
    children = _run(graph.get_children(node_uuid, domain=domain, namespace=ns))
    return json.dumps({
        "parent": f"{domain}://{path}" if path else "(root)",
        "namespace": ns,
        "children": children,
    }, ensure_ascii=False, default=str)


def _search(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.search import SearchIndexer
    ns = _resolve_namespace_arg(args)
    results = _run(SearchIndexer().search(
        args["query"], domain=args.get("domain") or None,
        namespace=ns or "", limit=args.get("limit", 20),
    ))
    return json.dumps({"query": args["query"], "namespace": ns, "results": results, "count": len(results)},
                       ensure_ascii=False, default=str)


def _alias(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    uri = args.get("uri", "")
    alias_uri = args.get("alias_uri", "")
    domain, path = _parse_uri(uri, args.get("domain", "core"))
    alias_domain, alias_path = _parse_uri(alias_uri, domain)
    ns = _resolve_namespace_arg(args)
    result = _run(GraphService().add_alias(path, alias_path, domain=domain, alias_domain=alias_domain, namespace=ns))
    _refresh_search_index(result.get("node_uuid", ""), ns)
    return json.dumps(result, ensure_ascii=False, default=str)


def _glossary_add(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    from agent.memory_graph.services.glossary import GlossaryService
    node_uri = args.get("node_uri", "")
    domain, path = _parse_uri(node_uri, args.get("domain", "core"))
    ns = _resolve_namespace_arg(args)
    node = _run(GraphService().get_memory_by_path(path, domain=domain, namespace=ns))
    if not node:
        return json.dumps({"error": f"Node not found: {domain}://{path}"})
    result = _run(GlossaryService().add_keyword(args["keyword"], node["node_uuid"], namespace=ns))
    _refresh_search_index(node.get("node_uuid", ""), ns)
    return json.dumps(result, ensure_ascii=False, default=str)


def _glossary_scan(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.glossary import GlossaryService
    ns = _resolve_namespace_arg(args)
    matches = _run(GlossaryService().scan_content(args["content"], namespace=ns))
    return json.dumps({"matches": matches, "count": len(matches)},
                       ensure_ascii=False, default=str)


# ─── DB Check ──────────────────────────────────────────────────────

def _check_memory_graph():
    """Check if Memory Graph DB is accessible."""
    try:
        import subprocess
        result = subprocess.run(
            ["sudo", "-u", "postgres", "psql", "-d", "hindsight", "-tAc",
             "SELECT 1 FROM mg_nodes LIMIT 1"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and "1" in result.stdout
    except Exception as exc:
        logger.debug("Memory Graph DB check failed: %s", exc, exc_info=True)
        return False


# ─── Tool Schemas ──────────────────────────────────────────────────

MG_READ_SCHEMA = {
    "name": "memory_graph_read",
    "description": "Read a memory by URI (domain://path). Returns content, metadata, aliases.",
    "parameters": {
        "type": "object",
        "properties": {
            "uri": {"type": "string", "description": "URI like core://path/to/memory"},
            "domain": {"type": "string", "default": "core"},
        },
        "required": ["uri"],
    },
}

MG_CREATE_SCHEMA = {
    "name": "memory_graph_create",
    "description": (
        "Create a new memory node under a parent URI. "
        "TRIGGERS — call this PROACTIVELY (without being asked) when: "
        "1) You arrive at a genuinely new understanding or insight about the user, project, or environment. "
        "2) The user reveals new personal information (preferences, habits, relationships, goals). "
        "3) A significant relational or emotional event occurs (conflict, gratitude, disappointment). "
        "4) You reach a technical conclusion or discover a non-obvious workaround. "
        "5) You catch yourself about to say 'I understand now' or 'I'll remember that' — stop and store it first. "
        "SELF-CHECK: After important exchanges, ask 'Does this cognition have a corresponding record in Memory Graph?' If not, create it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "parent_uri": {"type": "string", "description": "Parent URI (empty = root). Use domain://path format, e.g. core://用户/偏好"},
            "content": {"type": "string", "description": "Memory content — plain text, be specific and factual"},
            "title": {"type": "string", "default": ""},
            "priority": {"type": "integer", "default": 0, "description": "0=normal, 1=important, 2=critical"},
            "domain": {"type": "string", "default": "core", "description": "Domain prefix: core, 用户, 项目, 经验教训, 工具与配置"},
        },
        "required": ["parent_uri", "content"],
    },
}

MG_UPDATE_SCHEMA = {
    "name": "memory_graph_update",
    "description": (
        "Update a memory's content (creates new version, deprecates old). "
        "TRIGGERS — call this PROACTIVELY when: "
        "1) An existing memory is outdated or partially wrong based on new information. "
        "2) A fact has evolved (e.g. project status changed, user preference shifted). "
        "3) You discover a memory exists but needs correction or expansion. "
        "Prefer update over creating duplicates. Use memory_graph_search first to check if a related memory exists."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "uri": {"type": "string", "description": "URI of the memory to update"},
            "content": {"type": "string", "description": "New content (replaces old, old version preserved)"},
            "domain": {"type": "string", "default": "core"},
            "priority": {"type": "integer"},
        },
        "required": ["uri", "content"],
    },
}

MG_DELETE_SCHEMA = {
    "name": "memory_graph_delete",
    "description": "Delete a memory node and its entire subtree.",
    "parameters": {
        "type": "object",
        "properties": {
            "uri": {"type": "string"},
            "domain": {"type": "string", "default": "core"},
        },
        "required": ["uri"],
    },
}

MG_LIST_SCHEMA = {
    "name": "memory_graph_list",
    "description": "List children of a URI (or root if empty).",
    "parameters": {
        "type": "object",
        "properties": {
            "uri": {"type": "string", "default": ""},
            "domain": {"type": "string", "default": "core"},
        },
    },
}

MG_SEARCH_SCHEMA = {
    "name": "memory_graph_search",
    "description": "Full-text search across all memory content.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "domain": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
}

MG_ALIAS_SCHEMA = {
    "name": "memory_graph_alias",
    "description": "Add an alias path pointing to an existing memory.",
    "parameters": {
        "type": "object",
        "properties": {
            "uri": {"type": "string", "description": "Existing URI"},
            "alias_uri": {"type": "string", "description": "New alias URI"},
            "domain": {"type": "string", "default": "core"},
        },
        "required": ["uri", "alias_uri"],
    },
}

MG_GLOSSARY_ADD_SCHEMA = {
    "name": "memory_graph_glossary_add",
    "description": "Bind a keyword to a node for trigger scanning.",
    "parameters": {
        "type": "object",
        "properties": {
            "keyword": {"type": "string"},
            "node_uri": {"type": "string"},
            "domain": {"type": "string", "default": "core"},
        },
        "required": ["keyword", "node_uri"],
    },
}

MG_GLOSSARY_SCAN_SCHEMA = {
    "name": "memory_graph_glossary_scan",
    "description": "Scan content for glossary keywords and return matching nodes.",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
        },
        "required": ["content"],
    },
}

MG_RECALL_SCHEMA = {
    "name": "memory_graph_recall",
    "description": "Weighted random recall — surface forgotten-but-important memories based on staleness and priority.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 5},
        },
    },
}

# ─── Registration ──────────────────────────────────────────────────

_TOOLSET = "memory_graph"

def _recall(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    ns = _resolve_namespace_arg(args)
    results = _run(GraphService().weighted_random_recall(namespace=ns, limit=args.get("limit", 5)))
    return json.dumps({"recalled": results, "count": len(results)}, ensure_ascii=False, default=str)

registry.register(name="memory_graph_read", toolset=_TOOLSET, schema=MG_READ_SCHEMA, handler=lambda args, **kw: _read(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_READ_SCHEMA["description"])
registry.register(name="memory_graph_create", toolset=_TOOLSET, schema=MG_CREATE_SCHEMA, handler=lambda args, **kw: _create(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_CREATE_SCHEMA["description"])
registry.register(name="memory_graph_update", toolset=_TOOLSET, schema=MG_UPDATE_SCHEMA, handler=lambda args, **kw: _update(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_UPDATE_SCHEMA["description"])
registry.register(name="memory_graph_delete", toolset=_TOOLSET, schema=MG_DELETE_SCHEMA, handler=lambda args, **kw: _delete(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_DELETE_SCHEMA["description"])
registry.register(name="memory_graph_list", toolset=_TOOLSET, schema=MG_LIST_SCHEMA, handler=lambda args, **kw: _list(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_LIST_SCHEMA["description"])
registry.register(name="memory_graph_search", toolset=_TOOLSET, schema=MG_SEARCH_SCHEMA, handler=lambda args, **kw: _search(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_SEARCH_SCHEMA["description"])
registry.register(name="memory_graph_alias", toolset=_TOOLSET, schema=MG_ALIAS_SCHEMA, handler=lambda args, **kw: _alias(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_ALIAS_SCHEMA["description"])
registry.register(name="memory_graph_glossary_add", toolset=_TOOLSET, schema=MG_GLOSSARY_ADD_SCHEMA, handler=lambda args, **kw: _glossary_add(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_GLOSSARY_ADD_SCHEMA["description"])
registry.register(name="memory_graph_glossary_scan", toolset=_TOOLSET, schema=MG_GLOSSARY_SCAN_SCHEMA, handler=lambda args, **kw: _glossary_scan(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_GLOSSARY_SCAN_SCHEMA["description"])
registry.register(name="memory_graph_recall", toolset=_TOOLSET, schema=MG_RECALL_SCHEMA, handler=lambda args, **kw: _recall(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_RECALL_SCHEMA["description"])

# ─── Nocturne parity tools ─────────────────────────────────────────

MG_ORPHANS_SCHEMA = {
    "name": "memory_graph_orphans",
    "description": "List all deprecated/orphan memories for cleanup.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

MG_RANDOM_SCHEMA = {
    "name": "memory_graph_random",
    "description": "Pick a weighted-random memory (staleness × priority). Surfaces forgotten-but-important content.",
    "parameters": {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain filter (e.g. 'core')", "default": ""},
        },
    },
}

MG_DIAGNOSTICS_SCHEMA = {
    "name": "memory_graph_diagnostics",
    "description": "Run diagnostics: stale memories, crowded parents, orphaned paths.",
    "parameters": {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "default": "core"},
        },
    },
}

MG_PURGE_SCHEMA = {
    "name": "memory_graph_purge",
    "description": "Permanently delete a deprecated memory. Repairs version chain. Refuses to delete active memories.",
    "parameters": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "integer", "description": "Memory ID to delete (must be deprecated)"},
        },
        "required": ["memory_id"],
    },
}

def _orphans(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    result = _run(GraphService().get_all_orphan_memories())
    return json.dumps({"orphans": result, "count": len(result)}, ensure_ascii=False, default=str)

def _random_memory(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    domain = args.get("domain") or None
    result = _run(GraphService().get_random_memory(domain=domain))
    if not result:
        return json.dumps({"error": "No memories available"}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False, default=str)

def _diagnostics(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    domain = args.get("domain", "core")
    result = _run(GraphService().get_diagnostics(domain=domain))
    return json.dumps(result, ensure_ascii=False, default=str)

def _purge(args, **kw):
    _ensure_db()
    from agent.memory_graph.services.graph import GraphService
    memory_id = args["memory_id"]
    try:
        result = _run(GraphService().permanently_delete_memory(memory_id))
        return json.dumps(result, ensure_ascii=False, default=str)
    except PermissionError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

registry.register(name="memory_graph_orphans", toolset=_TOOLSET, schema=MG_ORPHANS_SCHEMA, handler=lambda args, **kw: _orphans(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_ORPHANS_SCHEMA["description"])
registry.register(name="memory_graph_random", toolset=_TOOLSET, schema=MG_RANDOM_SCHEMA, handler=lambda args, **kw: _random_memory(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_RANDOM_SCHEMA["description"])
registry.register(name="memory_graph_diagnostics", toolset=_TOOLSET, schema=MG_DIAGNOSTICS_SCHEMA, handler=lambda args, **kw: _diagnostics(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_DIAGNOSTICS_SCHEMA["description"])
registry.register(name="memory_graph_purge", toolset=_TOOLSET, schema=MG_PURGE_SCHEMA, handler=lambda args, **kw: _purge(args), check_fn=_check_memory_graph, emoji="🧠", description=MG_PURGE_SCHEMA["description"])
