#!/usr/bin/env python3
"""Create private distillation suggestions for raw Memory OS review proposals.

This is intentionally conservative:
- reads only task-local private raw proposal files;
- writes 0600 local suggestion files;
- prints only metadata and counts;
- never mutates Memory Graph or proposal statuses.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Any

PROFILE_DIR = Path(os.environ.get("HERMES_PROFILE_DIR") or (Path.home() / ".hermes"))
BASE = Path(os.environ.get("DIGITAL_BRAIN_99_TASK_DIR") or (PROFILE_DIR / "tasks" / "digital-brain-99"))
RAW_DIR = BASE / "conversion_drafts" / "private_raw"
OUT_DIR = BASE / "distillation_suggestions"
REPORT_DIR = BASE / "reports"


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _latest_private_raw_files(raw_dir: Path) -> list[Path]:
    if not raw_dir.exists():
        return []
    latest: dict[str, Path] = {}
    for path in sorted(raw_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
        obj = _load_json(path)
        if not obj:
            continue
        key = str(obj.get("proposal_id") or path.stem)
        latest[key] = path
    return list(latest.values())


def _compress(text: str, max_chars: int = 360) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    parts = re.split(r"(?<=[。！？.!?])\s+", text)
    candidate = " ".join(parts[:2]).strip() if parts else text
    if not candidate:
        candidate = text
    if len(candidate) > max_chars:
        candidate = candidate[: max_chars - 3].rstrip() + "..."
    return candidate


def _suggestion_from(raw: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    content = str(raw.get("content") or "")
    return {
        "proposal_id": raw.get("proposal_id"),
        "source_private_raw_path": str(raw_path),
        "namespace_scope": raw.get("namespace_scope"),
        "candidate_kind": raw.get("candidate_kind"),
        "risk_level": raw.get("risk_level"),
        "target_store": raw.get("target_store"),
        "approval_status": "needs_human_or_strong_model_review",
        "suggested_memory_draft": _compress(content),
        "confidence": "low_to_medium_auto_distillation",
        "warnings": [
            "auto-compressed from private raw material; verify against source before writing Memory Graph",
            "do not approve if this is merely a raw excerpt, transient task status, or unsupported inference",
        ],
        "readback_queries": raw.get("readback_queries") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    report_dir = Path(args.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _chmod(out_dir, 0o700)

    summary: list[dict[str, Any]] = []
    for raw_path in _latest_private_raw_files(raw_dir):
        raw = _load_json(raw_path)
        if not raw:
            continue
        suggestion = _suggestion_from(raw, raw_path)
        proposal_id = str(raw.get("proposal_id") or raw_path.stem)
        out_path = out_dir / f"{proposal_id}.distilled.json"
        out_path.write_text(json.dumps(suggestion, ensure_ascii=False, indent=2), encoding="utf-8")
        _chmod(out_path, 0o600)
        summary.append(
            {
                "proposal_id_suffix": proposal_id[-8:],
                "candidate_kind": raw.get("candidate_kind"),
                "chars_in": len(str(raw.get("content") or "")),
                "draft_chars": len(str(suggestion.get("suggested_memory_draft") or "")),
                "file": str(out_path),
            }
        )

    stamp = time.strftime("%Y%m%d_%H%M%S")
    report = report_dir / f"proposal-distillation-suggestions-{stamp}.json"
    report.write_text(json.dumps({"count": len(summary), "suggestions": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report)
    print(f"suggestions {len(summary)}")
    for item in summary:
        print(f"{item['proposal_id_suffix']} {item['candidate_kind']} {item['chars_in']} -> {item['draft_chars']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
