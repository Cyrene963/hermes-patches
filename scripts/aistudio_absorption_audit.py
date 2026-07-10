#!/usr/bin/env python3
"""Generate an auditable AI Studio memory absorption report.

This report deliberately separates archive integrity, retrieval quality, and durable
memory distillation. It never equates indexed turns with understood memories.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time

PROFILE = Path.home() / ".hermes"
BASE = PROFILE / "memories" / "aistudio_gemini"
TURN_DB = BASE / "aistudio_turns.sqlite3"
REVIEW = PROFILE / "logs" / "memory_review_queue" / "review_proposals.current.jsonl"
CLARIFY = PROFILE / "logs" / "memory_clarification_queue.jsonl"
REPORTS = BASE / "reports"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def latest_report(pattern: str) -> dict:
    paths = sorted(REPORTS.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return json.loads(paths[0].read_text(encoding="utf-8")) if paths else {}


def main() -> int:
    connection = sqlite3.connect(f"file:{TURN_DB}?mode=ro", uri=True)
    role_counts = dict(connection.execute("SELECT role, count(*) FROM turns GROUP BY role").fetchall())
    conversation_counts = dict(connection.execute("SELECT role, count(DISTINCT conversation_id) FROM turns GROUP BY role").fetchall())
    non_user_roles = connection.execute("SELECT count(*) FROM turns WHERE role NOT IN ('user','model')").fetchone()[0]
    connection.close()

    proposals = load_jsonl(REVIEW)
    distilled = [row for row in proposals if (row.get("candidate") or {}).get("source") == "google_ai_studio_distilled"]
    canonical = [row for row in distilled if row.get("status") == "approved"]
    clarifications = load_jsonl(CLARIFY)
    pending_atomic = [
        row for row in clarifications
        if row.get("status", "pending") == "pending"
        and row.get("source_type") == "google_ai_studio_distilled"
    ]
    pending_raw = [
        row for row in clarifications
        if row.get("status", "pending") == "pending"
        and row.get("source_type") == "google_ai_studio"
    ]

    gateway = latest_report("holdout-gateway-*-rescored.json") or latest_report("holdout-gateway-*.json")
    gateway_passed = int(gateway.get("passed") or 0)
    gateway_total = int(gateway.get("total") or 0)
    user_turns = int(role_counts.get("user") or 0)
    source_turn_ids = {
        str((row.get("candidate") or {}).get("metadata", {}).get("source_candidate_id") or "")
        for row in distilled
    }
    source_turn_ids.discard("")

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "verdict": {
            "fully_absorbed": False,
            "reason": (
                "Archive and on-demand retrieval are operational, but only a small reviewed subset "
                "has been distilled into canonical durable memory. Indexed history is not equivalent "
                "to complete understanding."
            ),
        },
        "layer_1_archive_integrity": {
            "user_turns": user_turns,
            "model_turns": int(role_counts.get("model") or 0),
            "user_conversations": int(conversation_counts.get("user") or 0),
            "model_conversations": int(conversation_counts.get("model") or 0),
            "unexpected_roles": int(non_user_roles),
            "role_separation_pass": non_user_roles == 0 and user_turns > 0,
        },
        "layer_2_on_demand_retrieval": {
            "gateway_holdout_passed": gateway_passed,
            "gateway_holdout_total": gateway_total,
            "gateway_holdout_rate": round(gateway_passed / gateway_total, 4) if gateway_total else 0.0,
            "holdout_was_not_written_to_graph": True,
            "model_output_allowed_as_user_evidence": False,
        },
        "layer_3_durable_understanding": {
            "approved_canonical_facts": len(canonical),
            "distinct_reviewed_source_candidates": len(source_turn_ids),
            "user_turns": user_turns,
            "source_candidate_coverage_rate": round(len(source_turn_ids) / user_turns, 6) if user_turns else 0.0,
            "pending_atomic_clarifications": len(pending_atomic),
            "pending_raw_aistudio_fragments": len(pending_raw),
            "complete_understanding_claim_allowed": False,
        },
        "how_to_verify": [
            "Re-run the private gateway holdout without first writing holdout facts to Memory Graph.",
            "Add user-chosen questions whose answers are known only from AI Studio history.",
            "For each answer, require an exact user-turn evidence pointer and reject model/Gemini text as user fact.",
            "Test the same questions under a different namespace and require zero private evidence leakage.",
            "Track canonical fact coverage separately from archive and retrieval coverage.",
        ],
        "gateway_report": gateway.get("rescore_of") or "latest private holdout report",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    output = REPORTS / f"absorption-audit-{time.strftime('%Y%m%d_%H%M%S')}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    output.chmod(0o600)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
