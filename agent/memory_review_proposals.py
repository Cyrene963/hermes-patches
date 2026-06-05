"""Generic review-proposal layer for Memory OS shadow candidates.

This module is intentionally IO-light and store-agnostic. It converts already
extracted memory candidates into portable review proposals and aggregate reports;
callers decide where proposals are persisted or which backing memory store writes
approved changesets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
import argparse
import hashlib
import json
import os


@dataclass(frozen=True)
class MemoryCandidate:
    kind: str
    content: str
    evidence_quote: str
    subject: str
    scope: str
    durability: str
    confidence: float
    risk_level: str
    requires_review: bool
    suggested_store: str
    namespace_security_scope: str
    readback_queries: List[str] = field(default_factory=list)
    supersedes: List[str] = field(default_factory=list)
    conflict_with: List[str] = field(default_factory=list)
    reason: str = ""
    source: str = "shadow_write"
    evidence_id: str = ""
    target_path: str = ""


@dataclass(frozen=True)
class LearningEventClassification:
    kind: str
    durability: str
    confidence: float
    risk_level: str
    requires_review: bool
    suggested_store: str
    reason: str


@dataclass(frozen=True)
class MemoryWriteDecision:
    action: str  # auto_write | review | ignore | evidence_only | supersede | reject
    reason: str
    requires_review: bool
    target_store: str
    risk_level: str


@dataclass(frozen=True)
class ReadbackResult:
    queries: List[str]
    ok: bool = False
    top_uri: str = ""
    top_score: Optional[float] = None
    reason: str = ""


@dataclass(frozen=True)
class MemoryChangeSet:
    changeset_id: str
    operator: str
    namespace: str
    operation_type: str
    target_path_uri: str
    before_snapshot: Dict[str, Any]
    after_snapshot: Dict[str, Any]
    diff: str
    evidence_id: str
    evidence_quote: str
    reason: str
    review_status: str
    rollback_method: str


@dataclass(frozen=True)
class ReviewProposal:
    proposal_id: str
    candidate: MemoryCandidate
    decision: MemoryWriteDecision
    changeset: MemoryChangeSet
    readback: ReadbackResult
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _risk_level(raw: Mapping[str, Any], namespace: str) -> str:
    kind = str(raw.get("memory_type") or raw.get("kind") or "unknown")
    reason = str(raw.get("reason") or "").lower()
    content = str(raw.get("object") or raw.get("object_value") or raw.get("content") or "")
    if any(marker in content.lower() for marker in ["api key", "token", "secret", "password", "credential"]):
        return "sensitive"
    if kind in {"relationship_or_stakeholder_model", "credential_route"}:
        return "high"
    if raw.get("requires_review") or "sensitive" in reason or str(raw.get("target_store")) == "review":
        return "medium"
    if not namespace:
        return "medium"
    return "low"


def _durability(kind: str, importance: float) -> str:
    if kind in {"temporary_state", "temporary", "ignore", "noise"}:
        return "minutes"
    if importance >= 0.85:
        return "long_term"
    if importance >= 0.40:
        return "evidence_only"
    return "none"


def _candidate_action(raw: Mapping[str, Any]) -> str:
    target = str(raw.get("target_store") or "ignore")
    importance = _float(raw.get("importance_score", raw.get("importance", 0.0)))
    if raw.get("actually_written"):
        return "auto_write"
    if raw.get("requires_review") or target == "review":
        return "review"
    if target == "ignore" or importance < 0.40:
        return "ignore"
    if target in {"hindsight", "evidence"}:
        return "evidence_only"
    return "review"


def normalize_shadow_candidate(entry: Mapping[str, Any], raw: Mapping[str, Any]) -> MemoryCandidate:
    namespace = str(raw.get("namespace") or entry.get("namespace") or "")
    kind = str(raw.get("memory_type") or raw.get("kind") or "unknown")
    content = str(raw.get("object") or raw.get("object_value") or raw.get("content") or "")
    confidence = _float(raw.get("confidence", raw.get("importance_score", raw.get("importance", 0.0))))
    importance = _float(raw.get("importance_score", raw.get("importance", confidence)))
    evidence_quote = str(raw.get("evidence_quote") or entry.get("user_message") or content)[:1000]
    evidence_payload = {
        "timestamp": entry.get("timestamp"),
        "conversation_id": entry.get("conversation_id"),
        "subject": raw.get("subject"),
        "predicate": raw.get("predicate"),
        "evidence_quote": evidence_quote,
    }
    return MemoryCandidate(
        kind=kind,
        content=content,
        evidence_quote=evidence_quote,
        subject=str(raw.get("subject") or "unknown"),
        scope="private" if namespace else "unresolved",
        durability=_durability(kind, importance),
        confidence=max(0.0, min(1.0, confidence)),
        risk_level=_risk_level(raw, namespace),
        requires_review=bool(raw.get("requires_review")) or _candidate_action(raw) == "review",
        suggested_store=str(raw.get("target_store") or "ignore"),
        namespace_security_scope=namespace,
        readback_queries=[str(q) for q in raw.get("readback_queries") or [] if str(q).strip()],
        supersedes=[],
        conflict_with=[str(raw.get("conflict_with"))] if raw.get("conflict_with") else [],
        reason=str(raw.get("reason") or raw.get("failure_reason") or ""),
        source="shadow_write",
        evidence_id=_stable_id("ev", evidence_payload),
        target_path=str(raw.get("target_path") or ""),
    )


def decide_candidate(candidate: MemoryCandidate, raw: Mapping[str, Any]) -> MemoryWriteDecision:
    action = _candidate_action(raw)
    reason = str(raw.get("failure_reason") or raw.get("reason") or "")
    if action == "auto_write" and not raw.get("readback_ok"):
        action = "review"
        reason = reason or "write lacked verified readback"
    if not candidate.namespace_security_scope and action not in {"ignore", "evidence_only"}:
        action = "review"
        reason = reason or "namespace unresolved; private/core safety requires review"
    if candidate.risk_level in {"medium", "high", "sensitive"} and action == "auto_write":
        action = "review"
        reason = reason or "risk level requires supervised review"
    if not reason:
        reason = {
            "review": "candidate requires supervised review before durable write",
            "ignore": "candidate is low value or explicitly ignored",
            "evidence_only": "candidate should remain evidence until promoted",
            "auto_write": "candidate was already written and verified",
        }.get(action, "policy decision")
    return MemoryWriteDecision(
        action=action,
        reason=reason,
        requires_review=action == "review" or candidate.requires_review,
        target_store=candidate.suggested_store,
        risk_level=candidate.risk_level,
    )


def make_review_proposal(entry: Mapping[str, Any], raw: Mapping[str, Any], operator: str = "memory-os-review") -> ReviewProposal:
    candidate = normalize_shadow_candidate(entry, raw)
    decision = decide_candidate(candidate, raw)
    after = {
        "kind": candidate.kind,
        "content": candidate.content,
        "target_path": candidate.target_path,
        "namespace": candidate.namespace_security_scope,
        "evidence_id": candidate.evidence_id,
    }
    proposal_payload = {"candidate": asdict(candidate), "decision": asdict(decision)}
    proposal_id = _stable_id("rp", proposal_payload)
    changeset = MemoryChangeSet(
        changeset_id=_stable_id("cs", {"proposal_id": proposal_id, "after": after}),
        operator=operator,
        namespace=candidate.namespace_security_scope,
        operation_type="propose_write" if decision.action == "review" else decision.action,
        target_path_uri=candidate.target_path,
        before_snapshot={},
        after_snapshot=after,
        diff=json.dumps({"before": {}, "after": after}, ensure_ascii=False, sort_keys=True),
        evidence_id=candidate.evidence_id,
        evidence_quote=candidate.evidence_quote,
        reason=decision.reason,
        review_status="pending" if decision.action == "review" else decision.action,
        rollback_method="reject proposal before write" if decision.action == "review" else "delete or supersede written memory by changeset id",
    )
    readback = ReadbackResult(
        queries=candidate.readback_queries,
        ok=bool(raw.get("readback_ok")),
        top_uri=str(raw.get("top_uri") or raw.get("uri") or ""),
        top_score=raw.get("top_score"),
        reason=str(raw.get("failure_reason") or ""),
    )
    return ReviewProposal(proposal_id=proposal_id, candidate=candidate, decision=decision, changeset=changeset, readback=readback)


def iter_shadow_entries(paths: Iterable[Path]) -> Iterable[Dict[str, Any]]:
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry.setdefault("_shadow_file", str(path))
                    entry.setdefault("_line", line_no)
                    yield entry
                except json.JSONDecodeError:
                    yield {"_shadow_file": str(path), "_line": line_no, "parse_error": True, "raw": line[:200]}


def build_shadow_report(entries: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "entries": 0,
        "candidates": 0,
        "by_would_write": {},
        "by_would_review": {},
        "by_would_ignore": {},
        "by_actually_written": {},
        "by_failure_reason": {},
        "by_target_store": {},
        "by_subject_kind": {},
        "by_namespace": {},
        "high_value_unwritten": 0,
        "parse_errors": 0,
    }
    for entry in entries:
        if entry.get("parse_error"):
            report["parse_errors"] += 1
            continue
        report["entries"] += 1
        namespace = str(entry.get("namespace") or "<missing>")
        report["by_namespace"][namespace] = report["by_namespace"].get(namespace, 0) + 1
        for raw in entry.get("candidate_writes") or []:
            report["candidates"] += 1
            action = _candidate_action(raw)
            if action == "review":
                key = "true"
                report["by_would_review"][key] = report["by_would_review"].get(key, 0) + 1
            elif action in {"auto_write", "evidence_only"}:
                key = "true"
                report["by_would_write"][key] = report["by_would_write"].get(key, 0) + 1
            elif action == "ignore":
                key = "true"
                report["by_would_ignore"][key] = report["by_would_ignore"].get(key, 0) + 1
            written_key = str(bool(raw.get("actually_written"))).lower()
            report["by_actually_written"][written_key] = report["by_actually_written"].get(written_key, 0) + 1
            failure = str(raw.get("failure_reason") or raw.get("write_error") or "<none>")[:160]
            report["by_failure_reason"][failure] = report["by_failure_reason"].get(failure, 0) + 1
            target = str(raw.get("target_store") or "ignore")
            report["by_target_store"][target] = report["by_target_store"].get(target, 0) + 1
            sk = f"{raw.get('subject') or 'unknown'}::{raw.get('memory_type') or 'unknown'}"
            report["by_subject_kind"][sk] = report["by_subject_kind"].get(sk, 0) + 1
            if not raw.get("actually_written") and _float(raw.get("importance_score")) >= 0.85:
                report["high_value_unwritten"] += 1
    return report


def proposals_from_shadow(entries: Iterable[Mapping[str, Any]], min_importance: float = 0.85) -> List[ReviewProposal]:
    proposals: List[ReviewProposal] = []
    seen = set()
    for entry in entries:
        if entry.get("parse_error"):
            continue
        for raw in entry.get("candidate_writes") or []:
            if raw.get("actually_written"):
                continue
            if _float(raw.get("importance_score")) < min_importance and not raw.get("requires_review"):
                continue
            proposal = make_review_proposal(entry, raw)
            if proposal.proposal_id in seen:
                continue
            seen.add(proposal.proposal_id)
            if proposal.decision.action == "review":
                proposals.append(proposal)
    return proposals


def _shadow_paths(log_dir: Path, days: int) -> List[Path]:
    files = sorted(log_dir.glob("shadow_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:max(1, days)]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize shadow memory candidates and optionally create review proposals.")
    parser.add_argument("--log-dir", default="~/.hermes/logs/shadow_writes")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--min-importance", type=float, default=0.85)
    parser.add_argument("--write-proposals", action="store_true")
    parser.add_argument("--proposal-path", default="~/.hermes/logs/memory_review_queue/review_proposals.jsonl")
    args = parser.parse_args(argv)

    log_dir = Path(os.path.expanduser(args.log_dir))
    paths = _shadow_paths(log_dir, args.days)
    entries = list(iter_shadow_entries(paths))
    report = build_shadow_report(entries)
    proposals = proposals_from_shadow(entries, min_importance=args.min_importance)
    output = {"shadow_files": [str(p) for p in paths], "report": report, "proposal_count": len(proposals)}
    if args.write_proposals:
        proposal_path = Path(os.path.expanduser(args.proposal_path))
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        with proposal_path.open("w", encoding="utf-8") as handle:
            for proposal in proposals:
                handle.write(json.dumps(asdict(proposal), ensure_ascii=False) + "\n")
        output["proposal_path"] = str(proposal_path)
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
