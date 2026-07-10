#!/usr/bin/env python3
"""Distill AI Studio user-authored raw candidates into atomic review proposals.

Safety contract:
- only role=user can become a durable-memory draft;
- one proposal contains one atomic fact;
- volatile/sensitive statements become clarification-on-use candidates;
- probable duplicates/conflicts remain non-approvable review items;
- this script never writes Memory Graph.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path(os.environ.get("AISTUDIO_REVIEW_QUEUE") or (Path.home() / ".hermes/memories/aistudio_gemini/review_queue.jsonl"))
DEFAULT_OUTPUT = Path.home() / ".hermes/logs/memory_review_queue/review_proposals.current.jsonl"
DEFAULT_CLARIFY = Path.home() / ".hermes/logs/memory_clarification_queue.jsonl"
DEFAULT_NAMESPACE = os.environ.get("AISTUDIO_OWNER_NAMESPACE", "")
DEFAULT_RULES = Path(os.environ.get("AISTUDIO_DISTILLATION_RULES") or (Path.home() / ".hermes/memories/aistudio_gemini/distillation_rules.json"))
RUNTIME_REPO = Path(os.environ.get("HERMES_RUNTIME_REPO") or (Path.home() / ".hermes/hermes-agent"))
if str(RUNTIME_REPO) not in sys.path and RUNTIME_REPO.exists():
    sys.path.insert(0, str(RUNTIME_REPO))


def load_rules(path: Path) -> tuple[str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    namespace = str(payload.get("namespace") or DEFAULT_NAMESPACE).strip()
    rules = payload.get("rules")
    if not namespace:
        raise ValueError("owner namespace is required; refusing shared default")
    if not isinstance(rules, list) or not rules:
        raise ValueError("distillation rules must be a non-empty list")
    required = {"id", "kind", "target", "draft", "query", "risk"}
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or not required.issubset(rule):
            raise ValueError(f"invalid rule at index {index}")
        has_source_id = bool(str(rule.get("source_candidate_id") or "").strip())
        has_match = isinstance(rule.get("match"), list) and bool(rule.get("match"))
        if has_source_id == has_match:
            raise ValueError(
                f"rule at index {index} must define exactly one source selector: "
                "source_candidate_id or non-empty match list"
            )
    return namespace, rules


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(value: Any, n: int = 18) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:n]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def source_for_rule(rule: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    source_id = str(rule.get("source_candidate_id") or "").strip()
    if source_id:
        return next((row for row in rows if str(row.get("candidate_id") or "") == source_id), None)
    patterns = rule.get("match") or []
    return next((row for row in rows if all(re.search(pattern, str(row.get("excerpt") or ""), re.I | re.S) for pattern in patterns)), None)


def graph_search(query: str, namespace: str) -> list[dict[str, Any]]:
    try:
        from tools import memory_graph_tool
        raw = memory_graph_tool._search({"query": query, "domain": "core", "limit": 8, "namespace": namespace})
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return list(payload.get("results") or [])
    except Exception:
        return []


def graph_read(uri: str, namespace: str) -> dict[str, Any] | None:
    try:
        from tools import memory_graph_tool
        raw = memory_graph_tool._read({"uri": uri, "domain": "core", "namespace": namespace})
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return None if payload.get("error") else payload
    except Exception:
        return None


def overlap_score(rule: dict[str, Any], result: dict[str, Any]) -> float:
    text = " ".join([str(result.get("name") or ""), str(result.get("path") or ""), str(result.get("snippet") or "")]).casefold()
    terms = [str(term).casefold() for term in rule.get("existing_terms") or [] if str(term).strip()]
    if not terms:
        return 0.0
    return sum(1 for term in terms if term in text) / len(terms)


def make_proposal(rule: dict[str, Any], row: dict[str, Any], namespace: str, graph_hits: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = " ".join(str(row.get("excerpt") or "").split())[:1800]
    evidence_id = "ev_ai_atomic_" + sha({"candidate": row.get("candidate_id"), "rule": rule["id"]})
    proposal_id = "rp_ai_atomic_" + sha({"namespace": namespace, "rule": rule["id"], "draft": rule["draft"]})
    ranked = sorted(((overlap_score(rule, hit), hit) for hit in graph_hits), key=lambda item: item[0], reverse=True)
    probable = [hit for score, hit in ranked if score >= 0.5][:3]
    target_path = str(rule["target"]).split("://", 1)[-1].strip("/")
    parent_path = target_path.rsplit("/", 1)[0] if "/" in target_path else ""
    parent_exists = True
    if parent_path:
        parent_exists = graph_read(f"core://{parent_path}", namespace) is not None
    canonical = graph_read(rule["target"], namespace)
    canonical_same = bool(canonical and " ".join(str(canonical.get("content") or "").split()) == " ".join(rule["draft"].split()))
    if canonical_same:
        review_state = "already_canonical"
    elif not parent_exists:
        review_state = "invalid_parent"
    else:
        review_state = "needs_dedup_review" if probable else "ready_memory"
    suggested_store = "memory_graph" if review_state == "ready_memory" else "review"
    candidate = {
        "kind": rule["kind"], "distilled": True, "content": rule["draft"],
        "evidence_quote": evidence, "confidence": 0.90, "importance": 1, "priority": 1,
        "durability": "long_term", "requires_review": True, "risk_level": rule["risk"],
        "scope": "private", "suggested_store": suggested_store,
        "namespace_security_scope": namespace, "target_path": rule["target"],
        "readback_queries": [rule["query"], rule["draft"][:150]],
        "reason": "atomic user-authored AI Studio memory draft; supervised review required",
        "source": "google_ai_studio_distilled", "evidence_id": evidence_id,
        "metadata": {
            "target_store": suggested_store, "distilled": True, "review_state": review_state,
            "parent_exists": parent_exists, "canonical_same": canonical_same,
            "source_candidate_id": row.get("candidate_id"), "conversation_id": row.get("conversation_id"),
            "turn_index": row.get("turn_index"),
            "possible_duplicate_uris": [str(hit.get("uri") or "") for hit in probable],
        },
    }
    after = {"kind": rule["kind"], "content": rule["draft"], "target_path": rule["target"], "namespace": namespace, "evidence_id": evidence_id}
    return {
        "proposal_id": proposal_id, "status": "pending", "created_at": now(), "candidate": candidate,
        "decision": {"action": "review", "target_store": suggested_store, "requires_review": True, "risk_level": rule["risk"], "reason": review_state},
        "changeset": {
            "changeset_id": "cs_ai_atomic_" + sha({"proposal": proposal_id, "after": after}),
            "operator": "aistudio-atomic-distiller", "namespace": namespace,
            "operation_type": "propose_write", "target_path_uri": rule["target"],
            "before_snapshot": {}, "after_snapshot": after,
            "diff": json.dumps({"before": {}, "after": after}, ensure_ascii=False, sort_keys=True),
            "evidence_id": evidence_id, "evidence_quote": evidence,
            "reason": review_state, "review_status": review_state,
            "rollback_method": "reject before write; if approved, rollback via recorded Memory Graph changeset",
        },
        "readback": {"queries": candidate["readback_queries"], "ok": False, "top_uri": "", "top_score": None, "reason": "not written yet"},
    }


def make_clarification(rule: dict[str, Any], row: dict[str, Any], namespace: str) -> dict[str, Any]:
    cid = "mc_ai_atomic_" + sha({"namespace": namespace, "rule": rule["id"], "draft": rule["draft"]})
    evidence = " ".join(str(row.get("excerpt") or "").split())[:500]
    return {
        "schema_version": 1, "id": cid, "status": "pending", "namespace": namespace,
        "subject": rule["id"], "predicate": "needs_current_confirmation", "memory_type": rule["kind"],
        "target_path": rule["target"], "reason": "sensitive or volatile AI Studio user statement; confirm only when relevant",
        "risk": rule["risk"], "content_preview": rule["draft"], "evidence_preview": evidence,
        "source_type": "google_ai_studio_distilled", "confidence": 0.82, "importance": 1.0,
        "created_at": now(), "last_surfaced_at": "", "surface_count": 0,
        "source_candidate_id": row.get("candidate_id"), "value_sha256": sha(rule["draft"], 64),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--clarification", type=Path, default=DEFAULT_CLARIFY)
    ap.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    ap.add_argument("--namespace", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    configured_namespace, rules = load_rules(args.rules)
    namespace = str(args.namespace or configured_namespace).strip()
    if not namespace:
        raise ValueError("owner namespace is required")
    raw = [row for row in load_jsonl(args.input) if row.get("role") == "user"]
    all_proposals: list[dict[str, Any]] = []
    clarifications: list[dict[str, Any]] = []
    matched_rules: set[str] = set()
    for rule in rules:
        source = source_for_rule(rule, raw)
        if not source:
            continue
        matched_rules.add(rule["id"])
        if rule.get("clarify"):
            clarifications.append(make_clarification(rule, source, namespace))
        else:
            all_proposals.append(make_proposal(rule, source, namespace, graph_search(rule["query"], namespace)))

    proposals = [p for p in all_proposals if p["candidate"]["metadata"]["review_state"] != "already_canonical"]
    canonical_count = len(all_proposals) - len(proposals)
    report = {
        "generated_at": now(), "apply": args.apply, "raw_user_candidates": len(raw),
        "rules_matched": sorted(matched_rules), "proposal_count": len(proposals),
        "clarification_count": len(clarifications),
        "already_canonical": canonical_count,
        "ready_memory": sum(1 for p in proposals if p["candidate"]["metadata"]["review_state"] == "ready_memory"),
        "needs_dedup_review": sum(1 for p in proposals if p["candidate"]["metadata"]["review_state"] == "needs_dedup_review"),
        "invalid_parent": sum(1 for p in proposals if p["candidate"]["metadata"]["review_state"] == "invalid_parent"),
        "memory_graph_writes": 0,
    }
    if args.apply:
        current_rows = load_jsonl(args.output)
        existing = [row for row in current_rows if (row.get("candidate") or {}).get("source") not in {"google_ai_studio", "google_ai_studio_distilled"}]
        canonical_ids = {
            p["proposal_id"] for p in all_proposals
            if p["candidate"]["metadata"]["review_state"] == "already_canonical"
        }
        reconciled = []
        for row in current_rows:
            if row.get("proposal_id") not in canonical_ids:
                continue
            candidate = row.get("candidate") or {}
            candidate.setdefault("metadata", {})["review_state"] = "already_canonical"
            candidate["metadata"]["canonical_same"] = True
            candidate["suggested_store"] = "memory_graph"
            row["candidate"] = candidate
            row["status"] = "approved"
            row["updated_at"] = now()
            row["review"] = {"status": "approved", "reviewed_at": now(), "reason": "reconciled with identical canonical Memory Graph content"}
            reconciled.append(row)
        atomic_write_jsonl(args.output, existing + reconciled + proposals)
        old_clarify = [row for row in load_jsonl(args.clarification) if row.get("source_type") != "google_ai_studio_distilled"]
        atomic_write_jsonl(args.clarification, old_clarify + clarifications)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(args.report, 0o600)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if len(matched_rules) == len(rules) else 2


if __name__ == "__main__":
    raise SystemExit(main())
