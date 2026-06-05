"""Hindsight → Memory Graph migration bridge.

Imports existing Hindsight memories into the Memory Graph URI tree.
Creates a structured tree: hindsight/{bank_id}/{memory_id} with content
and metadata preserved.

Usage:
    python -m agent.memory_graph.migration              # dry-run
    python -m agent.memory_graph.migration --execute     # actually migrate
    python -m agent.memory_graph.migration --bank mybank # specific bank
"""

import asyncio
import json
import logging
import os
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def get_hindsight_memories(bank_id: str = "hindsight") -> List[Dict[str, Any]]:
    """Fetch memories from Hindsight via its API or direct DB."""
    # Try API first
    api_url = os.environ.get("HINDSIGHT_API_URL", "http://localhost:8765")
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_url}/memories", params={"bank_id": bank_id, "limit": 10000}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("memories", [])
    except Exception as e:
        logger.info(f"Hindsight API not available ({e}), trying direct DB")

    # Fallback: direct PostgreSQL query
    try:
        import asyncpg
        db_url = os.environ.get("HINDSIGHT_DATABASE_URL", "postgresql://hindsight@localhost/hindsight")
        conn = await asyncpg.connect(db_url)
        rows = await conn.fetch(
            "SELECT id, content, metadata, created_at, updated_at FROM memories WHERE bank_id = $1 ORDER BY created_at",
            bank_id,
        )
        await conn.close()
        return [
            {
                "id": row["id"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Failed to fetch Hindsight memories: {e}")
        return []


def _categorize_memory(memory: Dict[str, Any]) -> str:
    """Assign a category path based on memory content/metadata."""
    content = (memory.get("content") or "").lower()
    meta = memory.get("metadata", {})
    tags = meta.get("tags", [])

    # Check tags first
    tag_str = " ".join(tags).lower() if tags else ""

    if "user" in tag_str or "preference" in tag_str or "profile" in tag_str:
        return "user"
    if "project" in tag_str or "code" in tag_str:
        return "projects"
    if "env" in tag_str or "system" in tag_str or "tool" in tag_str:
        return "environment"
    if "lesson" in tag_str or "learned" in tag_str:
        return "lessons"

    # Content-based heuristics
    if any(w in content for w in ["user prefers", "user likes", "user wants", "communication style"]):
        return "user"
    if any(w in content for w in ["project", "repo", "codebase", "repository"]):
        return "projects"
    if any(w in content for w in ["installed", "os:", "linux", "server", "tool:"]):
        return "environment"
    if any(w in content for w in ["learned", "lesson", "discovered", "found that"]):
        return "lessons"

    return "general"


async def migrate_hindsight_to_graph(
    bank_id: str = "hindsight",
    domain: str = "hindsight",
    dry_run: bool = True,
    limit: int = 0,
) -> Dict[str, Any]:
    """Migrate Hindsight memories to Memory Graph.

    Creates tree structure:
        hindsight/user/        — user preferences
        hindsight/projects/    — project knowledge
        hindsight/environment/ — system/env facts
        hindsight/lessons/     — learned lessons
        hindsight/general/     — uncategorized

    Args:
        bank_id: Hindsight bank to migrate from
        domain: Target domain in memory graph
        dry_run: If True, only report what would be done
        limit: Max memories to process (0 = all)

    Returns:
        Migration report dict
    """
    from .services.graph import GraphService

    memories = await get_hindsight_memories(bank_id)
    if limit > 0:
        memories = memories[:limit]

    report = {
        "total_hindsight": len(memories),
        "migrated": 0,
        "skipped": 0,
        "errors": [],
        "categories": {},
        "dry_run": dry_run,
    }

    if not memories:
        report["message"] = "No Hindsight memories found to migrate"
        return report

    graph = GraphService()

    # Pre-create category nodes
    categories = set()
    for mem in memories:
        cat = _categorize_memory(mem)
        categories.add(cat)

    if not dry_run:
        for cat in sorted(categories):
            try:
                await graph.create_memory(
                    parent_path="", content=f"Category: {cat}",
                    title=cat, domain=domain, priority=2,
                )
            except ValueError:
                pass  # Already exists

    # Migrate each memory
    for mem in memories:
        cat = _categorize_memory(mem)
        content = mem.get("content", "")
        if not content.strip():
            report["skipped"] += 1
            continue

        # Build content with metadata
        full_content = content
        if mem.get("created_at"):
            full_content = f"[{mem['created_at']}] {full_content}"

        if dry_run:
            report["migrated"] += 1
            report["categories"][cat] = report["categories"].get(cat, 0) + 1
            continue

        try:
            # Generate a safe title from first 50 chars
            title = content[:50].replace("/", "-").replace("\n", " ").strip()
            if not title:
                title = f"mem-{mem.get('id', 'unknown')}"

            result = await graph.create_memory(
                parent_path=cat,
                content=full_content,
                title=title,
                domain=domain,
                priority=2,
            )
            report["migrated"] += 1
            report["categories"][cat] = report["categories"].get(cat, 0) + 1
        except Exception as e:
            report["errors"].append({"memory_id": mem.get("id"), "error": str(e)})

    return report


async def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Migrate Hindsight memories to Memory Graph")
    parser.add_argument("--execute", action="store_true", help="Actually migrate (default is dry-run)")
    parser.add_argument("--bank", default="hindsight", help="Hindsight bank ID")
    parser.add_argument("--domain", default="hindsight", help="Target domain in memory graph")
    parser.add_argument("--limit", type=int, default=0, help="Max memories to process (0=all)")
    args = parser.parse_args()

    # Init DB
    from .db import init_db
    db_url = os.environ.get("MEMORY_GRAPH_DB_URL")
    if not db_url:
        # Auto-detect from Hindsight
        hd_url = os.environ.get("HINDSIGHT_DATABASE_URL", "")
        if hd_url:
            db_url = hd_url.replace("postgresql://", "postgresql+asyncpg://")
        else:
            db_url = "postgresql+asyncpg://hindsight@localhost/hindsight"
    await init_db(db_url)

    report = await migrate_hindsight_to_graph(
        bank_id=args.bank, domain=args.domain,
        dry_run=not args.execute, limit=args.limit,
    )

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    from .db import close_db
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
