"""Shadow Mode write logger — records proposed writes without executing them."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

_SHADOW_LOG_DIR = os.path.expanduser("~/.hermes/logs/shadow_writes")
os.makedirs(_SHADOW_LOG_DIR, exist_ok=True)


def log_shadow_write(
    conversation_id: str,
    user_id: str,
    namespace: str,
    user_message: str,
    assistant_message: str,
    candidates: List[Dict[str, Any]],
    mode: str = "shadow"
) -> Dict[str, Any]:
    """Log a shadow write entry."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "user_id": user_id,
        "namespace": namespace,
        "user_message": user_message[:200],
        "assistant_message": assistant_message[:200],
        "candidate_writes": [],
        "would_write": False,
        "would_review": False,
        "would_ignore": False,
        "actually_written": False,
        "mode": mode,
    }

    for c in candidates:
        write_action = {
            "memory_type": c.get("memory_type", "unknown"),
            "importance_score": c.get("importance", 0),
            "target_store": c.get("target_store", "ignore"),
            "target_path": c.get("target_path", ""),
            "subject": c.get("subject", ""),
            "predicate": c.get("predicate", ""),
            "object": c.get("object_value", "")[:100],
            "requires_review": c.get("requires_review", False),
            "reason": c.get("reason", ""),
            "dedup_key": c.get("dedup_key", ""),
            "auto_write_allowed": c.get("auto_write_allowed", False),
            "actually_written": c.get("actually_written", False),
            "readback_ok": c.get("readback_ok", False),
            "uri": c.get("uri", ""),
            "top_uri": c.get("top_uri", ""),
            "top_score": c.get("top_score"),
            "failure_reason": c.get("failure_reason", ""),
            "readback_queries": c.get("readback_queries", []),
            "write_error": c.get("write_error", ""),
        }
        entry["candidate_writes"].append(write_action)

        if c.get("actually_written"):
            entry["actually_written"] = True

        target = c.get("target_store", "ignore")
        importance = c.get("importance", 0)

        if target == "review" or c.get("requires_review"):
            entry["would_review"] = True
        elif target == "ignore" or importance < 0.40:
            entry["would_ignore"] = True
        elif importance >= 0.40:
            entry["would_write"] = True

    # Append to daily log file
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(_SHADOW_LOG_DIR, f"shadow_{date_str}.jsonl")

    with open(log_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.debug("Shadow write logged: %d candidates, would_write=%s",
                 len(candidates), entry["would_write"])

    return entry


def generate_readback_queries(candidate: Dict[str, Any]) -> List[str]:
    """Generate readback queries for a candidate write (dry-run)."""
    subject = candidate.get("subject", "")
    predicate = candidate.get("predicate", "")
    obj = candidate.get("object_value", "")

    queries = []

    if subject and predicate:
        queries.append(f"{subject} {predicate}")
    if subject and obj:
        queries.append(f"{subject} {obj[:20]}")

    # Type-specific queries
    mtype = candidate.get("memory_type", "")
    if mtype == "user_fact":
        queries.append(f"{subject}的成绩")
        queries.append(f"{subject}的年龄")
    elif mtype == "project_fact":
        queries.append(f"{subject}技术栈")
        queries.append(f"{subject}部署")
    elif mtype == "preference":
        queries.append(f"用户偏好")
        queries.append(f"用户关心什么")
    elif mtype == "task":
        queries.append(f"待办任务")
        queries.append(f"明天做什么")
    elif mtype == "rule":
        queries.append(f"操作规则")
        queries.append(f"注意事项")

    return queries[:3]  # Max 3 queries


def get_shadow_stats(date_str: Optional[str] = None) -> Dict[str, Any]:
    """Get comprehensive shadow write statistics for a date."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    log_file = os.path.join(_SHADOW_LOG_DIR, f"shadow_{date_str}.jsonl")
    if not os.path.exists(log_file):
        return {"date": date_str, "entries": 0}

    entries = []
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    # Aggregate statistics
    total_candidates = sum(len(e.get("candidate_writes", [])) for e in entries)
    would_write = sum(1 for e in entries if e.get("would_write"))
    would_review = sum(1 for e in entries if e.get("would_review"))
    would_ignore = sum(1 for e in entries if e.get("would_ignore"))

    by_type = {}
    by_target = {}
    importance_scores = []
    high_confidence = 0
    low_confidence = 0
    duplicate_candidates = 0
    conflict_candidates = 0
    unknown_namespace = 0
    core_write_attempts = 0
    md_write_attempts = 0

    seen_dedup_keys = set()

    for e in entries:
        ns = e.get("namespace", "")
        if not ns or ns == "":
            unknown_namespace += 1

        for c in e.get("candidate_writes", []):
            mtype = c.get("memory_type", "unknown")
            target = c.get("target_store", "ignore")
            importance = c.get("importance_score", 0)

            by_type[mtype] = by_type.get(mtype, 0) + 1
            by_target[target] = by_target.get(target, 0) + 1
            importance_scores.append(importance)

            if importance >= 0.85:
                high_confidence += 1
            elif importance < 0.50:
                low_confidence += 1

            # Dedup check
            dedup_key = c.get("dedup_key", "")
            if dedup_key:
                if dedup_key in seen_dedup_keys:
                    duplicate_candidates += 1
                seen_dedup_keys.add(dedup_key)

            # Core write check
            if target == "memory_graph" and "core://" in c.get("target_path", ""):
                core_write_attempts += 1

            # MD write check
            if target == "memory_md":
                md_write_attempts += 1

    avg_importance = sum(importance_scores) / len(importance_scores) if importance_scores else 0

    # Generate readback queries for top candidates
    readback_candidates = []
    for e in entries:
        for c in e.get("candidate_writes", []):
            if c.get("importance_score", 0) >= 0.70:
                queries = generate_readback_queries(c)
                readback_candidates.append({
                    "subject": c.get("subject"),
                    "predicate": c.get("predicate"),
                    "readback_queries": queries,
                    "target_path": c.get("target_path"),
                })

    return {
        "date": date_str,
        "entries": len(entries),
        "turns_processed": len(entries),
        "reflection_generated_count": len(entries),
        "candidate_write_count": total_candidates,
        "would_write_count": would_write,
        "would_review_count": would_review,
        "would_ignore_count": would_ignore,
        "target_store_distribution": by_target,
        "memory_type_distribution": by_type,
        "avg_importance_score": round(avg_importance, 3),
        "high_confidence_count": high_confidence,
        "low_confidence_count": low_confidence,
        "duplicate_candidate_count": duplicate_candidates,
        "conflict_candidate_count": conflict_candidates,
        "unknown_namespace_count": unknown_namespace,
        "core_write_attempt_count": core_write_attempts,
        "memory_md_write_attempt_count": md_write_attempts,
        "readback_candidates": readback_candidates[:10],
    }
