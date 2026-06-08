"""Standalone Memory OS review-proposal bridge for Memory Graph WebUI.

This bridge lets the existing Memory Graph human review workbench display and
triage pending standalone Memory OS ReviewProposal candidates.

Safety boundaries:
- summaries are redacted by default;
- reject only mutates the proposal JSONL status;
- approve is fail-closed and only writes candidates that explicitly target
  Memory Graph, then records row-level changes so the existing Graph review
  workbench can roll them back.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException, Query, Request
from filelock import FileLock
from pydantic import BaseModel

from auth import get_user, verify_session_token
from db import get_graph_service, get_search_indexer
from db.namespace import reset_is_admin, reset_namespace, set_is_admin, set_namespace
from db.snapshot import get_changeset_store

router = APIRouter(prefix="/api/proposal-review", tags=["proposal-review"])
_DEFAULT_REVIEW_JSONL = Path.home() / ".hermes" / "logs" / "memory_review_queue" / "review_proposals.current.jsonl"
_ALLOWED_APPROVE_TARGET_STORES = {"memory_graph"}
_COOKIE_NAME = "mg_session"


def _current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_session_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _is_admin_user(user: dict[str, Any]) -> bool:
    return user.get("role") == "admin" or user.get("username") == "admin"


def _visible_proposals_for_user(proposals: Iterable[dict[str, Any]], user: dict[str, Any]) -> list[dict[str, Any]]:
    if _is_admin_user(user):
        return list(proposals)
    namespace = str(user.get("namespace", "") or "")
    if not namespace:
        return []
    return [p for p in proposals if _candidate_namespace(p) == namespace]


def _assert_can_access_proposal(payload: dict[str, Any], user: dict[str, Any]) -> None:
    if _is_admin_user(user):
        return
    namespace = str(user.get("namespace", "") or "")
    if not namespace or _candidate_namespace(payload) != namespace:
        raise HTTPException(status_code=403, detail="Proposal is outside current user's namespace")


def _review_jsonl_path() -> Path:
    configured = os.environ.get("MEMORY_OS_REVIEW_JSONL") or os.environ.get("MG_MEMORY_OS_REVIEW_JSONL")
    if configured:
        return Path(configured).expanduser()
    return _DEFAULT_REVIEW_JSONL


def _candidate_kind(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") or {}
    for key in ("memory_type", "kind", "type"):
        value = str(metadata.get(key, "") or candidate.get(key, "") or "").strip()
        if value:
            return value
    return "unknown"


def _increment(bucket: dict[str, int], key: Any) -> None:
    safe = str(key or "").strip() or "unknown"
    bucket[safe] = bucket.get(safe, 0) + 1


def _redacted_preview(value: Any, max_chars: int = 120) -> dict[str, Any]:
    text = "" if value is None else str(value)
    return {"redacted": True, "text": "[redacted]", "truncated": bool(text), "length": len(text), "max_chars": max_chars}


def _proposal_action_hint(payload: dict[str, Any]) -> dict[str, str]:
    """Return a redacted, UI-safe action hint for supervised proposal triage.

    This intentionally uses only metadata such as target_store/kind/target_path
    and never returns raw candidate/evidence content.
    """
    candidate = payload.get("candidate") or {}
    decision = payload.get("decision") or {}
    metadata = candidate.get("metadata") or {}
    target_store = str(metadata.get("target_store", "") or decision.get("target_store", "") or candidate.get("suggested_store", "") or "")
    kind = _candidate_kind(candidate)
    target_path = str(metadata.get("target_path", "") or candidate.get("target_path", "") or (payload.get("changeset") or {}).get("target_path_uri", "") or "")
    risk = str(candidate.get("risk_level", "") or decision.get("risk_level", "") or "")

    if target_store == "memory_graph":
        return {
            "action": "eligible_memory_graph_approval_review",
            "label": "Ready for Memory Graph approval review",
            "tone": "emerald",
            "reason": "Direct approval is allowed, but still requires readback verification.",
        }
    if target_store == "review":
        if "工具凭据查找规则" in target_path or "credential" in target_path.lower():
            return {
                "action": "needs_private_tool_route_memory_conversion",
                "label": "Convert to private tool-route memory",
                "tone": "sky",
                "reason": "Looks like a durable credential/tool-route rule; keep private and verify recall.",
            }
        if "程序性记忆" in target_path or kind == "procedural_memory":
            return {
                "action": "needs_skill_or_procedural_memory_conversion",
                "label": "Convert to procedural memory / skill",
                "tone": "purple",
                "reason": "Looks like reusable procedure; convert into a maintained skill or procedural memory.",
            }
        if "纠错" in target_path:
            return {
                "action": "needs_memory_graph_conversion",
                "label": "Convert to correction memory",
                "tone": "amber",
                "reason": "Looks like a durable correction; write privately and verify future recall.",
            }
        if "考试上下文" in target_path:
            return {
                "action": "needs_private_context_memory_conversion",
                "label": "Convert to private context memory",
                "tone": "indigo",
                "reason": "Looks like private context; write under the owner namespace after review.",
            }
        if kind in {"user_fact", "project_fact", "preference", "rule", "task", "decision", "explicit_correction"}:
            return {
                "action": "needs_memory_graph_conversion",
                "label": "Convert to Memory Graph candidate",
                "tone": "amber",
                "reason": "Durable kind is present but target_store=review; needs supervised conversion.",
            }
    return {
        "action": "manual_review",
        "label": "Manual review required",
        "tone": "slate",
        "reason": f"No safe automatic conversion route for kind={kind or 'unknown'}, target_store={target_store or 'unknown'}, risk={risk or 'unknown'}.",
    }


def _proposal_summary(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate") or {}
    decision = payload.get("decision") or {}
    metadata = candidate.get("metadata") or {}
    privacy = str(candidate.get("privacy", "") or candidate.get("scope", "") or "")
    redacted_risk = bool(decision.get("redacted")) or privacy in {"sensitive", "admin_only", "private"}
    target_path = str(metadata.get("target_path", "") or candidate.get("target_path", "") or "")
    namespace = str(
        payload.get("namespace", "")
        or candidate.get("namespace", "")
        or candidate.get("namespace_security_scope", "")
        or (payload.get("changeset") or {}).get("namespace", "")
    )
    action_hint = _proposal_action_hint(payload)
    return {
        "proposal_id": str(payload.get("id", "") or payload.get("proposal_id", "")),
        "namespace": namespace,
        "status": str(payload.get("status", "pending") or "pending"),
        "subject": str(candidate.get("subject", "")),
        "predicate": str(candidate.get("predicate", "") or candidate.get("kind", "")),
        "candidate_kind": _candidate_kind(candidate),
        "memory_type": str(metadata.get("memory_type", "") or candidate.get("kind", "")),
        "confidence": candidate.get("confidence"),
        "importance": candidate.get("importance"),
        "source_type": str(candidate.get("source_type", "") or candidate.get("source", "")),
        "target_store": str(metadata.get("target_store", "") or candidate.get("suggested_store", "")),
        "target_path": "[redacted]" if target_path else "",
        "target_path_present": bool(target_path),
        "requires_review": bool(candidate.get("requires_review")) or bool(decision.get("requires_review", True)),
        "risk": "redacted" if redacted_risk else "standard",
        "reason": str(payload.get("reason", "") or candidate.get("reason", "") or decision.get("reason", "") or ""),
        "policy_reason": str(metadata.get("policy_reason", "") or candidate.get("reason", "")),
        "failure_reason": str(metadata.get("failure_reason", "")),
        "readback_query_count": len(payload.get("readback_queries") or candidate.get("readback_queries") or (payload.get("readback") or {}).get("queries") or []),
        "created_at": str(payload.get("created_at", "")),
        "updated_at": str(payload.get("updated_at", "")),
        "change_set_count": len(payload.get("change_sets") or ([payload.get("changeset")] if payload.get("changeset") else [])),
        "content_preview": _redacted_preview(candidate.get("value", candidate.get("content"))),
        "evidence_preview": _redacted_preview(payload.get("evidence_quote") or candidate.get("evidence_quote")),
        "action_hint": action_hint,
        "action_hint_action": action_hint["action"],
        "action_hint_label": action_hint["label"],
        "action_hint_tone": action_hint["tone"],
        "action_hint_reason": action_hint["reason"],
    }


def _load_proposals(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    proposals: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.exists():
        return proposals, errors
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append({"line": line_no, "error": f"invalid JSON: {exc}"})
                continue
            if not isinstance(payload, dict):
                errors.append({"line": line_no, "error": "proposal must be a JSON object"})
                continue
            proposals.append(payload)
    return proposals, errors


def _summarize(proposals: Iterable[dict[str, Any]], *, status: str, limit: int | None) -> dict[str, Any]:
    all_items = list(proposals)
    if status == "all":
        visible = all_items
    else:
        visible = [p for p in all_items if str(p.get("status", "pending") or "pending") == status]
    limited = visible[:limit] if limit is not None else visible

    by_namespace: dict[str, int] = {}
    by_candidate_kind: dict[str, int] = {}
    by_source_type: dict[str, int] = {}
    by_target_store: dict[str, int] = {}
    by_target_path: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    timestamps: list[str] = []

    for payload in visible:
        candidate = payload.get("candidate") or {}
        decision = payload.get("decision") or {}
        metadata = candidate.get("metadata") or {}
        namespace = (
            payload.get("namespace", "")
            or candidate.get("namespace", "")
            or candidate.get("namespace_security_scope", "")
            or (payload.get("changeset") or {}).get("namespace", "")
        )
        _increment(by_namespace, namespace)
        _increment(by_candidate_kind, _candidate_kind(candidate))
        _increment(by_source_type, candidate.get("source_type", "") or candidate.get("source", ""))
        _increment(by_target_store, metadata.get("target_store", "") or candidate.get("suggested_store", ""))
        target_path = metadata.get("target_path", "") or candidate.get("target_path", "")
        _increment(by_target_path, "present" if str(target_path or "").strip() else "missing")
        privacy = str(candidate.get("privacy", "") or candidate.get("scope", "") or "")
        risk_level = str(candidate.get("risk_level", "") or "")
        risk = "redacted" if bool(decision.get("redacted")) or privacy in {"sensitive", "admin_only", "private"} else (risk_level or "standard")
        _increment(by_risk, risk if (candidate.get("requires_review") or decision.get("requires_review", True)) else "low")
        _increment(by_reason, payload.get("reason") or candidate.get("reason") or decision.get("reason") or metadata.get("policy_reason") or "")
        if payload.get("created_at"):
            timestamps.append(str(payload.get("created_at")))

    return {
        "total_count": len(all_items),
        "filtered_count": len(visible),
        "pending_count": sum(1 for p in all_items if str(p.get("status", "pending") or "pending") == "pending"),
        "approved_count": sum(1 for p in all_items if str(p.get("status", "")) == "approved"),
        "rejected_count": sum(1 for p in all_items if str(p.get("status", "")) == "rejected"),
        "failed_count": sum(1 for p in all_items if str(p.get("status", "")) == "failed"),
        "by_namespace": by_namespace,
        "by_candidate_kind": by_candidate_kind,
        "by_memory_type": by_candidate_kind,
        "by_source_type": by_source_type,
        "by_target_store": by_target_store,
        "by_target_path": by_target_path,
        "by_risk": by_risk,
        "by_reason": by_reason,
        "oldest_created_at": min(timestamps) if timestamps else "",
        "newest_created_at": max(timestamps) if timestamps else "",
        "redacted": True,
        "limit": limit,
        "proposals": [_proposal_summary(p) for p in limited],
    }


class ProposalAction(BaseModel):
    reason: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _proposal_id(payload: dict[str, Any]) -> str:
    return str(payload.get("id", "") or payload.get("proposal_id", ""))


def _candidate_content(candidate: dict[str, Any]) -> str:
    return str(candidate.get("value", candidate.get("content", "")) or "")


def _candidate_target_store(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") or {}
    return str(metadata.get("target_store", "") or candidate.get("suggested_store", "") or "")


def _candidate_target_path(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") or {}
    return str(metadata.get("target_path", "") or candidate.get("target_path", "") or "")


def _candidate_namespace(payload: dict[str, Any]) -> str:
    candidate = payload.get("candidate") or {}
    return str(
        payload.get("namespace", "")
        or candidate.get("namespace", "")
        or candidate.get("namespace_security_scope", "")
        or (payload.get("changeset") or {}).get("namespace", "")
    )


def _candidate_readback_queries(payload: dict[str, Any]) -> list[str]:
    candidate = payload.get("candidate") or {}
    raw = payload.get("readback_queries") or candidate.get("readback_queries") or (payload.get("readback") or {}).get("queries") or []
    return [str(x) for x in raw if str(x).strip()]


def _read_all_with_lines(path: Path) -> tuple[list[tuple[str, dict[str, Any] | None]], list[dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any] | None]] = []
    errors: list[dict[str, Any]] = []
    if not path.exists():
        return rows, errors
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped:
                rows.append((raw, None))
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                errors.append({"line": line_no, "error": f"invalid JSON: {exc}"})
                rows.append((raw, None))
                continue
            rows.append((raw, payload if isinstance(payload, dict) else None))
    return rows, errors


def _rewrite_rows(path: Path, rows: list[tuple[str, dict[str, Any] | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for raw, payload in rows:
            if payload is None:
                handle.write(raw if raw.endswith("\n") else raw + "\n")
            else:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def _mutate_proposal(proposal_id: str, mutate) -> dict[str, Any]:
    path = _review_jsonl_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Review queue not found: {path}")
    lock = FileLock(str(path) + ".lock")
    with lock:
        rows, errors = _read_all_with_lines(path)
        if errors:
            raise HTTPException(status_code=409, detail={"message": "Review queue has parse errors", "errors": errors[:5]})
        updated_payload: dict[str, Any] | None = None
        for idx, (_raw, payload) in enumerate(rows):
            if not payload:
                continue
            if _proposal_id(payload) == proposal_id:
                updated_payload = mutate(payload)
                rows[idx] = (_raw, updated_payload)
                break
        if updated_payload is None:
            raise HTTPException(status_code=404, detail=f"Proposal not found: {proposal_id}")
        _rewrite_rows(path, rows)
        return updated_payload


def _mark_status(proposal_id: str, status: str, *, reason: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    def mutate(payload: dict[str, Any]) -> dict[str, Any]:
        current = str(payload.get("status", "pending") or "pending")
        if current != "pending" and status in {"approved", "rejected"}:
            raise HTTPException(status_code=409, detail=f"Proposal {proposal_id} is already {current}")
        payload["status"] = status
        payload["updated_at"] = _utc_now()
        if reason:
            payload.setdefault("review", {})["reason"] = reason
        payload.setdefault("review", {})["status"] = status
        payload["review"]["reviewed_at"] = payload["updated_at"]
        if extra:
            payload["review"].update(extra)
        return payload
    return _mutate_proposal(proposal_id, mutate)


def _split_target_path(target_path: str) -> tuple[str, str, str]:
    clean = target_path.strip().strip("/")
    if not clean:
        raise HTTPException(status_code=422, detail="Candidate target_path is empty")
    if "://" in clean:
        domain, clean = clean.split("://", 1)
        clean = clean.strip("/")
    else:
        domain = "core"
    parts = [part for part in clean.split("/") if part]
    if not parts:
        raise HTTPException(status_code=422, detail="Candidate target_path has no title")
    parent_path = "/".join(parts[:-1])
    title = parts[-1]
    return domain, parent_path, title


async def _verify_readback(namespace: str, domain: str, uri: str, content: str, queries: list[str]) -> dict[str, Any]:
    graph = get_graph_service()
    search = get_search_indexer()
    read = None
    if "://" in uri:
        read_domain, read_path = uri.split("://", 1)
    else:
        read_domain, read_path = domain, uri
    read = await graph.get_memory_by_path(read_path, domain=read_domain, namespace=namespace)
    read_ok = bool(read and str(read.get("content", "")) == content)
    search_checks = []
    for query in (queries or [content[:80]]):
        if not query.strip():
            continue
        results = await search.search(query=query, limit=5, domain=domain, namespace=namespace)
        top_uri = results[0].get("uri") if results else ""
        search_checks.append({"query": query, "top_uri": top_uri, "found": any(r.get("uri") == uri for r in results)})
    search_ok = bool(search_checks) and all(check["found"] for check in search_checks)
    return {"read_ok": read_ok, "search_ok": search_ok, "checks": search_checks, "uri": uri}


@router.get("/inbox")
async def proposal_review_inbox(
    request: Request,
    status: str = Query("pending", pattern="^(pending|approved|rejected|failed|all)$"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Return a redacted summary of standalone Memory OS review proposals.

    This endpoint is read-only. It never approves/rejects proposals and never
    writes to Memory Graph or standalone Memory OS canonical stores.
    """
    path = _review_jsonl_path()
    user = _current_user(request)
    proposals, errors = _load_proposals(path)
    visible_proposals = _visible_proposals_for_user(proposals, user)
    return {
        "source": "standalone-memory-os-review-jsonl",
        "review_jsonl": str(path),
        "exists": path.exists(),
        "errors": errors,
        "user_namespace": str(user.get("namespace", "") or ""),
        "is_admin": _is_admin_user(user),
        "inbox": _summarize(visible_proposals, status=status, limit=limit),
    }

@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, request: Request, action: ProposalAction | None = None) -> dict[str, Any]:
    """Reject a pending candidate without writing canonical memory."""
    user = _current_user(request)
    path = _review_jsonl_path()
    proposals, errors = _load_proposals(path)
    if errors:
        raise HTTPException(status_code=409, detail={"message": "Review queue has parse errors", "errors": errors[:5]})
    payload = next((p for p in proposals if _proposal_id(p) == proposal_id), None)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Proposal not found: {proposal_id}")
    _assert_can_access_proposal(payload, user)
    updated = _mark_status(proposal_id, "rejected", reason=(action.reason if action else None))
    return {"ok": True, "action": "rejected", "proposal": _proposal_summary(updated)}


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, request: Request, action: ProposalAction | None = None) -> dict[str, Any]:
    """Approve a pending candidate into Memory Graph with strict readback.

    Fail-closed safety:
    - Only target_store=memory_graph is eligible.
    - Existing target paths are not overwritten in this first bridge.
    - If create/read/search verification fails, proposal is marked failed, not approved.
    - Successful creates are also recorded in ChangesetStore so the existing
      Graph changes workbench can roll them back.
    """
    path = _review_jsonl_path()
    user = _current_user(request)
    rows, errors = _load_proposals(path)
    if errors:
        raise HTTPException(status_code=409, detail={"message": "Review queue has parse errors", "errors": errors[:5]})
    payload = next((p for p in rows if _proposal_id(p) == proposal_id), None)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Proposal not found: {proposal_id}")
    _assert_can_access_proposal(payload, user)
    status = str(payload.get("status", "pending") or "pending")
    if status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal {proposal_id} is already {status}")

    candidate = payload.get("candidate") or {}
    target_store = _candidate_target_store(candidate)
    if target_store not in _ALLOWED_APPROVE_TARGET_STORES:
        raise HTTPException(
            status_code=422,
            detail=f"Proposal target_store={target_store or 'unknown'} is not eligible for direct Memory Graph approval",
        )
    content = _candidate_content(candidate)
    if not content.strip():
        raise HTTPException(status_code=422, detail="Candidate content is empty")
    namespace = _candidate_namespace(payload)
    if not namespace.strip():
        raise HTTPException(status_code=422, detail="Candidate namespace is empty; refusing to write shared core by default")
    target_path = _candidate_target_path(candidate)
    domain, parent_path, title = _split_target_path(target_path)
    priority = int(candidate.get("priority", candidate.get("importance", 1)) or 1)
    disclosure = str(candidate.get("disclosure") or candidate.get("reason") or "Approved from supervised Memory OS candidate queue.")

    graph = get_graph_service()
    ns_token = set_namespace(namespace)
    # Creation inserts mg_memories before mg_paths; the current RLS policy for
    # mg_memories checks reachability through mg_paths, so direct create under a
    # normal namespace fails before the path exists. Use an admin RLS context for
    # this tightly-scoped create while still passing the proposal namespace into
    # GraphService, then require readback/search verification before marking the
    # proposal approved.
    admin_token = set_is_admin(True)
    try:
        existing = await graph.get_memory_by_path(target_path.split("://", 1)[-1].strip("/"), domain=domain, namespace=namespace)
        if existing:
            raise HTTPException(status_code=409, detail=f"Target path already exists: {domain}://{target_path}")
        result = await graph.create_memory(
            parent_path=parent_path,
            content=content,
            priority=priority,
            title=title,
            disclosure=disclosure,
            domain=domain,
            namespace=namespace,
        )
        uri = result.get("uri", f"{domain}://{result.get('path', target_path)}")
        verification = await _verify_readback(namespace, domain, uri, content, _candidate_readback_queries(payload))
        if not (verification.get("read_ok") and verification.get("search_ok")):
            _mark_status(
                proposal_id,
                "failed",
                reason="readback verification failed",
                extra={"memory_graph_result": result, "verification": verification},
            )
            raise HTTPException(status_code=500, detail={"message": "Readback verification failed", "verification": verification})

        get_changeset_store().record_many(before_state={}, after_state=result.get("rows_after", {}))
        updated = _mark_status(
            proposal_id,
            "approved",
            reason=(action.reason if action else None),
            extra={"memory_graph_result": {"uri": uri, "node_uuid": result.get("node_uuid")}, "verification": verification},
        )
        return {"ok": True, "action": "approved", "uri": uri, "verification": verification, "proposal": _proposal_summary(updated)}
    except HTTPException:
        raise
    except Exception as exc:
        _mark_status(proposal_id, "failed", reason=f"approval error: {exc}")
        raise HTTPException(status_code=500, detail=f"Approval failed: {exc}") from exc
    finally:
        reset_is_admin(admin_token)
        reset_namespace(ns_token)

