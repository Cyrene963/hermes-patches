"""
MCP Server for Memory Graph

Provides MCP (Model Context Protocol) interface for AI agents to interact
with the PostgreSQL-based memory graph system.

URI-based addressing with domain prefixes:
- core://agent              - AI's identity/memories
- writer://chapter_1        - Story/script drafts
- game://magic_system       - Game setting documents

Multiple paths can point to the same memory (aliases).
"""

import asyncio
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# Ensure we can import from backend modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as _cfg
from db import (
    get_db_manager, get_graph_service, get_glossary_service,
    get_search_indexer, close_db,
)
from db.namespace import get_namespace
from db.snapshot import get_changeset_store
from text_patch import (
    normalize_with_positions,
    find_valid_matches,
    try_normalized_patch,
    normalize_literal_newlines,
    format_normalization_preview,
)
from system_views import (
    fetch_and_format_memory,
    generate_boot_memory_view,
    generate_memory_index_view,
    generate_recent_memories_view,
    generate_glossary_index_view,
    generate_diagnostic_view,
)

from mcp.server.fastmcp import FastMCP

# =============================================================================
# Domain Configuration
# =============================================================================

_domains_from_config = _cfg.get("valid_domains")
VALID_DOMAINS = _domains_from_config if isinstance(_domains_from_config, list) else [
    d.strip() for d in str(_domains_from_config).split(",") if d.strip()
]
if "system" not in VALID_DOMAINS:
    VALID_DOMAINS.append("system")
DEFAULT_DOMAIN = "core"

# =============================================================================
# URI Parsing
# =============================================================================

_URI_PATTERN = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)://(.*)$")


def parse_uri(uri: str) -> Tuple[str, str]:
    """Parse a memory URI into (domain, path)."""
    uri = uri.strip()
    match = _URI_PATTERN.match(uri)
    if match:
        domain = match.group(1).lower()
        path = match.group(2).strip("/")
        if domain not in VALID_DOMAINS:
            raise ValueError(
                f"Unknown domain '{domain}'. Valid domains: {', '.join(VALID_DOMAINS)}"
            )
        return (domain, path)
    # Legacy fallback: bare path without protocol
    path = uri.strip("/")
    return (DEFAULT_DOMAIN, path)


def make_uri(domain: str, path: str) -> str:
    """Create a URI from domain and path."""
    return f"{domain}://{path}"


# =============================================================================
# Changeset Helpers
# =============================================================================

def _record_rows(
    before_state: Dict[str, List[Dict[str, Any]]],
    after_state: Dict[str, List[Dict[str, Any]]],
):
    """Feed row-level before/after states into the ChangesetStore."""
    store = get_changeset_store()
    store.record_many(before_state, after_state)


# =============================================================================
# MCP Server
# =============================================================================

mcp = FastMCP("Memory Graph Interface")


# =============================================================================
# MCP Tools
# =============================================================================

@mcp.tool()
async def read_memory(uri: str) -> str:
    """
    Reads a memory by its URI.

    Special System URIs:
    - system://boot             : [Startup Only] Loads your core memories.
    - system://index/<domain>   : Index of memories under specified domain.
    - system://recent           : Shows recently modified memories (default: 10).
    - system://recent/N         : Shows the N most recently modified memories.
    - system://glossary         : Shows all glossary keywords and their bound nodes.

    Args:
        uri: The memory URI (e.g., "core://nocturne", "system://boot")

    Returns:
        Memory content with Memory ID, priority, disclosure, and list of children.

    Examples:
        read_memory("core://agent")
        read_memory("writer://chapter_1/scene_1")
    """
    # System URI intercepts
    if uri.strip() == "system://boot":
        ns = get_namespace()
        current_core_uris = _cfg.get_boot_uris(ns)
        return await generate_boot_memory_view(current_core_uris)

    stripped = uri.strip()

    # system://index/<domain>
    if stripped.startswith("system://index/"):
        domain_filter = stripped[len("system://index/"):].strip("/")
        if not domain_filter:
            return "Error: index command requires a domain (e.g. system://index/core)"
        if domain_filter not in VALID_DOMAINS:
            return f"Error: Unknown domain '{domain_filter}'. Valid domains: {', '.join(VALID_DOMAINS)}"
        return await generate_memory_index_view(domain_filter=domain_filter)
    elif stripped == "system://index":
        return "Error: index command now requires a domain (e.g. system://index/core)"

    # system://glossary
    if stripped == "system://glossary":
        return await generate_glossary_index_view()

    # system://diagnostic/<domain>
    if stripped.startswith("system://diagnostic/"):
        domain_filter = stripped[len("system://diagnostic/"):].strip("/")
        if not domain_filter:
            return "Error: diagnostic command requires a domain"
        if domain_filter not in VALID_DOMAINS:
            return f"Error: Unknown domain '{domain_filter}'. Valid domains: {', '.join(VALID_DOMAINS)}"
        return await generate_diagnostic_view(domain=domain_filter)
    elif stripped == "system://diagnostic":
        return "Error: diagnostic command now requires a domain"

    # system://recent or system://recent/N
    if stripped == "system://recent" or stripped.startswith("system://recent/"):
        limit = 10
        suffix = stripped[len("system://recent"):].strip("/")
        if suffix:
            try:
                limit = max(1, min(100, int(suffix)))
            except ValueError:
                return f"Error: Invalid number in URI '{uri}'. Usage: system://recent or system://recent/N"
        return await generate_recent_memories_view(limit=limit)

    # system://random/<domain>
    if stripped.startswith("system://random/"):
        domain_filter = stripped[len("system://random/"):].strip("/")
        if not domain_filter:
            return "Error: random command requires a domain"
        if domain_filter not in VALID_DOMAINS:
            return f"Error: Unknown domain '{domain_filter}'. Valid domains: {', '.join(VALID_DOMAINS)}"
        graph = get_graph_service()
        pick = await graph.get_random_memory(namespace=get_namespace(), domain=domain_filter)
        if not pick:
            return f"No memories available for random selection in domain '{domain_filter}'."
        content = await fetch_and_format_memory(pick["uri"], track_access=True)
        meta_lines = [
            f"[Random Pick | Priority: {pick['priority']} | Last Accessed: {pick['last_accessed_at'] or 'never'}]",
        ]
        return "\n".join(meta_lines) + "\n\n" + content
    elif stripped == "system://random":
        return "Error: random command now requires a domain"

    try:
        content = await fetch_and_format_memory(uri, track_access=True)
        return content
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def create_memory(
    parent_uri: str,
    content: str,
    priority: int,
    disclosure: str,
    title: Optional[str] = None,
) -> str:
    """
    Creates a new memory under a parent URI.

    Args:
        parent_uri: The existing node to create this memory under.
                    Use "core://" or "writer://" for root level in that domain.
        content: Memory content.
        priority: Relative retrieval priority (lower = retrieved first, min 0).
        disclosure: A short trigger condition describing WHEN to read_memory() this node.
        title: A concrete, glanceable concept name (alphanumeric, hyphens, underscores only).

    Returns:
        The created memory's full URI
    """
    graph = get_graph_service()
    try:
        if not disclosure or not disclosure.strip():
            return "Error: disclosure is required."

        if title:
            if not re.match(r"^[a-zA-Z0-9_-]+$", title):
                return "Error: Title must only contain alphanumeric characters, underscores, or hyphens."

        domain, parent_path = parse_uri(parent_uri)

        result = await graph.create_memory(
            parent_path=parent_path,
            content=content,
            priority=priority,
            title=title,
            disclosure=disclosure,
            domain=domain,
            namespace=get_namespace(),
        )

        created_uri = result.get("uri", make_uri(domain, result["path"]))
        _record_rows(before_state={}, after_state=result.get("rows_after", {}))

        return f"Success: Memory created at '{created_uri}'"

    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def update_memory(
    uri: str,
    old_string: Optional[str] = None,
    new_string: Optional[str] = None,
    append: Optional[str] = None,
    priority: Optional[int] = None,
    disclosure: Optional[str] = None,
) -> str:
    """
    Updates an existing memory to a new version.

    PREREQUISITE: You MUST call read_memory(uri) and read the full content BEFORE calling this.

    Two content-editing modes (mutually exclusive):
    1. Patch mode: Provide old_string + new_string.
    2. Append mode: Provide append.

    Args:
        uri: URI to update (e.g., "core://agent/my_user")
        old_string: [Patch] Text to find in existing content
        new_string: [Patch] Replacement text. Use "" to delete.
        append: [Append] Text to append to end of existing content
        priority: New relative priority (None = keep existing).
        disclosure: New disclosure (None = keep existing).
    """
    graph = get_graph_service()
    try:
        domain, path = parse_uri(uri)
        full_uri = make_uri(domain, path)

        # Validate mutually exclusive modes
        if old_string is not None and append is not None:
            return "Error: Cannot use both patch and append mode."
        if old_string is not None and new_string is None:
            return 'Error: old_string provided without new_string.'
        if new_string is not None and old_string is None:
            return "Error: new_string provided without old_string."

        content = None

        if old_string is not None:
            if old_string == new_string:
                return "Error: old_string and new_string are identical."
            memory = await graph.get_memory_by_path(path, domain, namespace=get_namespace())
            if not memory:
                return f"Error: Memory at '{full_uri}' not found."

            current_content = memory.get("content", "")
            count = current_content.count(old_string)
            if count > 1:
                return f"Error: old_string found {count} times. Provide more context."
            if count == 1:
                content = current_content.replace(old_string, new_string, 1)
            else:
                # Try normalized patch
                patched = try_normalized_patch(current_content, old_string, new_string)
                if patched is not None:
                    content = patched
                else:
                    return f"Error: old_string not found in '{full_uri}'."

            if content == current_content:
                return f"Error: Replacement produced identical content."

        elif append is not None:
            if not append:
                return f"Error: Empty append for '{full_uri}'."
            memory = await graph.get_memory_by_path(path, domain, namespace=get_namespace())
            if not memory:
                return f"Error: Memory at '{full_uri}' not found."
            content = memory.get("content", "") + append

        if content is None and priority is None and disclosure is None:
            return f"Error: No update fields provided for '{full_uri}'."

        result = await graph.update_memory(
            path=path, content=content, priority=priority,
            disclosure=disclosure, domain=domain, namespace=get_namespace(),
        )

        _record_rows(
            before_state=result.get("rows_before", {}),
            after_state=result.get("rows_after", {}),
        )

        return f"Success: Memory at '{full_uri}' updated"

    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def delete_memory(uri: str) -> str:
    """
    Deletes a memory by cutting its URI path.

    PREREQUISITE: You MUST call read_memory(uri) BEFORE deleting.

    Args:
        uri: The URI to delete (e.g., "core://agent/old_note")
    """
    graph = get_graph_service()
    try:
        domain, path = parse_uri(uri)
        full_uri = make_uri(domain, path)

        memory = await graph.get_memory_by_path(path, domain, namespace=get_namespace())
        if not memory:
            return f"Error: Memory at '{full_uri}' not found."

        result = await graph.remove_path(path, domain, namespace=get_namespace())
        rows_before = result.get("rows_before", {})
        _record_rows(before_state=rows_before, after_state={})

        deleted_path_count = len(rows_before.get("paths", []))
        descendant_count = max(0, deleted_path_count - 1)
        msg = f"Success: Memory '{full_uri}' deleted."
        if descendant_count > 0:
            msg += f" (Recursively removed {descendant_count} descendant path(s))"
        return msg

    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def add_alias(
    new_uri: str, target_uri: str, priority: int, disclosure: str
) -> str:
    """
    Creates an alias URI pointing to the same memory as target_uri.
    This is NOT a copy. The alias and original share the same Memory ID.

    Args:
        new_uri: New URI to create (alias)
        target_uri: Existing URI to alias
        priority: Relative priority for THIS alias path.
        disclosure: Disclosure condition for THIS alias path.
    """
    graph = get_graph_service()
    try:
        new_domain, new_path = parse_uri(new_uri)
        target_domain, target_path = parse_uri(target_uri)

        result = await graph.add_path(
            new_path=new_path, target_path=target_path,
            new_domain=new_domain, target_domain=target_domain,
            priority=priority, disclosure=disclosure,
            namespace=get_namespace(),
        )

        _record_rows(
            before_state={},
            after_state=result.get("rows_after", {}),
        )

        return f"Success: Alias '{result['new_uri']}' -> '{result['target_uri']}'"

    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def manage_triggers(
    uri: str,
    add: Optional[List[str]] = None,
    remove: Optional[List[str]] = None,
) -> str:
    """
    Bind/unbind trigger words to a memory node.
    Triggers are bound to the MEMORY NODE (Memory ID), NOT to any specific path.

    Args:
        uri: Any URI pointing to the target memory node
        add: List of trigger words to bind (Optional)
        remove: List of trigger words to unbind (Optional)
    """
    graph = get_graph_service()
    glossary = get_glossary_service()
    try:
        domain, path = parse_uri(uri)
        full_uri = make_uri(domain, path)

        memory = await graph.get_memory_by_path(path, domain, namespace=get_namespace())
        if not memory:
            return f"Error: Memory at '{full_uri}' not found."

        node_uuid = memory["node_uuid"]

        if add and remove:
            add_set = {k.strip() for k in add if k.strip()}
            remove_set = {k.strip() for k in remove if k.strip()}
            overlap = add_set.intersection(remove_set)
            if overlap:
                return f"Error: Cannot add and remove same keywords: {', '.join(sorted(overlap))}"

        added = []
        removed = []
        skipped = []

        before_state = {"glossary_keywords": []}
        after_state = {"glossary_keywords": []}

        if add:
            for kw in add:
                kw = kw.strip()
                if not kw:
                    continue
                try:
                    result = await glossary.add_glossary_keyword(kw, node_uuid, namespace=get_namespace())
                    added.append(kw)
                    if "rows_before" in result:
                        before_state["glossary_keywords"].extend(result["rows_before"].get("glossary_keywords", []))
                    if "rows_after" in result:
                        after_state["glossary_keywords"].extend(result["rows_after"].get("glossary_keywords", []))
                except ValueError:
                    skipped.append(kw)

        if remove:
            for kw in remove:
                kw = kw.strip()
                if not kw:
                    continue
                result = await glossary.remove_glossary_keyword(kw, node_uuid, namespace=get_namespace())
                if result.get("success"):
                    removed.append(kw)
                    if "rows_before" in result:
                        before_state["glossary_keywords"].extend(result["rows_before"].get("glossary_keywords", []))
                    if "rows_after" in result:
                        after_state["glossary_keywords"].extend(result["rows_after"].get("glossary_keywords", []))

        if added or removed:
            get_changeset_store().record_many(before_state, after_state)

        current = await glossary.get_glossary_for_node(node_uuid, namespace=get_namespace())

        lines = [f"Keywords for '{full_uri}':"]
        if added:
            lines.append(f"  Added: {', '.join(added)}")
        if skipped:
            lines.append(f"  Already existed (skipped): {', '.join(skipped)}")
        if removed:
            lines.append(f"  Removed: {', '.join(removed)}")
        if current:
            lines.append(f"  Current: [{', '.join(current)}]")
        else:
            lines.append("  Current: (none)")

        return "\n".join(lines)

    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def search_memory(
    query: str, domain: Optional[str] = None, limit: int = 10
) -> str:
    """
    Search memories by path and content using full-text search.

    Args:
        query: Search keywords (substring match)
        domain: Optional domain filter (e.g., "core", "writer").
        limit: Maximum results (default 10)

    Examples:
        search_memory("job")
        search_memory("chapter", domain="writer")
    """
    search = get_search_indexer()
    try:
        if domain is not None and domain not in VALID_DOMAINS:
            return f"Error: Unknown domain '{domain}'. Valid domains: {', '.join(VALID_DOMAINS)}"

        results = await search.search(query, limit, domain, namespace=get_namespace())

        if not results:
            scope = f"in '{domain}'" if domain else "across all domains"
            return f"No matching memories found {scope}."

        lines = [f"Found {len(results)} matches for '{query}':", ""]
        for item in results:
            uri = item.get("uri", make_uri(item.get("domain", DEFAULT_DOMAIN), item["path"]))
            lines.append(f"- {uri}")
            lines.append(f"  Priority: {item['priority']}")
            if item.get("disclosure"):
                lines.append(f"  Disclosure: {item['disclosure']}")
            lines.append(f"  {item['snippet']}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# Export
# =============================================================================

__all__ = ["mcp", "parse_uri", "make_uri", "VALID_DOMAINS", "DEFAULT_DOMAIN"]
