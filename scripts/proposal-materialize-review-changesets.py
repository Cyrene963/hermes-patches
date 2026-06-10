#!/usr/bin/env python3
"""Materialize private distillation suggestions into reviewable Memory Graph changesets.

The script is deliberately conservative:
- reads local private suggestion files only;
- writes 0600 local changeset JSONL with proposed memory content;
- writes a redacted report with IDs, hashes, and validation status only;
- never writes Memory Graph and never mutates the review proposal queue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROFILE_DIR = Path(os.environ.get("HERMES_PROFILE_DIR") or (Path.home() / ".hermes"))
BASE = Path(os.environ.get("DIGITAL_BRAIN_99_TASK_DIR") or (PROFILE_DIR / "tasks" / "digital-brain-99"))
SUGGESTION_DIR = BASE / "distillation_suggestions"
CHANGESET_DIR = BASE / "review_changesets"
REPORT_DIR = BASE / "reports"


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _sha(value: Any, n: int = 16) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:n]


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _latest_suggestions(path: Path) -> list[Path]:
    if not path.exists():
        return []
    latest: dict[str, Path] = {}
    for item in sorted(path.glob("*.distilled.json"), key=lambda p: p.stat().st_mtime):
        obj = _load_json(item)
        if not obj:
            continue
        key = str(obj.get("proposal_id") or item.stem)
        latest[key] = item
    return list(latest.values())


def _slug(text: str, fallback: str) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return fallback
    # Keep URI segment short and filesystem/URL friendly while preserving unicode text.
    text = re.sub(r"[\\/#?%*:|\"<>]+", " ", text).strip()
    text = re.sub(r"\s+", "-", text)[:56].strip("-")
    return text or fallback


def _target_uri(suggestion: dict[str, Any]) -> str:
    kind = str(suggestion.get("candidate_kind") or "memory").strip() or "memory"
    draft = str(suggestion.get("suggested_memory_draft") or "")
    suffix = _slug(draft, str(suggestion.get("proposal_id") or _sha(suggestion))[-8:])
    if kind == "user_self_model":
        return f"core://用户档案/待审核自我模型/{suffix}"
    if kind == "memory_system_insight":
        return f"core://项目/Hermes Memory OS 99% 数字替身长期目标/待审核系统洞察/{suffix}"
    return f"core://待审核记忆/{kind}/{suffix}"


def _validate(suggestion: dict[str, Any]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    draft = str(suggestion.get("suggested_memory_draft") or "").strip()
    namespace = str(suggestion.get("namespace_scope") or "").strip()
    if not draft:
        warnings.append("missing suggested_memory_draft")
    if len(draft) < 24:
        warnings.append("draft too short for durable memory")
    if len(draft) > 600:
        warnings.append("draft too long; needs tighter distillation")
    if not namespace:
        warnings.append("missing namespace_scope")
    if str(suggestion.get("approval_status")) != "needs_human_or_strong_model_review":
        warnings.append("unexpected approval_status")
    if str(suggestion.get("confidence")) == "low_to_medium_auto_distillation":
        warnings.append("auto-distilled; needs strong-model or human review before write")
    status = "blocked" if any(w.startswith("missing") or "too short" in w for w in warnings) else "review_ready"
    return status, warnings


def _changeset_from(suggestion: dict[str, Any], suggestion_path: Path) -> dict[str, Any]:
    proposal_id = str(suggestion.get("proposal_id") or suggestion_path.stem)
    content = str(suggestion.get("suggested_memory_draft") or "").strip()
    namespace = str(suggestion.get("namespace_scope") or "")
    target_uri = _target_uri(suggestion)
    after = {
        "kind": suggestion.get("candidate_kind") or "memory",
        "content": content,
        "target_path": target_uri,
        "namespace": namespace,
        "source": "private_distillation_suggestion",
        "source_private_raw_path": suggestion.get("source_private_raw_path") or "",
        "proposal_id": proposal_id,
    }
    status, warnings = _validate(suggestion)
    readback_queries = [str(q) for q in suggestion.get("readback_queries") or [] if str(q).strip()]
    if content and content not in readback_queries:
        readback_queries.insert(0, content[:160])
    changeset_id = "cs_distill_" + _sha({"proposal_id": proposal_id, "after": after})
    return {
        "changeset_id": changeset_id,
        "proposal_id": proposal_id,
        "operator": "proposal-distillation-materializer",
        "namespace": namespace,
        "operation_type": "propose_write",
        "target_path_uri": target_uri,
        "before_snapshot": {},
        "after_snapshot": after,
        "diff": json.dumps({"before": {}, "after": after}, ensure_ascii=False, sort_keys=True),
        "evidence_id": "ev_distill_" + _sha({"proposal_id": proposal_id, "source": suggestion.get("source_private_raw_path")}),
        "evidence_quote": "private raw material retained in source_private_raw_path; redacted from reports",
        "reason": "private raw proposal was distilled into a reviewable durable-memory candidate",
        "review_status": status,
        "rollback_method": "reject changeset before write; if written later, delete or supersede target_path_uri by changeset_id",
        "readback": {"queries": readback_queries, "ok": False, "top_uri": "", "top_score": None, "reason": "not written yet"},
        "risk_level": suggestion.get("risk_level") or "medium",
        "approval_status": "needs_human_or_strong_model_review",
        "warnings": warnings,
        "source_suggestion_path": str(suggestion_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suggestion-dir", default=str(SUGGESTION_DIR))
    parser.add_argument("--changeset-dir", default=str(CHANGESET_DIR))
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    args = parser.parse_args()

    suggestion_dir = Path(args.suggestion_dir)
    changeset_dir = Path(args.changeset_dir)
    report_dir = Path(args.report_dir)
    changeset_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _chmod(changeset_dir, 0o700)

    changesets: list[dict[str, Any]] = []
    report_items: list[dict[str, Any]] = []
    for suggestion_path in _latest_suggestions(suggestion_dir):
        suggestion = _load_json(suggestion_path)
        if not suggestion:
            continue
        cs = _changeset_from(suggestion, suggestion_path)
        changesets.append(cs)
        report_items.append(
            {
                "changeset_id": cs["changeset_id"],
                "proposal_id_suffix": str(cs.get("proposal_id"))[-8:],
                "namespace_hash": _sha(cs.get("namespace") or ""),
                "target_uri_hash": _sha(cs.get("target_path_uri") or ""),
                "content_hash": _sha((cs.get("after_snapshot") or {}).get("content") or ""),
                "content_chars": len(str((cs.get("after_snapshot") or {}).get("content") or "")),
                "candidate_kind": (cs.get("after_snapshot") or {}).get("kind"),
                "review_status": cs.get("review_status"),
                "risk_level": cs.get("risk_level"),
                "warning_count": len(cs.get("warnings") or []),
            }
        )

    stamp = time.strftime("%Y%m%d_%H%M%S")
    changeset_path = changeset_dir / f"review-changesets-{stamp}.jsonl"
    with changeset_path.open("w", encoding="utf-8") as handle:
        for cs in changesets:
            handle.write(json.dumps(cs, ensure_ascii=False, sort_keys=True) + "\n")
    _chmod(changeset_path, 0o600)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suggestion_dir": str(suggestion_dir),
        "changeset_file": str(changeset_path),
        "count": len(changesets),
        "review_ready": sum(1 for cs in changesets if cs.get("review_status") == "review_ready"),
        "blocked": sum(1 for cs in changesets if cs.get("review_status") == "blocked"),
        "items": report_items,
        "privacy_note": "Report redacts content/namespace/target URI. Private changeset JSONL is 0600 and contains proposed memory text.",
    }
    report_path = report_dir / f"proposal-review-changesets-{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(report_path)
    print(changeset_path)
    print(f"changesets {len(changesets)} review_ready {report['review_ready']} blocked {report['blocked']}")
    return 0 if report["blocked"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
