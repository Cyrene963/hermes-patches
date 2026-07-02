#!/usr/bin/env python3
"""Digital-brain / Memory Graph 99% baseline runner.

Quiet enough for cron, explicit enough for repair work. It checks live services,
WebUI auth boundaries, review backlog, Memory Graph canary readback, and known
stop-the-line defects without mutating private user data.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(os.environ.get("HERMES_PROFILE_DIR", os.environ.get("HERMES_HOME", str(pathlib.Path.home() / ".hermes"))))
OUT_ROOT = ROOT / "tasks" / "digital-brain-99-baselines"
OUT_ROOT.mkdir(parents=True, exist_ok=True)
STAMP = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
OUT = OUT_ROOT / f"baseline-{STAMP}.json"


def sh(cmd: str, timeout: int = 20) -> dict:
    p = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout)
    return {"cmd": cmd, "returncode": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}


def http(url: str, cookie: str | None = None, method: str = "GET", data: bytes | None = None) -> dict:
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=headers, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
            parsed = None
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = None
            return {"status": r.status, "ok": 200 <= r.status < 300, "body": body[:2000], "json": parsed}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return {"status": e.code, "ok": False, "body": body[:2000], "json": None}
    except Exception as e:
        return {"status": 0, "ok": False, "body": repr(e), "json": None}


def session_token(username: str) -> str | None:
    backend = pathlib.Path(os.environ.get("MG_BACKEND_DIR", str(pathlib.Path.home() / "projects" / "memory-graph" / "backend")))
    cmd = f"cd {backend} && python3 - <<'PY'\nfrom auth import create_session_token\nprint(create_session_token({username!r}))\nPY"
    r = sh(cmd)
    return r["stdout"].splitlines()[-1].strip() if r["returncode"] == 0 and r["stdout"].strip() else None


def review_queue_stats() -> dict:
    path = ROOT / "logs" / "memory_review_queue" / "review_proposals.current.jsonl"
    stats = {
        "exists": path.exists(),
        "total": 0,
        "by_status": {},
        "by_namespace": {},
        "by_target_store": {},
        "by_stage": {},
        "readback_empty_pending": 0,
        "safe_pending_raw_material": 0,
        "errors": [],
    }
    if not path.exists():
        return stats
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception as e:
            stats["errors"].append({"line": i, "error": str(e)})
            continue
        stats["total"] += 1
        c = o.get("candidate") or {}
        m = c.get("metadata") or {}
        decision = o.get("decision") or {}
        changeset = o.get("changeset") or {}
        status = str(o.get("status", "pending") or "pending")
        ns = str(o.get("namespace") or c.get("namespace") or c.get("namespace_security_scope") or changeset.get("namespace") or "")
        store = str(m.get("target_store") or c.get("suggested_store") or decision.get("target_store") or "")
        readback = o.get("readback") or {}
        queries = c.get("readback_queries") or readback.get("queries") or o.get("readback_queries") or []
        if status == "pending" and not queries:
            stats["readback_empty_pending"] += 1
        source = str(c.get("source_type") or c.get("source") or o.get("source") or "")
        content = str(c.get("content") or c.get("object_value") or c.get("value") or o.get("content") or "").strip()
        evidence = str(c.get("evidence_quote") or o.get("evidence_quote") or "").strip()
        explicitly_distilled = bool(c.get("distilled") or m.get("distilled"))
        has_distinct_evidence = bool(content and evidence and content != evidence)
        has_readback = bool(queries)
        if store == "memory_graph" and explicitly_distilled and has_readback:
            stage = "ready_memory"
        elif store == "memory_graph" and has_distinct_evidence and has_readback and source not in {"state_db_message", "google_ai_studio"}:
            stage = "ready_memory"
        else:
            stage = "raw_material"
        if status == "pending" and store == "memory_graph" and stage == "raw_material" and has_readback:
            stats["safe_pending_raw_material"] += 1
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
        stats["by_namespace"][ns] = stats["by_namespace"].get(ns, 0) + 1
        stats["by_target_store"][store] = stats["by_target_store"].get(store, 0) + 1
        stats["by_stage"][stage] = stats["by_stage"].get(stage, 0) + 1
    return stats


def jsonl_status_stats(path: pathlib.Path) -> dict:
    stats = {"exists": path.exists(), "total": 0, "by_status": {}, "errors": []}
    if not path.exists():
        return stats
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as e:
            stats["errors"].append({"line": i, "error": str(e)})
            continue
        stats["total"] += 1
        status = str(row.get("status", "pending") or "pending")
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
    return stats


def hindsight_watchdog_summary() -> dict:
    cmd = f"{ROOT}/scripts/hindsight_backlog_watchdog.py"
    r = sh(cmd, timeout=90)
    summary = {"command": r, "status": "unknown"}
    if r["stdout"]:
        last = r["stdout"].splitlines()[-1]
        try:
            summary.update(json.loads(last))
        except Exception:
            pass
    return summary


def main() -> int:
    admin_token = session_token("admin")
    steven_token = session_token("steven")
    report = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "services": {
            "memory_graph_webui": sh("systemctl is-active memory-graph-webui.service"),
            "hermes_memory_graph_duplicate": sh("systemctl is-active hermes-memory-graph.service || true"),
            "hindsight": sh("systemctl is-active hindsight"),
            "postgres": sh("systemctl is-active postgresql@15-main"),
        },
        "health": {
            "webui_local": http("http://127.0.0.1:8233/health"),
            "embedded_mg": http("http://127.0.0.1:8900/health"),
            "hindsight": http("http://127.0.0.1:9177/health"),
            "public_mg": http(os.environ["MG_PUBLIC_HEALTH_URL"]) if os.environ.get("MG_PUBLIC_HEALTH_URL") else {"status": 0, "ok": True, "body": "skipped: MG_PUBLIC_HEALTH_URL unset", "json": None},
        },
        "review_queue": review_queue_stats(),
        "repair_queue": jsonl_status_stats(ROOT / "logs" / "memory_repair_queue.jsonl"),
        "clarification_queue": jsonl_status_stats(ROOT / "logs" / "memory_clarification_queue.jsonl"),
        "hindsight_backlog": hindsight_watchdog_summary(),
        "lifecycle_canary": sh(f"{ROOT}/scripts/memory_graph_lifecycle_canary.py", timeout=120),
        "webui_auth": {
            "unauth_proposals": http("http://127.0.0.1:8233/api/proposal-review/inbox"),
            "steven_review_groups": http("http://127.0.0.1:8233/api/review/groups", cookie=f"mg_session={steven_token}" if steven_token else None),
            "steven_proposals": http("http://127.0.0.1:8233/api/proposal-review/inbox?status=pending&limit=20", cookie=f"mg_session={steven_token}" if steven_token else None),
            "admin_proposals": http("http://127.0.0.1:8233/api/proposal-review/inbox?status=pending&limit=5", cookie=f"mg_session={admin_token}" if admin_token else None),
        },
        "tool_registration": sh(
            f"cd {ROOT / 'hermes-agent'} && venv/bin/python - <<'PY'\n"
            "import json\n"
            "from toolsets import TOOLSETS,_HERMES_CORE_TOOLS\n"
            "print(json.dumps({\n"
            "  'memory_graph_count': len(TOOLSETS.get('memory_graph',{}).get('tools',[])),\n"
            "  'memory_graph_search_core': 'memory_graph_search' in _HERMES_CORE_TOOLS,\n"
            "  'session_search_core': 'session_search' in _HERMES_CORE_TOOLS,\n"
            "  'deep_research_core': 'deep_research' in _HERMES_CORE_TOOLS,\n"
            "}))\n"
            "PY"
        ),
    }
    stop = []
    if report["services"]["memory_graph_webui"]["stdout"] != "active": stop.append("memory-graph-webui not active")
    if report["services"]["hindsight"]["stdout"] != "active": stop.append("hindsight not active")
    if report["services"]["postgres"]["stdout"] != "active": stop.append("postgres not active")
    dup_state = report["services"]["hermes_memory_graph_duplicate"].get("stdout", "")
    if dup_state not in {"inactive", "failed", ""}:
        stop.append(f"duplicate hermes-memory-graph not inactive: {dup_state}")
    if report["webui_auth"]["unauth_proposals"]["status"] != 401: stop.append("proposal inbox not 401 unauthenticated on local app path")
    if report["webui_auth"]["steven_review_groups"]["status"] != 403: stop.append("non-admin can access global review groups")
    pending_review = report["review_queue"].get("by_status", {}).get("pending", 0)
    safe_pending_raw_material = report["review_queue"].get("safe_pending_raw_material", 0)
    actionable_pending_review = max(0, pending_review - safe_pending_raw_material)
    if actionable_pending_review:
        stop.append(f"review queue still has actionable pending manual proposals: {actionable_pending_review}")
    if report["review_queue"].get("readback_empty_pending", 0): stop.append(f"pending review proposals missing readback queries: {report['review_queue']['readback_empty_pending']}")
    if report["review_queue"].get("errors"): stop.append("review queue JSON parse errors")
    pending_repair = report["repair_queue"].get("by_status", {}).get("pending", 0)
    if pending_repair: stop.append(f"repair queue still has pending failed writes: {pending_repair}")
    if report["repair_queue"].get("errors"): stop.append("repair queue JSON parse errors")
    if report["clarification_queue"].get("errors"): stop.append("clarification queue JSON parse errors")
    if report["hindsight_backlog"].get("status") != "pass": stop.append("hindsight backlog watchdog failing")
    if report["lifecycle_canary"].get("returncode") != 0: stop.append("memory graph lifecycle canary failing")
    report["stop_the_line"] = stop
    report["status"] = "pass" if not stop else "fail"
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(OUT))
    print(json.dumps({"status": report["status"], "stop_the_line": stop, "review_queue_total": report["review_queue"]["total"]}, ensure_ascii=False))
    return 0 if not stop else 2

if __name__ == "__main__":
    raise SystemExit(main())
