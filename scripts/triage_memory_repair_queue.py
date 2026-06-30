#!/usr/bin/env python3
"""Triage MemoryWritePipeline repair queue.

Do not blindly write old failed candidates. Classify stale repair rows into:
- ignored_noise: wrappers, tests, low-info generated fragments
- migrated_to_clarification: plausible user/private memory candidates surfaced on use
- kept_pending: rows not understood or not safe to mutate
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

REPAIR_PATH = Path.home() / ".hermes" / "logs" / "memory_repair_queue.jsonl"
CLARIFY_PATH = Path.home() / ".hermes" / "logs" / "memory_clarification_queue.jsonl"
BACKUP_DIR = Path.home() / ".hermes" / "logs" / "memory_repair_queue_backups"

NOISE_PATTERNS = [
    r"\[IMPORTANT: You are running as a scheduled cron job",
    r"\[IMPORTANT: The user has invoked",
    r"The full skill content is loaded below",
    r"<available_skills>",
    r"metadata:\s*hermes:",
    r"^\[SILENT\]$",
    r"^\{\s*\"(?:status|error|id)\"",
]
TEST_NAMESPACES = {"telegram:u1", "test", "telegram:test-user"}
SYNTHETIC_TEST_VALUE_HASHES = {
    # Neutral fixture from memory_write_pipeline tests; empty namespace is expected
    # to be rejected and should not keep production repair gates degraded.
    "852039388a32dc8c22759514b3e8227b14e13a9fc91b27737a232efeff99335f",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(text: str, limit: int = 700) -> str:
    return " ".join(str(text or "").split())[:limit]


def is_noise(row: dict) -> str:
    text = "\n".join(str(row.get(k, "")) for k in ["content_preview", "evidence_preview", "subject", "predicate", "target_path"])
    namespace = str(row.get("namespace") or "")
    if namespace in TEST_NAMESPACES:
        return "test_namespace"
    if not namespace and str(row.get("value_sha256") or "") in SYNTHETIC_TEST_VALUE_HASHES:
        return "synthetic_test_fixture_empty_namespace"
    if namespace.startswith("telegram:-") and row.get("subject") == "auto_store_heuristic":
        return "group_auto_store_heuristic_not_private_memory"
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, text, re.I | re.S):
            return "wrapper_or_runtime_noise"
    if len(norm(row.get("content_preview", ""))) < 12:
        return "low_information"
    return ""


def clarification_id(row: dict) -> str:
    raw = "|".join(str(row.get(k, "")) for k in ["namespace", "subject", "predicate", "target_path", "value_sha256"])
    return "mc_repair_" + hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:18]


def risk(row: dict) -> str:
    text = "\n".join(str(row.get(k, "")) for k in ["subject", "predicate", "memory_type", "target_path", "content_preview", "evidence_preview"])
    if re.search(r"(credential|secret|token|api[_ -]?key|凭据|密钥|密码)", text, re.I):
        return "sensitive"
    if not row.get("namespace") or row.get("namespace") == "core":
        return "cross_namespace"
    if row.get("memory_type") == "project_fact":
        return "project_fact"
    if float(row.get("confidence") or 0.0) < 0.85:
        return "low_confidence"
    return "repair_backlog"


def load_jsonl(path: Path) -> list[dict]:
    rows=[]
    if not path.exists(): return rows
    for line in path.open(encoding="utf-8"):
        try: rows.append(json.loads(line))
        except Exception: rows.append({"_parse_error_line": line.rstrip("\n")})
    return rows


def append_clarifications(items: list[dict]) -> int:
    CLARIFY_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing=set()
    if CLARIFY_PATH.exists():
        for line in CLARIFY_PATH.open(encoding="utf-8"):
            try: existing.add(json.loads(line).get("id"))
            except Exception: pass
    written=0
    with CLARIFY_PATH.open("a", encoding="utf-8") as handle:
        for item in items:
            if item["id"] in existing: continue
            handle.write(json.dumps(item, ensure_ascii=False)+"\n")
            existing.add(item["id"]); written += 1
    return written


def main() -> int:
    if not REPAIR_PATH.exists():
        print(json.dumps({"status":"missing_repair_queue","path":str(REPAIR_PATH)}))
        return 0
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup=BACKUP_DIR / f"memory_repair_queue.before_triage.{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    shutil.copy2(REPAIR_PATH, backup)
    rows=load_jsonl(REPAIR_PATH)
    out=[]; clarifications=[]; counts={"ignored_noise":0,"migrated_to_clarification":0,"kept_pending":0,"parse_error":0}
    ts=now()
    for row in rows:
        if row.get("_parse_error_line"):
            out.append(row["_parse_error_line"]); counts["parse_error"] += 1; continue
        status=str(row.get("status","pending") or "pending")
        if status != "pending":
            out.append(json.dumps(row, ensure_ascii=False)); counts["kept_pending"] += 1; continue
        noise=is_noise(row)
        if noise:
            row["status"]="ignored_noise"
            row["triaged_at"]=ts
            row["triage_reason"]=noise
            counts["ignored_noise"] += 1
        else:
            cid=clarification_id(row)
            item={
                "schema_version":1,
                "id":cid,
                "status":"pending",
                "namespace":row.get("namespace") or "",
                "subject":row.get("subject") or "repair_candidate",
                "predicate":row.get("predicate") or "needs_confirmation",
                "memory_type":row.get("memory_type") or "unknown",
                "target_path":row.get("target_path") or "",
                "reason":"migrated from memory repair queue; confirm when relevant",
                "risk":risk(row),
                "content_preview":norm(row.get("content_preview") or ""),
                "evidence_preview":norm(row.get("evidence_preview") or ""),
                "source_type":row.get("source_type") or "repair_queue",
                "confidence":float(row.get("confidence") or 0.0),
                "importance":float(row.get("importance") or 0.0),
                "created_at":ts,
                "last_surfaced_at":"",
                "surface_count":0,
                "source_repair_value_sha256":row.get("value_sha256") or "",
                "value_sha256":row.get("value_sha256") or hashlib.sha256(norm(row.get("content_preview","")).encode()).hexdigest(),
            }
            clarifications.append(item)
            row["status"]="migrated_to_clarification"
            row["triaged_at"]=ts
            row["clarification_id"]=cid
            counts["migrated_to_clarification"] += 1
        out.append(json.dumps(row, ensure_ascii=False))
    written=append_clarifications(clarifications)
    REPAIR_PATH.write_text("\n".join(out)+"\n", encoding="utf-8")
    counts["clarification_written"]=written
    counts["backup"]=str(backup)
    print(json.dumps({"status":"ok", **counts}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
