"""System views — computed read-only content for system:// URIs.

Ported from Nocturne Memory with full parity:
system://boot        — core memories at startup
system://version     — module version
system://stats       — node/edge/path/memory counts
system://recent      — recently modified memories
system://recent/N    — N most recent
system://index/DOMAIN — memory index for a domain
system://glossary    — all glossary keywords
system://diagnostic/DOMAIN — health diagnostics
system://tree        — full tree overview
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional


async def handle_system_uri(path: str, graph_service, search_indexer) -> Dict[str, Any]:
    """Route system:// URI to computed content."""
    if path == "version":
        from .. import __version__
        return {
            "uri": "system://version",
            "content": f"Memory Graph v{__version__}",
            "name": "version",
        }

    if path == "stats":
        from ..db import get_session
        from ..db.models import Node, Edge, Path, Memory, GlossaryKeyword, SearchDocument
        from sqlalchemy import select, func

        async with get_session() as session:
            node_cnt = (await session.execute(select(func.count()).select_from(Node))).scalar() or 0
            edge_cnt = (await session.execute(select(func.count()).select_from(Edge))).scalar() or 0
            path_cnt = (await session.execute(select(func.count()).select_from(Path))).scalar() or 0
            mem_cnt = (await session.execute(select(func.count()).select_from(Memory))).scalar() or 0
            active_cnt = (await session.execute(
                select(func.count()).select_from(Memory).where(Memory.deprecated == False)
            )).scalar() or 0
            kw_cnt = (await session.execute(select(func.count()).select_from(GlossaryKeyword))).scalar() or 0
            doc_cnt = (await session.execute(select(func.count()).select_from(SearchDocument))).scalar() or 0

        return {
            "uri": "system://stats",
            "content": json.dumps({
                "nodes": node_cnt,
                "edges": edge_cnt,
                "paths": path_cnt,
                "memories_total": mem_cnt,
                "memories_active": active_cnt,
                "memories_deprecated": mem_cnt - active_cnt,
                "glossary_keywords": kw_cnt,
                "search_documents": doc_cnt,
            }, indent=2),
            "name": "stats",
        }

    if path == "recent" or path.startswith("recent/"):
        limit = 10
        suffix = path[len("recent"):]
        if suffix.startswith("/"):
            try:
                limit = max(1, min(100, int(suffix[1:])))
            except ValueError:
                return {"uri": "system://recent", "content": f"Error: invalid number in '{path}'", "name": "recent"}
        results = await graph_service.get_recent_memories(limit=limit)
        lines = [
            "# Recently Modified Memories",
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Showing: {len(results)} entries",
            "",
        ]
        if not results:
            lines.append("(No memories found.)")
        for i, item in enumerate(results, 1):
            uri = item["uri"]
            priority = item.get("priority", 0)
            disclosure = item.get("disclosure")
            raw_ts = item.get("created_at", "")
            modified = raw_ts[:16].replace("T", " ") if raw_ts and len(raw_ts) >= 16 else raw_ts or "unknown"
            lines.append(f"{i}. {uri}  [★{priority}]  modified: {modified}")
            if disclosure:
                lines.append(f"   disclosure: {disclosure}")
            else:
                lines.append("   disclosure: (NOT SET)")
            lines.append("")
        return {"uri": "system://recent", "content": "\n".join(lines), "name": "recent"}

    if path.startswith("index/"):
        domain_filter = path[len("index/"):].strip("/")
        if not domain_filter:
            return {"uri": "system://index", "content": "Error: index requires a domain (e.g. system://index/core)", "name": "index"}
        content = await _generate_memory_index_view(graph_service, domain_filter)
        return {"uri": f"system://index/{domain_filter}", "content": content, "name": "index"}

    if path == "glossary":
        content = await _generate_glossary_index_view(graph_service)
        return {"uri": "system://glossary", "content": content, "name": "glossary"}

    if path.startswith("diagnostic/"):
        domain_filter = path[len("diagnostic/"):].strip("/")
        if not domain_filter:
            return {"uri": "system://diagnostic", "content": "Error: diagnostic requires a domain", "name": "diagnostic"}
        content = await _generate_diagnostic_view(graph_service, domain=domain_filter)
        return {"uri": f"system://diagnostic/{domain_filter}", "content": content, "name": "diagnostic"}

    if path == "tree":
        from ..db.models import ROOT_NODE_UUID
        children = await graph_service.get_children(ROOT_NODE_UUID)
        tree = []
        for child in children:
            grandchildren = await graph_service.get_children(child["node_uuid"])
            tree.append({
                "name": child["name"],
                "uri": child["uri"],
                "snippet": child.get("content_snippet", ""),
                "children_count": len(grandchildren),
            })
        return {
            "uri": "system://tree",
            "content": json.dumps(tree, indent=2, ensure_ascii=False),
            "name": "tree",
        }

    if path.startswith("random/"):
        domain_filter = path[len("random/"):].strip("/")
        if not domain_filter:
            return {"uri": "system://random", "content": "Error: random requires a domain", "name": "random"}
        pick = await graph_service.get_random_memory(domain=domain_filter)
        if not pick:
            return {"uri": f"system://random/{domain_filter}", "content": f"No memories in domain '{domain_filter}'.", "name": "random"}
        return {
            "uri": f"system://random/{domain_filter}",
            "content": f"[Random Pick | Priority: {pick['priority']} | Last Accessed: {pick['last_accessed_at'] or 'never'}]\n\nURI: {pick['uri']}",
            "name": "random",
        }

    return {
        "uri": f"system://{path}",
        "content": f"Unknown system path: {path}\nAvailable: boot, version, stats, recent, index/<domain>, glossary, diagnostic/<domain>, random/<domain>, tree",
        "name": path,
    }


async def _generate_memory_index_view(graph_service, domain_filter: str) -> str:
    """Generate a memory index view for a domain."""
    from ..db.models import ROOT_NODE_UUID

    try:
        paths = await graph_service.get_all_paths(ROOT_NODE_UUID)

        node_groups: Dict[tuple, list] = {}
        for item in paths:
            domain = item.get("domain", "core")
            if domain != domain_filter:
                continue
            nid = item.get("node_uuid", "")
            node_groups.setdefault(nid, []).append(item)

        lines = [
            "# Memory Index",
            f"# Domain: {domain_filter}",
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Total: {len(node_groups)} unique nodes",
            "",
            "# Legend: [#ID] = Memory ID, [★N] = priority (lower = higher)",
            "",
        ]

        for nid, items in sorted(node_groups.items(), key=lambda x: x[1][0].get("path", "")):
            primary = min(items, key=lambda x: (x["path"].count("/"), len(x["path"])))
            uri = primary.get("uri", f"{domain_filter}://{primary['path']}")
            priority = primary.get("priority", 0)
            memory_id = primary.get("memory_id", "?")
            lines.append(f"  - {uri} [#{memory_id}] [★{priority}]")

        return "\n".join(lines)
    except Exception as e:
        return f"Error generating index: {str(e)}"


async def _generate_glossary_index_view(graph_service) -> str:
    """Generate a glossary keyword index."""
    try:
        from ..db import get_session
        from ..db.models import GlossaryKeyword, Node, Path, Edge
        from sqlalchemy import select

        async with get_session() as session:
            result = await session.execute(
                select(GlossaryKeyword.keyword, GlossaryKeyword.node_uuid)
                .order_by(GlossaryKeyword.keyword)
            )
            rows = result.all()

        lines = [
            "# Glossary Index",
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Total: {len(rows)} keyword bindings",
            "",
        ]

        if not rows:
            lines.append("(No glossary keywords defined yet.)")
            return "\n".join(lines)

        for keyword, node_uuid in rows:
            # Get URI for node
            async with get_session() as session:
                path_result = await session.execute(
                    select(Path.domain, Path.path)
                    .join(Edge, Path.edge_id == Edge.id)
                    .where(Edge.child_uuid == node_uuid)
                    .limit(1)
                )
                path_row = path_result.first()
                uri = f"{path_row[0]}://{path_row[1]}" if path_row else f"unknown://{node_uuid[:8]}"
            lines.append(f"- {keyword}  ->  {uri}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error generating glossary: {str(e)}"


async def _generate_diagnostic_view(graph_service, domain: str, days_stale: int = 30, max_children: int = 10) -> str:
    """Generate a diagnostic report."""
    try:
        priority_thresholds = {0: 3, 1: 7, 2: 14}
        diagnostics = await graph_service.get_diagnostics(
            days_stale=days_stale, max_children=max_children,
            priority_thresholds=priority_thresholds, domain=domain,
        )

        stale_nodes = diagnostics.get("stale_nodes", [])
        crowded_nodes = diagnostics.get("crowded_nodes", [])
        orphaned_nodes = diagnostics.get("orphaned_nodes", [])

        if not stale_nodes and not crowded_nodes and not orphaned_nodes:
            return "No issues found. Memory system is healthy."

        lines = [
            f"# Memory System Diagnostics: {domain}",
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        if stale_nodes:
            lines.extend([
                "## 1. Stale Memories",
                f"Thresholds: Priority 0 (<3d), Priority 1 (<7d), Priority 2 (<14d), Others (<{days_stale}d).",
                "",
            ])
            for i, node in enumerate(stale_nodes, 1):
                last_acc = node.get("last_accessed_at")
                stale_days = node.get("stale_days")
                date_str = f"Last Accessed: {last_acc[:10]}" if last_acc else "Never accessed"
                lines.append(f"{i}. {node['uri']}")
                lines.append(f"   Priority: {node['priority']} | Stale: ~{stale_days}d | {date_str}")
            lines.append("")

        if crowded_nodes:
            lines.extend([
                "## 2. Crowded Parent Nodes",
                f"Nodes with more than {max_children} children.",
                "",
            ])
            for i, node in enumerate(crowded_nodes, 1):
                lines.append(f"{i}. {node['uri']} ({node['child_count']} children)")
            lines.append("")

        if orphaned_nodes:
            lines.extend([
                "## 3. Orphaned Paths",
                "Paths whose parent path no longer exists.",
                "",
            ])
            for i, node in enumerate(orphaned_nodes, 1):
                lines.append(f"{i}. {node['uri']}")
            lines.append("")

        return "\n".join(lines).strip()
    except Exception as e:
        return f"Error generating diagnostics: {str(e)}"
