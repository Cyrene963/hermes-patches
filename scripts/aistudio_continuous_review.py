#!/usr/bin/env python3
"""Second-stage review for continuous AI Studio memory proposals.

Dry-run by default. Apply mode may reject/clarify proposals and may approve only
low-risk, evidence-backed, durable, useful, route-valid memories. Approval goes
through the Memory Graph proposal API, which performs create/read/search checks.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib import request

PROFILE = Path(os.environ.get("HERMES_PROFILE_DIR") or (Path.home() / ".hermes"))
BASE = Path(os.environ.get("AISTUDIO_MEMORY_BASE") or (PROFILE / "memories" / "aistudio_gemini"))
RUNTIME = Path(os.environ.get("HERMES_RUNTIME_REPO") or (PROFILE / "hermes-agent"))
if RUNTIME.exists() and str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))
QUEUE = PROFILE / "logs" / "memory_review_queue" / "review_proposals.current.jsonl"
CLARIFICATION = PROFILE / "logs" / "memory_clarification_queue.jsonl"
REPORTS = BASE / "reports"
LOCK = BASE / "continuous_distill.lock"
API_BASE = os.environ.get("MEMORY_GRAPH_WEBUI_URL", "http://127.0.0.1:8233").rstrip("/")

QUESTIONISH_RE = re.compile(r"(?:吗[？?]?|你觉得|能不能|可以不可以|有没有|如何|怎么|为什么|希望获得|想知道)", re.I)
LOW_UTILITY_RE = re.compile(r"(?:某一题|这一题|这篇作文|本次|这次|当前这局|新玩家|临时|先这么用|出了问题再修|某个武将)", re.I)
SENSITIVE_KIND = {"relationship"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.chmod(0o600); tmp.replace(path)


def demote_unconsented_ready_memory(row: dict[str, Any], *, demoted_at: str | None = None) -> bool:
    """Fail closed for legacy ready-memory rows without consensus evidence."""
    candidate = row.get("candidate") or {}
    metadata = candidate.get("metadata") or {}
    if row.get("status", "pending") != "pending":
        return False
    if candidate.get("suggested_store") != "memory_graph" or metadata.get("consensus_gate"):
        return False
    timestamp = demoted_at or now()
    candidate["suggested_store"] = "review"
    metadata["target_store"] = "review"
    metadata["review_state"] = "needs_consensus_review"
    metadata["demoted_reason"] = "missing_independent_consensus_gate"
    metadata["demoted_at"] = timestamp
    candidate["metadata"] = metadata
    decision = row.setdefault("decision", {})
    decision["action"] = "review"
    decision["target_store"] = "review"
    decision["reason"] = "missing independent consensus gate"
    row["updated_at"] = timestamp
    return True


def promote_ready_memory(row: dict[str, Any], *, consensus_gate: str, promoted_at: str | None = None) -> None:
    """Promote a reviewed proposal to the API's ready-memory stage.

    This is a state transition, not approval. The approval API still owns the
    Graph write and read/search verification.
    """
    candidate = row.get("candidate") or {}
    metadata = candidate.get("metadata") or {}
    if row.get("status", "pending") != "pending":
        raise ValueError("only pending proposals can be promoted")
    if not candidate.get("distilled"):
        raise ValueError("proposal is not distilled")
    if metadata.get("role") != "user":
        raise ValueError("only role=user evidence can be promoted")
    if metadata.get("requires_current_validation") and metadata.get("current_validation_status") != "confirmed_current":
        raise ValueError("historical learning evidence requires current validation before promotion")
    if candidate.get("risk_level") != "low" or metadata.get("volatility") in {"sensitive", "time_bound"}:
        raise ValueError("sensitive or volatile proposal cannot be promoted")
    if not candidate.get("readback_queries"):
        raise ValueError("proposal has no readback queries")
    timestamp = promoted_at or now()
    candidate["suggested_store"] = "memory_graph"
    metadata["target_store"] = "memory_graph"
    metadata["consensus_gate"] = consensus_gate
    metadata["consensus_promoted_at"] = timestamp
    candidate["metadata"] = metadata
    decision = row.setdefault("decision", {})
    decision["action"] = "review"
    decision["target_store"] = "memory_graph"
    decision["reason"] = f"promoted after {consensus_gate}"
    row["updated_at"] = timestamp


def graph_read(uri: str, namespace: str) -> str:
    try:
        from tools import memory_graph_tool
        raw = memory_graph_tool._read({"uri": uri, "domain": "core", "namespace": namespace})
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return str(payload.get("content") or "")[:800]
    except Exception:
        return ""


def candidate_payload(row: dict[str, Any]) -> dict[str, Any]:
    candidate = row.get("candidate") or {}
    metadata = candidate.get("metadata") or {}
    namespace = str(candidate.get("namespace_security_scope") or "")
    duplicates = []
    for uri in metadata.get("possible_duplicate_uris") or []:
        duplicates.append({"uri": uri, "content": graph_read(str(uri), namespace)})
    return {
        "proposal_id": row.get("proposal_id"), "kind": candidate.get("kind"),
        "fact": candidate.get("content"), "evidence_quote": candidate.get("evidence_quote"),
        "risk": candidate.get("risk_level"), "volatility": metadata.get("volatility"),
        "learning_state": metadata.get("learning_state"),
        "requires_current_validation": bool(metadata.get("requires_current_validation")),
        "current_validation_status": metadata.get("current_validation_status"),
        "observed_at": metadata.get("observed_at"),
        "target_path": candidate.get("target_path"), "review_state": metadata.get("review_state"),
        "duplicates": duplicates,
    }


def deterministic_block(item: dict[str, Any]) -> str:
    fact = str(item.get("fact") or "")
    evidence = str(item.get("evidence_quote") or "")
    if str(item.get("risk") or "") == "high" or str(item.get("volatility") or "") in {"sensitive", "time_bound"}:
        return "sensitive_or_volatile"
    if item.get("requires_current_validation") and str(item.get("current_validation_status") or "") != "confirmed_current":
        return "historical_learning_state_unverified"
    if str(item.get("kind") or "") in SENSITIVE_KIND:
        return "sensitive_kind"
    if len(fact) < 12 or len(evidence) < 4:
        return "insufficient_content"
    if QUESTIONISH_RE.search(evidence) and not re.search(r"(?:我(?:偏好|喜欢|不喜欢|要求|认为|相信|一直|习惯)|你(?:必须|不要|以后|别再))", evidence):
        return "question_or_request_not_preference"
    if LOW_UTILITY_RE.search(fact):
        return "too_narrow_or_temporary"
    return ""


def review_prompt(items: list[dict[str, Any]]) -> str:
    return """You are a conservative second-stage reviewer for durable USER memory. Return JSON only:
{"items":[{"proposal_id":"...","decision":"approve|reject|clarify","novelty":"new|duplicate|too_narrow|volatile|unsupported|misrouted","utility":"high|medium|low","reason":"brief Chinese"}]}.
Approve only when ALL are true: evidence explicitly supports the fact; stable and low-risk; materially changes answers across multiple future conversations OR is a currently validated stable learning weakness/communication hard preference; not a one-off question/task; correctly routed; materially new versus duplicate contents. Historical learning questions are temporal observations, not proof of current ability: reject approval when requires_current_validation=true unless current_validation_status=confirmed_current. A past wrong answer or request for help must not become a permanent current weakness. Reject project implementation details, one website/source rule, one exam paper symbol, one game state, one-off task formats, vague self-description, generic quality requirements, narrow situations, weak inference, copied text, and facts useful only in their original conversation. Clarify sensitive/self-label/stale plans. Approval should be rare, normally below 10% of all input proposals. Prefer rejecting over increasing count. One decision per input proposal.
INPUT:\n""" + json.dumps(items, ensure_ascii=False)


def call_review(batch: list[dict[str, Any]], task: str, timeout: int) -> dict[str, dict[str, Any]]:
    from agent.auxiliary_client import call_llm
    response = call_llm(task=task, messages=[{"role": "user", "content": review_prompt(batch)}], temperature=0, max_tokens=5000, timeout=timeout)
    text = str(response.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I); text = re.sub(r"\s*```$", "", text)
    payload = json.loads(text[text.find("{") : text.rfind("}") + 1])
    return {str(item["proposal_id"]): item for item in payload.get("items") or []}


def admin_token() -> str:
    backend = Path(os.environ.get("MEMORY_GRAPH_WEBUI_BACKEND") or (Path.home() / "projects" / "memory-graph" / "backend"))
    python = os.environ.get("MEMORY_GRAPH_PYTHON") or "/usr/bin/python3"
    command = [python, "-c", "from auth import create_session_token; print(create_session_token('admin'))"]
    result = subprocess.run(command, cwd=backend, text=True, capture_output=True, timeout=30)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"Memory Graph token generation failed: {result.stderr[-500:]}")
    return result.stdout.strip()


def approve(proposal_id: str) -> dict[str, Any]:
    token = admin_token()
    req = request.Request(
        f"{API_BASE}/api/proposal-review/proposals/{proposal_id}/approve",
        data=json.dumps({"reason": "continuous AI Studio second-stage quality gate approved"}).encode(),
        headers={"Content-Type": "application/json", "Cookie": f"mg_session={token}"}, method="POST",
    )
    with request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        path.chmod(0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=QUEUE)
    parser.add_argument("--clarification", type=Path, default=CLARIFICATION)
    parser.add_argument("--proposal-id", default="")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--task", default="approval")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = load_jsonl(args.queue)
    demoted = sum(1 for row in rows if demote_unconsented_ready_memory(row))
    if demoted:
        atomic_jsonl(args.queue, rows)
    pending = [row for row in rows if row.get("status", "pending") == "pending" and (row.get("candidate") or {}).get("source") == "google_ai_studio_continuous"]
    if args.proposal_id:
        pending = [row for row in pending if row.get("proposal_id") == args.proposal_id]
    pending = pending[: args.limit]
    inputs = [candidate_payload(row) for row in pending]
    decisions: dict[str, dict[str, Any]] = {}
    blocked = {}
    reviewable = []
    for item in inputs:
        reason = deterministic_block(item)
        if reason:
            blocked[str(item["proposal_id"])] = reason
        else:
            reviewable.append(item)
    batches = [reviewable[i : i + args.batch_size] for i in range(0, len(reviewable), args.batch_size)]
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.concurrency, len(batches) or 1))) as pool:
        futures = {pool.submit(call_review, batch, args.task, args.timeout): batch for batch in batches}
        for future in as_completed(futures):
            try:
                decisions.update(future.result())
            except Exception as exc:
                errors.append({"proposal_ids": [item["proposal_id"] for item in futures[future]], "error": repr(exc)})

    applied = {"approved": [], "rejected": [], "clarified": [], "failed": []}
    if args.apply and not errors:
        by_id = {str(row.get("proposal_id") or ""): row for row in rows}
        clarification_rows = load_jsonl(args.clarification)
        clarification_by_id = {str(row.get("id") or ""): row for row in clarification_rows}
        for proposal_id in blocked:
            row = by_id[proposal_id]; row["status"] = "rejected"; row["updated_at"] = now()
            row["review"] = {"status": "rejected", "reason": blocked[proposal_id], "reviewed_at": now()}
            applied["rejected"].append(proposal_id)
        approval_ids = []
        for proposal_id, decision in decisions.items():
            row = by_id.get(proposal_id)
            if not row or row.get("status", "pending") != "pending":
                continue
            action = str(decision.get("decision") or "reject")
            utility = str(decision.get("utility") or "low")
            novelty = str(decision.get("novelty") or "unsupported")
            if action == "approve" and utility == "high" and novelty == "new":
                candidate = row.get("candidate") or {}
                candidate["suggested_store"] = "memory_graph"; candidate.setdefault("metadata", {})["target_store"] = "memory_graph"
                row["candidate"] = candidate; row.setdefault("decision", {})["target_store"] = "memory_graph"
                approval_ids.append(proposal_id)
            else:
                status = "clarified" if action == "clarify" else "rejected"
                row["status"] = "rejected"; row["updated_at"] = now()
                row["review"] = {"status": status, "reason": str(decision.get("reason") or novelty), "reviewed_at": now()}
                if action == "clarify":
                    candidate = row.get("candidate") or {}; metadata = candidate.get("metadata") or {}
                    clarification_id = "mc_ai_review_" + proposal_id.removeprefix("rp_ai_cont_")
                    clarification_by_id.setdefault(clarification_id, {
                        "id": clarification_id, "status": "pending", "created_at": now(),
                        "namespace": candidate.get("namespace_security_scope"),
                        "source_type": "google_ai_studio_continuous_review",
                        "source_candidate_id": candidate.get("candidate_id"),
                        "source_turn_id": metadata.get("source_turn_id"),
                        "category": candidate.get("kind"), "risk_level": candidate.get("risk_level", "medium"),
                        "proposed_fact": candidate.get("content"), "evidence_quote": candidate.get("evidence_quote"),
                        "question": "这条历史表述是否仍然准确，并适合作为长期记忆？",
                        "reason": str(decision.get("reason") or novelty),
                    })
                applied["clarified" if action == "clarify" else "rejected"].append(proposal_id)
        atomic_jsonl(args.queue, rows)
        atomic_jsonl(args.clarification, list(clarification_by_id.values()))
        # From this point the API owns queue mutation. Never rewrite the stale
        # in-memory rows after an approval response.
        for proposal_id in approval_ids:
            try:
                result = approve(proposal_id); verification = result.get("verification") or {}
                if result.get("ok") is not True or verification.get("read_ok") is not True or verification.get("search_ok") is not True:
                    raise RuntimeError(f"approval verification failed: {result}")
                applied["approved"].append(proposal_id)
            except Exception as exc:
                applied["failed"].append({"proposal_id": proposal_id, "error": repr(exc)})
                break

    report = {
        "generated_at": now(), "apply": args.apply, "pending_reviewed": len(pending),
        "demoted_unconsented_ready_memory": demoted,
        "deterministic_rejects": blocked, "model_decisions": decisions, "errors": errors,
        "decision_counts": {
            action: sum(1 for decision in decisions.values() if decision.get("decision") == action)
            for action in ("approve", "reject", "clarify")
        },
        "applied": applied,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    output = REPORTS / f"continuous-second-review-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"); output.chmod(0o600)
    print(json.dumps({"report": str(output), "pending_reviewed": len(pending), "demoted_unconsented_ready_memory": demoted, "decision_counts": report["decision_counts"], "deterministic_rejects": len(blocked), "errors": len(errors), "applied": applied}, ensure_ascii=False))
    return 0 if not errors and not applied["failed"] else 1


def main() -> int:
    with exclusive_lock(LOCK):
        return run_main()


if __name__ == "__main__":
    raise SystemExit(main())
