#!/usr/bin/env python3
"""E2E canary for Memory OS ReviewProposal approve -> Memory Graph readback -> cleanup.

Creates a temporary distilled ReviewProposal in the supervised queue, approves it
through the live Memory Graph WebUI API, verifies readback/search succeeded, then
removes the temporary node. Fails closed if the canary remains readable.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib import error, request

QUEUE = pathlib.Path.home() / ".hermes" / "logs" / "memory_review_queue" / "review_proposals.current.jsonl"
EVIDENCE_DIR = pathlib.Path.home() / ".hermes" / "tasks" / "digital-brain-99-baselines"
API_BASE = "http://127.0.0.1:8233"
NAMESPACE = os.environ.get("MEMORY_OS_E2E_NAMESPACE", "telegram:test-user")


def _run(cmd: list[str], *, cwd: str | None = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def _admin_token() -> str:
    return _run([sys.executable, "-c", "from auth import create_session_token; print(create_session_token('admin'))"], cwd=os.environ.get("MG_BACKEND_DIR", str(pathlib.Path.home() / "projects" / "memory-graph" / "backend")))


def _append_canary() -> dict:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    backup = QUEUE.with_suffix(QUEUE.suffix + f".bak_e2e_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(QUEUE, backup)
    marker = f"memory-os-approval-e2e-canary-{int(time.time())}"
    proposal_id = "rp_canary_" + hashlib.sha256(marker.encode()).hexdigest()[:16]
    target_uri = f"core://Memory OS Approval E2E Canary {marker}"
    content = f"Temporary verified Memory OS approval E2E canary {marker}. This row exists only to test approve, readback, changeset, and cleanup."
    row = {
        "proposal_id": proposal_id,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "candidate": {
            "kind": "target_function",
            "distilled": True,
            "content": content,
            "evidence_quote": f"Temporary canary evidence {marker}",
            "confidence": 0.99,
            "importance": 1,
            "priority": 1,
            "durability": "temporary_canary",
            "requires_review": True,
            "risk_level": "low",
            "scope": "private",
            "suggested_store": "memory_graph",
            "namespace_security_scope": NAMESPACE,
            "target_path": target_uri,
            "readback_queries": [marker],
            "reason": "temporary canary for approval/readback E2E; delete after verification",
            "source": "memory_os_e2e_canary",
            "metadata": {"target_store": "memory_graph", "distilled": True},
        },
        "decision": {"action": "review", "target_store": "memory_graph", "requires_review": True, "risk_level": "low", "reason": "temporary canary"},
        "changeset": {
            "changeset_id": "cs_canary_" + hashlib.sha256((marker + "cs").encode()).hexdigest()[:16],
            "operator": "memory-os-e2e-canary",
            "namespace": NAMESPACE,
            "operation_type": "propose_write",
            "target_path_uri": target_uri,
            "before_snapshot": {},
            "after_snapshot": {"content": content, "namespace": NAMESPACE, "target_path": target_uri},
            "review_status": "pending",
            "rollback_method": "delete approved canary node by returned uri",
        },
        "readback": {"queries": [marker], "ok": False, "top_uri": "", "top_score": None, "reason": "not written yet"},
    }
    with QUEUE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"proposal_id": proposal_id, "marker": marker, "target_uri": target_uri, "backup": str(backup)}


def _approve(proposal_id: str) -> dict:
    token = _admin_token()
    req = request.Request(
        f"{API_BASE}/api/proposal-review/proposals/{proposal_id}/approve",
        data=json.dumps({"reason": "E2E approval/readback canary verified"}).encode(),
        headers={"Content-Type": "application/json", "Cookie": f"mg_session={token}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode())
    except error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')
        raise RuntimeError(f"approve HTTP {exc.code}: {body[:2000]}") from exc


def _memory_tool_eval(code: str) -> str:
    return _run([sys.executable, "-c", code], cwd=os.environ.get("HERMES_AGENT_DIR", str(pathlib.Path.home() / ".hermes" / "hermes-agent")))


def _cleanup(uri: str) -> dict:
    code = f"""
import json
from tools import memory_graph_tool
uri={uri!r}
namespace={NAMESPACE!r}
before=memory_graph_tool._read({{'uri': uri, 'namespace': namespace}})
delete=memory_graph_tool._delete({{'uri': uri, 'namespace': namespace}}) if 'not found' not in before.lower() else '{{"already_absent": true}}'
after=memory_graph_tool._read({{'uri': uri, 'namespace': namespace}})
print(json.dumps({{'before_found': 'error' not in before.lower(), 'delete': json.loads(delete), 'after': json.loads(after)}}, ensure_ascii=False))
"""
    return json.loads(_memory_tool_eval(code))


def main() -> int:
    canary = _append_canary()
    approved = None
    cleanup = None
    status = "fail"
    try:
        approved = _approve(canary["proposal_id"])
        verification = approved.get("verification") or {}
        if approved.get("ok") is not True or verification.get("read_ok") is not True or verification.get("search_ok") is not True:
            raise AssertionError(f"approval/readback failed: {approved}")
        cleanup = _cleanup(approved["uri"])
        if not cleanup.get("after", {}).get("error"):
            raise AssertionError(f"cleanup failed: {cleanup}")
        status = "pass"
        return 0
    finally:
        if approved and not cleanup:
            cleanup = _cleanup(approved.get("uri") or canary["target_uri"])
        report = {"status": status, "canary": canary, "approval": approved, "cleanup": cleanup, "created_at": datetime.now(timezone.utc).isoformat()}
        out = EVIDENCE_DIR / f"proposal-approve-e2e-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(out))
        print(json.dumps({"status": status, "proposal_id": canary["proposal_id"], "uri": (approved or {}).get("uri"), "cleanup_after_error": bool((cleanup or {}).get("after", {}).get("error"))}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
