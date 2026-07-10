#!/usr/bin/env python3
"""Migrate stale ReviewProposal backlog into clarification-on-use queue.

This is intentionally not an approval/import script. Old backfill proposals are
raw evidence or uncertain candidates; the digital-brain path is to surface them
only when a future task would rely on them, then ask the user to confirm/correct.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

REVIEW_PATH = Path.home() / ".hermes" / "logs" / "memory_review_queue" / "review_proposals.current.jsonl"
CLARIFY_PATH = Path.home() / ".hermes" / "logs" / "memory_clarification_queue.jsonl"
BACKUP_DIR = Path.home() / ".hermes" / "logs" / "memory_review_queue" / "backups"

MIGRATABLE_REASONS = {
    "backfill candidate from local session evidence; requires human approval",
    "AI Studio/Gemini conversation candidate; requires supervised review before durable write",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str, limit: int = 700) -> str:
    return " ".join(str(text or "").split())[:limit]


def _proposal_id(payload: dict) -> str:
    return str(payload.get("proposal_id") or payload.get("id") or "")


def _candidate(payload: dict) -> dict:
    return payload.get("candidate") or {}


def _namespace(payload: dict) -> str:
    cand = _candidate(payload)
    return str(
        cand.get("namespace_security_scope")
        or payload.get("namespace")
        or (payload.get("changeset") or {}).get("namespace")
        or ""
    )


def _target_store(payload: dict) -> str:
    cand = _candidate(payload)
    meta = cand.get("metadata") or {}
    decision = payload.get("decision") or {}
    return str(meta.get("target_store") or cand.get("suggested_store") or decision.get("target_store") or "")


def _target_path(payload: dict) -> str:
    cand = _candidate(payload)
    return str(cand.get("target_path") or (payload.get("changeset") or {}).get("target_path_uri") or "")


def _reason(payload: dict) -> str:
    cand = _candidate(payload)
    decision = payload.get("decision") or {}
    return str(payload.get("reason") or cand.get("reason") or decision.get("reason") or "")


def _content(payload: dict) -> str:
    cand = _candidate(payload)
    return _norm(cand.get("content") or cand.get("value") or cand.get("object_value") or payload.get("content") or "")


def _evidence(payload: dict) -> str:
    cand = _candidate(payload)
    return _norm(payload.get("evidence_quote") or cand.get("evidence_quote") or payload.get("evidence") or "")


def _clarification_id(payload: dict) -> str:
    raw = "|".join([_proposal_id(payload), _namespace(payload), _target_path(payload), _content(payload)])
    return "mc_review_" + hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:18]


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"_parse_error_line": line.rstrip("\n")})
    return rows


def _append_clarifications(items: list[dict]) -> int:
    CLARIFY_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if CLARIFY_PATH.exists():
        with CLARIFY_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    existing.add(json.loads(line).get("id"))
                except Exception:
                    continue
    written = 0
    with CLARIFY_PATH.open("a", encoding="utf-8") as handle:
        for item in items:
            if item["id"] in existing:
                continue
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            existing.add(item["id"])
            written += 1
    return written


MIXED_EXTERNAL_MODEL_RE = re.compile(
    r"(?:\bModel\s+\d{1,2}:\d{2}\s*(?:AM|PM)?\b|Thoughts\s+Expand\s+to\s+view\s+model\s+thoughts|\bmodel\s+thoughts\b)",
    re.I,
)


def _is_role_pure_user_candidate(payload: dict) -> bool:
    cand = _candidate(payload)
    metadata = cand.get("metadata") or {}
    role = str(metadata.get("role") or cand.get("role") or "").strip().lower()
    source = str(cand.get("source_type") or cand.get("source") or "").strip().lower()
    text = "\n".join([_content(payload), _evidence(payload)])
    if source in {"google_ai_studio", "google_ai_studio_distilled"} and role != "user":
        return False
    return not MIXED_EXTERNAL_MODEL_RE.search(text)


def main() -> int:
    if not REVIEW_PATH.exists():
        print(json.dumps({"status": "missing_review_queue", "path": str(REVIEW_PATH)}))
        return 0
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"review_proposals.before_clarification_migration.{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    shutil.copy2(REVIEW_PATH, backup)

    rows = _load_jsonl(REVIEW_PATH)
    migrated_items = []
    updated = []
    migrated = skipped = 0
    now = _now()
    for row in rows:
        if row.get("_parse_error_line"):
            updated.append(row["_parse_error_line"])
            skipped += 1
            continue
        status = str(row.get("status", "pending") or "pending")
        reason = _reason(row)
        target_store = _target_store(row)
        if status == "pending" and target_store == "memory_graph" and reason in MIGRATABLE_REASONS and _is_role_pure_user_candidate(row):
            cand = _candidate(row)
            cid = _clarification_id(row)
            item = {
                "schema_version": 1,
                "id": cid,
                "status": "pending",
                "namespace": _namespace(row),
                "subject": cand.get("subject") or cand.get("kind") or cand.get("memory_type") or "review_proposal",
                "predicate": cand.get("predicate") or "needs_confirmation",
                "memory_type": cand.get("memory_type") or cand.get("kind") or "unknown",
                "target_path": _target_path(row),
                "reason": "migrated from old review backlog; confirm when relevant",
                "risk": "raw_material" if reason.startswith("backfill") else "external_import",
                "content_preview": _content(row) or "[no concise content preview]",
                "evidence_preview": _evidence(row),
                "source_type": cand.get("source_type") or cand.get("source") or "review_backlog",
                "confidence": float(cand.get("confidence") or row.get("confidence") or 0.0),
                "importance": float(cand.get("importance") or cand.get("priority") or row.get("importance") or 0.0),
                "created_at": now,
                "last_surfaced_at": "",
                "surface_count": 0,
                "source_proposal_id": _proposal_id(row),
                "value_sha256": hashlib.sha256((_content(row) or _evidence(row)).encode("utf-8", "ignore")).hexdigest(),
            }
            migrated_items.append(item)
            row["status"] = "migrated_to_clarification"
            row["updated_at"] = now
            row["review"] = dict(row.get("review") or {}, status="migrated_to_clarification", reviewed_at=now, reason="migrated to clarification-on-use queue, not approved")
            row["clarification_id"] = cid
            migrated += 1
        else:
            skipped += 1
        updated.append(json.dumps(row, ensure_ascii=False))

    written = _append_clarifications(migrated_items)
    REVIEW_PATH.write_text("\n".join(updated) + "\n", encoding="utf-8")
    print(json.dumps({"status":"ok","migrated":migrated,"clarification_written":written,"skipped":skipped,"backup":str(backup),"review_path":str(REVIEW_PATH),"clarification_path":str(CLARIFY_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
