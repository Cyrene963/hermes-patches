#!/usr/bin/env python3
"""E2E canary: ReviewProposal approve -> Memory Graph -> gateway recall -> cleanup.

This proves the full digital-brain loop reaches future task execution:
1. append a temporary distilled review proposal;
2. approve it through the live WebUI API;
3. verify Memory Graph read/search;
4. ask `/v1/chat/completions` a memory-only question from three fresh sessions;
5. delete the temporary memory and verify cleanup.
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

import yaml

ROOT = pathlib.Path.home()
REPO = ROOT / ".hermes" / "hermes-agent"
RUNTIME_PYTHON = REPO / "venv" / "bin" / "python"
QUEUE = ROOT / ".hermes" / "logs" / "memory_review_queue" / "review_proposals.current.jsonl"
OUT_DIR = ROOT / ".hermes" / "tasks" / "digital-brain-99-baselines"
API_BASE = "http://127.0.0.1:8233"
GATEWAY_URL = "http://127.0.0.1:8642/v1/chat/completions"


def _ensure_runtime_python() -> None:
    """Run under Hermes' runtime venv even when cron PATH points elsewhere."""
    if os.environ.get("MEMORY_OS_E2E_RUNTIME_REEXEC") == "1":
        return
    if not RUNTIME_PYTHON.exists():
        return
    if pathlib.Path(sys.executable).resolve() == RUNTIME_PYTHON.resolve():
        return
    env = os.environ.copy()
    env["MEMORY_OS_E2E_RUNTIME_REEXEC"] = "1"
    os.execve(str(RUNTIME_PYTHON), [str(RUNTIME_PYTHON), str(pathlib.Path(__file__).resolve()), *sys.argv[1:]], env)


_ensure_runtime_python()


def _default_namespace() -> str:
    """Use the same namespace the API gateway assigns for this host by default.

    A cross-namespace default makes the canary fail when isolation is working,
    which is the opposite of what this end-to-end recall check is meant to test.
    """
    try:
        cfg = yaml.safe_load((ROOT / ".hermes" / "config.yaml").read_text(encoding="utf-8")) or {}
        user_id = str(cfg.get("default_terminal_user") or "").strip()
        if user_id:
            return f"telegram:{user_id}"
    except Exception:
        pass
    raise RuntimeError(
        "Cannot determine E2E namespace; set MEMORY_OS_E2E_NAMESPACE or "
        "configure default_terminal_user"
    )


NAMESPACE = os.environ.get("MEMORY_OS_E2E_NAMESPACE") or _default_namespace()
SESSION_KEY = os.environ.get("MEMORY_OS_E2E_SESSION_KEY") or f"agent:api_server:{NAMESPACE}:dm:memory-os-e2e"


def _run(cmd: list[str], *, cwd: str | None = None, timeout: int = 180) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True, timeout=timeout).strip()


def _api_server_key() -> str:
    try:
        cfg = yaml.safe_load((ROOT / ".hermes" / "config.yaml").read_text(encoding="utf-8")) or {}
        return str((((cfg.get("platforms") or {}).get("api_server") or {}).get("extra") or {}).get("key") or "").strip()
    except Exception:
        return ""


def _admin_token() -> str:
    backend = os.environ.get("MG_BACKEND_DIR", str(ROOT / "projects" / "memory-graph" / "backend"))
    return _run([sys.executable, "-c", "from auth import create_session_token; print(create_session_token('admin'))"], cwd=backend)


def _append_canary() -> dict[str, str]:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    backup = QUEUE.with_suffix(QUEUE.suffix + f".bak_gateway_e2e_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(QUEUE, backup)
    marker = f"memory-os-gateway-recall-e2e-{int(time.time())}"
    code = "GW-ANCHOR-" + hashlib.sha256(marker.encode()).hexdigest()[:5].upper()
    proposal_id = "rp_gateway_" + hashlib.sha256((marker + code).encode()).hexdigest()[:16]
    target_uri = f"core://Memory OS Gateway Recall E2E Canary {marker}"
    content = f"Temporary verified Memory Graph anchor. The Veylix gateway recall probe code is {code}. Delete after verification."
    row = {
        "proposal_id": proposal_id,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "candidate": {
            "kind": "target_function",
            "distilled": True,
            "content": content,
            "evidence_quote": f"Temporary gateway recall canary evidence {marker}",
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
            "readback_queries": [code],
            "reason": "temporary canary for approval/readback/gateway recall E2E; delete after verification",
            "source": "memory_os_gateway_recall_e2e_canary",
            "metadata": {"target_store": "memory_graph", "distilled": True},
        },
        "decision": {"action": "review", "target_store": "memory_graph", "requires_review": True, "risk_level": "low", "reason": "temporary gateway recall canary"},
        "changeset": {
            "changeset_id": "cs_gateway_" + hashlib.sha256((marker + "cs").encode()).hexdigest()[:16],
            "operator": "memory-os-gateway-recall-e2e-canary",
            "namespace": NAMESPACE,
            "operation_type": "propose_write",
            "target_path_uri": target_uri,
            "before_snapshot": {},
            "after_snapshot": {"content": content, "namespace": NAMESPACE, "target_path": target_uri},
            "review_status": "pending",
            "rollback_method": "delete approved canary node by returned uri",
        },
        "readback": {"queries": [code], "ok": False, "top_uri": "", "top_score": None, "reason": "not written yet"},
    }
    with QUEUE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"proposal_id": proposal_id, "marker": marker, "code": code, "target_uri": target_uri, "backup": str(backup)}


def _approve(proposal_id: str) -> dict:
    token = _admin_token()
    req = request.Request(
        f"{API_BASE}/api/proposal-review/proposals/{proposal_id}/approve",
        data=json.dumps({"reason": "E2E approval/readback/gateway-recall canary verified"}).encode(),
        headers={"Content-Type": "application/json", "Cookie": f"mg_session={token}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode())
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"approve HTTP {exc.code}: {body[:2000]}") from exc


def _gateway_chat(prompt: str, expected_code: str, session_id: str, namespace: str) -> dict:
    payload = {
        "model": "hermes-agent",
        "messages": [
            {"role": "system", "content": f"Use only memory for namespace {namespace}. Return one exact GW-ANCHOR-* token or UNKNOWN."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "stream": False,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Hermes-Session-Key": SESSION_KEY,
        "X-Hermes-Session-Id": session_id,
    }
    key = _api_server_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = request.Request(GATEWAY_URL, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=240) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            return {"ok": content == expected_code, "status": response.status, "content": content}
    except Exception as exc:
        body = ""
        if hasattr(exc, "read"):
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
        return {"ok": False, "error": repr(exc), "error_body": body[:2000]}


def _memory_tool_eval(code: str) -> str:
    return _run([str(REPO / "venv/bin/python"), "-c", code], cwd=str(REPO), timeout=120)


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


def _remove_pending_canaries() -> list[str]:
    removed: list[str] = []
    if not QUEUE.exists():
        return removed
    rows: list[str] = []
    for line in QUEUE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            rows.append(line)
            continue
        pid = str(payload.get("proposal_id") or "")
        if pid.startswith("rp_gateway_") and str(payload.get("status", "pending")) == "pending":
            removed.append(pid)
        else:
            rows.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if removed:
        QUEUE.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return removed


def main() -> int:
    canary = _append_canary()
    approved = None
    probes = []
    cleanup = None
    status = "fail"
    exact_hits = 0
    try:
        approved = _approve(canary["proposal_id"])
        verification = approved.get("verification") or {}
        if approved.get("ok") is not True or verification.get("read_ok") is not True or verification.get("search_ok") is not True:
            raise AssertionError(f"approval/readback failed: {approved}")
        gateway_prompt = (
            'A temporary Memory Graph Anchor contains the Veylix gateway recall probe code. '
            'Return only the exact GW-ANCHOR-* code visible in recalled memory context. '
            'If no such code is visible, answer UNKNOWN.'
        )
        for suffix in ('a', 'b', 'c'):
            probe = _gateway_chat(gateway_prompt, canary["code"], f"api-approved-gateway-recall-{int(time.time())}{suffix}", NAMESPACE)
            probes.append(probe)
        exact_hits = sum(1 for p in probes if p.get("ok") is True)
        if exact_hits < 2:
            raise AssertionError(f"gateway recall unstable: {probes}")
        cleanup = _cleanup(approved["uri"])
        if not (cleanup.get("after") or {}).get("error"):
            raise AssertionError(f"cleanup failed: {cleanup}")
        status = "pass"
        return 0
    finally:
        if approved and not cleanup:
            cleanup = _cleanup(approved.get("uri") or canary["target_uri"])
        removed = _remove_pending_canaries()
        report = {
            "status": status,
            "canary": canary,
            "approval": approved,
            "gateway": {"probes": probes, "exact_hits": sum(1 for p in probes if p.get("ok") is True)},
            "cleanup": cleanup,
            "removed_pending_canaries": removed,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"proposal-gateway-recall-e2e-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(out))
        print(json.dumps({
            "status": status,
            "proposal_id": canary["proposal_id"],
            "uri": (approved or {}).get("uri"),
            "gateway_ok": exact_hits >= 2 if probes else False,
            "gateway_content": [p.get("content") for p in probes],
            "cleanup_after_error": bool((cleanup or {}).get("after", {}).get("error")),
        }, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
