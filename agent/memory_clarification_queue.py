"""Clarification-on-use queue for uncertain memory candidates.

This replaces low-ROI batch review for risky/uncertain memories with a natural
conversation loop: keep a compact pending candidate, surface it only when the
current user query is relevant, and ask the user to confirm/correct it before
promoting it to canonical memory.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

DEFAULT_QUEUE_PATH = "~/.hermes/logs/memory_clarification_queue.jsonl"


@dataclass(frozen=True)
class ClarificationCandidate:
    id: str
    namespace: str
    subject: str
    predicate: str
    memory_type: str
    target_path: str
    reason: str
    risk: str
    content_preview: str
    evidence_preview: str
    source_type: str
    confidence: float
    created_at: str


def _path(path: str | None = None) -> Path:
    return Path(os.path.expanduser(path or DEFAULT_QUEUE_PATH))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _preview(text: str, *, limit: int = 500, redacted: bool = False) -> str:
    clean = _normalize(text)
    if not clean:
        return ""
    if redacted:
        return "[redacted: sensitive clarification candidate]"
    return clean[:limit]


def _has_secret(text: str) -> bool:
    return bool(re.search(
        r"(sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_|xox[baprs]-|AKIA[0-9A-Z]{16}|token\s*[:=]|api[_ -]?key\s*[:=]|密码|密钥)",
        text or "",
        re.I,
    ))


def _candidate_id(namespace: str, subject: str, predicate: str, value: str) -> str:
    raw = "|".join([namespace, subject, predicate, value])
    return "mc_" + hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:18]


def classify_clarification_risk(candidate: Any, classification: dict[str, Any] | None = None) -> str:
    classification = classification or {}
    if classification.get("conflict_with") or getattr(candidate, "conflict_with", ""):
        return "conflict"
    source_type = getattr(candidate, "source_type", "")
    memory_type = getattr(candidate, "memory_type", "")
    text = "\n".join([
        getattr(candidate, "subject", ""),
        getattr(candidate, "predicate", ""),
        getattr(candidate, "object_value", ""),
        getattr(candidate, "evidence_quote", ""),
        getattr(candidate, "target_path", ""),
    ])
    if _has_secret(text) or re.search(r"(credential|secret|token|api[_ -]?key|凭据|密钥|密码)", text, re.I):
        return "sensitive"
    if source_type == "agent_inference":
        return "inference"
    if float(getattr(candidate, "confidence", 0.0) or 0.0) < 0.85:
        return "low_confidence"
    if memory_type == "project_fact":
        return "project_fact"
    if memory_type in {"hindsight_import", "external_import"} or source_type in {"hindsight_import", "external_import"}:
        return "external_import"
    namespace = classification.get("namespace") or getattr(candidate, "namespace", "") or ""
    if not namespace or namespace == "core":
        return "cross_namespace"
    return "uncertain"


def record_clarification_candidate(
    candidate: Any,
    classification: dict[str, Any],
    *,
    queue_path: str | None = None,
) -> dict[str, Any]:
    namespace = classification.get("namespace") or getattr(candidate, "namespace", "") or ""
    raw_value = getattr(candidate, "object_value", "") or ""
    raw_evidence = getattr(candidate, "evidence_quote", "") or ""
    risk = classify_clarification_risk(candidate, classification)
    redacted = risk == "sensitive"
    item = {
        "schema_version": 1,
        "id": _candidate_id(namespace, getattr(candidate, "subject", ""), getattr(candidate, "predicate", ""), raw_value),
        "status": "pending",
        "namespace": namespace,
        "subject": getattr(candidate, "subject", ""),
        "predicate": getattr(candidate, "predicate", ""),
        "memory_type": getattr(candidate, "memory_type", ""),
        "target_path": classification.get("target_path") or getattr(candidate, "target_path", ""),
        "reason": classification.get("reason") or getattr(candidate, "reason", "") or risk,
        "risk": risk,
        "content_preview": _preview(raw_value, redacted=redacted),
        "evidence_preview": _preview(raw_evidence, redacted=redacted),
        "source_type": getattr(candidate, "source_type", ""),
        "confidence": float(getattr(candidate, "confidence", 0.0) or 0.0),
        "importance": float(getattr(candidate, "importance", 0.0) or 0.0),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_surfaced_at": "",
        "surface_count": 0,
        "value_sha256": hashlib.sha256(raw_value.encode("utf-8", "ignore")).hexdigest() if raw_value else "",
    }
    path = _path(queue_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids = set()
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    existing_ids.add(json.loads(line).get("id"))
                except Exception:
                    continue
    if item["id"] not in existing_ids:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def _tokens(text: str) -> set[str]:
    raw = _normalize(text).lower()
    latin = set(re.findall(r"[a-z0-9_+-]{3,}", raw))
    cjk_terms = set(re.findall(r"[\u4e00-\u9fff]{2,}", raw))
    cjk_chars = set(re.findall(r"[\u4e00-\u9fff]", raw))
    tokens = latin | cjk_terms | cjk_chars
    # Compact bilingual aliases for common memory-clarification queries.  This
    # keeps candidates discoverable when the stored fact is English but the user
    # asks with Chinese operational vocabulary, without broad fuzzy matching.
    alias_groups = [
        {"credential", "credentials", "凭据", "密钥", "token", "令牌", "api_key", "key"},
        {"config", "configuration", "配置", "设置"},
        {"claude", "claude-code", "claude_code"},
        {"login", "logged", "logged-in", "not", "登录"},
    ]
    for group in alias_groups:
        if tokens & group:
            tokens |= group
    return tokens


def _load_pending(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("status", "pending") == "pending":
                rows.append(row)
    return rows


def relevant_clarification_candidates(
    query: str,
    *,
    namespace: str = "",
    queue_path: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    matches: list[tuple[int, dict[str, Any]]] = []
    for row in _load_pending(_path(queue_path)):
        row_ns = row.get("namespace") or ""
        if namespace and row_ns and row_ns != namespace:
            continue
        haystack = " ".join(str(row.get(k, "")) for k in ["subject", "predicate", "memory_type", "target_path", "reason", "content_preview", "evidence_preview"])
        row_tokens = _tokens(haystack)
        score = len(query_tokens & row_tokens)
        if score >= 2 or (row.get("subject") and str(row.get("subject")).lower() in query.lower()):
            matches.append((score, row))
    matches.sort(key=lambda item: (-item[0], item[1].get("created_at", "")))
    return [row for _, row in matches[:limit]]


def build_clarification_context_block(
    query: str,
    *,
    namespace: str = "",
    queue_path: str | None = None,
    limit: int = 3,
) -> str:
    rows = relevant_clarification_candidates(query, namespace=namespace, queue_path=queue_path, limit=limit)
    if not rows:
        return ""
    lines = [
        "# Memory Clarification Candidates",
        "System note: These are uncertain memory candidates, not established facts. Do not batch-review them. If the current task would rely on one, ask the user a short natural clarification, then use the answer to update memory.",
    ]
    for row in rows:
        lines.append(
            f"- id={row.get('id')} risk={row.get('risk')} type={row.get('memory_type')} "
            f"subject={row.get('subject')} target={row.get('target_path')} "
            f"candidate={row.get('content_preview')} reason={row.get('reason')}"
        )
    return "\n".join(lines)


__all__ = [
    "DEFAULT_QUEUE_PATH",
    "classify_clarification_risk",
    "record_clarification_candidate",
    "relevant_clarification_candidates",
    "build_clarification_context_block",
]
