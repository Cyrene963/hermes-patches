"""Progressive Disclosure — trigger-based content revelation.

Progressive disclosure is stored on Edge (not Node/Memory), so the same
node accessed via different aliases can have different triggers.

Rules:
- MUST fire BEFORE the failure, while there is still time to act
- GOOD: external input signal ("When the user mentions X")
- GOOD: output intent ("When I am about to do X")
- BAD: mid-failure, self-awareness, vacuous ("important", "remember")

Display: When reading a parent node, children's disclosures appear as
a table of contents that the agent can selectively expand.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


async def get_disclosure_table(graph_service, node_uuid: str,
                                domain: str = "core", namespace: str = "") -> Dict[str, Any]:
    """Build a disclosure table for a node's children.

    Returns:
        {
            "parent_node": node_uuid,
            "children": [
                {
                    "name": "...",
                    "uri": "core://...",
                    "disclosure": "When the user mentions X, ...",
                    "priority": 0,
                    "snippet": "short content preview",
                    "has_disclosure": true,
                },
                ...
            ],
            "disclosure_count": 3,
            "total_children": 7,
        }
    """
    children = await graph_service.get_children(
        node_uuid, domain=domain, context_path=None, namespace=namespace
    )

    entries = []
    disclosure_count = 0
    for child in children:
        has_disclosure = bool(child.get("disclosure"))
        if has_disclosure:
            disclosure_count += 1
        entries.append({
            "name": child["name"],
            "uri": f"{child['domain']}://{child['path']}",
            "disclosure": child.get("disclosure", ""),
            "priority": child.get("priority", 0),
            "snippet": child.get("content_snippet", ""),
            "has_disclosure": has_disclosure,
        })

    return {
        "parent_node": node_uuid,
        "children": entries,
        "disclosure_count": disclosure_count,
        "total_children": len(entries),
    }


def format_disclosure_for_prompt(disclosure_table: Dict[str, Any]) -> str:
    """Format a disclosure table as a human-readable prompt section.

    Output example:
        ## Children of core://agent
        - [0] worldview — When building worldview, read this first
        - [1] skills — (no trigger)
        - [2] memory — When storing new facts, check existing structure
    """
    lines = []
    parent = disclosure_table.get("parent_node", "unknown")
    children = disclosure_table.get("children", [])

    if not children:
        return ""

    lines.append(f"## Children ({len(children)} total, {disclosure_table.get('disclosure_count', 0)} with triggers)")
    lines.append("")

    for child in children:
        prio = child.get("priority", 0)
        name = child["name"]
        uri = child["uri"]

        if child.get("has_disclosure"):
            trigger = child["disclosure"]
            lines.append(f"- [{prio}] {name} — ⚡ {trigger}")
        else:
            lines.append(f"- [{prio}] {name}")

    return "\n".join(lines)


async def check_disclosure_triggers(graph_service, content: str,
                                     node_uuid: str, domain: str = "core",
                                     namespace: str = "") -> List[Dict[str, Any]]:
    """Check if any disclosure triggers fire for the given content.

    Scans the content against disclosure triggers of children of the given node.
    Returns list of triggered children with their URIs and trigger text.
    """
    children = await graph_service.get_children(
        node_uuid, domain=domain, namespace=namespace
    )

    triggered = []
    content_lower = content.lower()

    for child in children:
        disclosure = child.get("disclosure", "")
        if not disclosure:
            continue

        # Simple keyword matching — check if disclosure keywords appear in content
        # A more sophisticated version would use NLP/LLM matching
        disclosure_lower = disclosure.lower()

        # Extract key phrases from disclosure trigger
        # Common patterns: "When the user mentions X", "When doing Y"
        keywords = _extract_trigger_keywords(disclosure_lower)
        if not keywords:
            continue

        matches = sum(1 for kw in keywords if kw in content_lower)
        if matches >= max(1, len(keywords) // 2):  # At least half the keywords match
            triggered.append({
                "name": child["name"],
                "uri": f"{child['domain']}://{child['path']}",
                "disclosure": disclosure,
                "priority": child.get("priority", 0),
                "match_count": matches,
                "total_keywords": len(keywords),
            })

    # Sort by match quality, then priority
    triggered.sort(key=lambda x: (-x["match_count"], x["priority"]))
    return triggered


def _extract_trigger_keywords(disclosure: str) -> List[str]:
    """Extract searchable keywords from a disclosure trigger text."""
    import re

    # Remove common filler words
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "when", "while",
        "if", "then", "that", "this", "it", "its", "i", "me", "my", "we",
        "our", "you", "your", "he", "she", "they", "them", "and", "or", "but",
        "not", "no", "so", "about", "up", "out", "just", "also", "very",
    }

    words = re.findall(r'\b[a-z]{3,}\b', disclosure)
    keywords = [w for w in words if w not in stopwords]

    # Also extract quoted phrases
    quoted = re.findall(r'"([^"]+)"', disclosure) + re.findall(r"'([^']+)'", disclosure)
    keywords.extend([q.lower() for q in quoted])

    return keywords[:10]  # Cap at 10 keywords
