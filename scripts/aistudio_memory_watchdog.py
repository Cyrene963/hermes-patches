#!/usr/bin/env python3
"""Half-hour AI Studio/Gemini memory sync watchdog.

Cron/no-agent wrapper. Silent on ordinary no-change success; prints a short report
only when new/changed files are indexed or when real errors occur.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROFILE = Path(os.environ.get("HERMES_PROFILE_DIR") or (Path.home() / ".hermes"))
_base_env = str(os.environ.get("AISTUDIO_MEMORY_BASE") or "").strip()
_default_base = PROFILE / "memories" / "aistudio_gemini"
BASE = Path(_base_env) if _base_env else _default_base
REPORTS = BASE / "reports"
STATE = BASE / "watchdog_state.json"
SCRIPTS = PROFILE / "scripts"
_runtime_python_env = str(os.environ.get("HERMES_RUNTIME_PYTHON") or "").strip()
_default_runtime_python = PROFILE / "hermes-agent" / "venv" / "bin" / "python"
RUNTIME_PYTHON = Path(_runtime_python_env) if _runtime_python_env else _default_runtime_python
PYTHON = str(RUNTIME_PYTHON) if RUNTIME_PYTHON.exists() else sys.executable
SYNC = SCRIPTS / "aistudio_drive_sync.py"
PARSE = SCRIPTS / "aistudio_archive_parse.py"
FTS = SCRIPTS / "aistudio_fts_index.py"
TURN = SCRIPTS / "aistudio_turn_extract.py"
TURN_INDEX = SCRIPTS / "aistudio_turn_index.py"
TREASURE = SCRIPTS / "aistudio_treasure_review.py"
CONVERT = SCRIPTS / "convert_aistudio_to_review_proposals.py"
DISTILL = SCRIPTS / "aistudio_distill_review_proposals.py"
CONTINUOUS_DISTILL = SCRIPTS / "aistudio_continuous_distill.py"
CONTINUOUS_REVIEW = SCRIPTS / "aistudio_continuous_review.py"


def chmod_private(path: Path) -> None:
    try:
        path.chmod(0o600)
    except FileNotFoundError:
        pass


def run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def latest(pattern: str) -> Path | None:
    files = sorted(REPORTS.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def read_json(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    chmod_private(STATE)


def file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifacts_ready() -> bool:
    required = [
        BASE / "manifest.jsonl",
        BASE / "aistudio_memory.sqlite3",
        BASE / "turns.jsonl",
        BASE / "aistudio_turns.sqlite3",
        BASE / "review_queue.jsonl",
        BASE / "distillation_rules.json",
    ]
    return all(path.exists() and path.stat().st_size > 0 for path in required)


def input_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in [BASE / "manifest.jsonl", BASE / "review_queue.jsonl", BASE / "distillation_rules.json"]:
        digest.update(path.name.encode("utf-8"))
        digest.update(file_sha256(path).encode("ascii"))
    return digest.hexdigest()


def prune_reports(keep_per_pattern: int = 20) -> int:
    removed = 0
    for pattern in [
        "drive-sync-*.json", "parse-report-*.json", "fts-index-report-*.json",
        "turn-extract-report-*.json", "turn-index-report-*.json",
        "treasure-review-report-*.json", "continuous-distill-*.json",
    ]:
        files = sorted(REPORTS.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[keep_per_pattern:]:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def main() -> int:
    if not _base_env and not BASE.is_symlink():
        print("AISTUDIO_MEMORY_BASE is required unless the profile has a private memories/aistudio_gemini symlink", file=sys.stderr)
        return 2
    REPORTS.mkdir(parents=True, exist_ok=True)
    before_manifest = sum(1 for _ in (BASE / "manifest.jsonl").open("r", encoding="utf-8")) if (BASE / "manifest.jsonl").exists() else 0

    sync = run([str(SYNC), "sync", "--limit", "1000"], timeout=600)
    sync_report = read_json(latest("drive-sync-*.json"))
    real_sync_errors = sync_report.get("errors", [])
    synced_count = int(sync_report.get("synced_count") or 0)
    state = load_state()
    current_fingerprint = input_fingerprint()
    continuous = run([
        PYTHON, str(CONTINUOUS_DISTILL),
        "--config", str(BASE / "continuous_distill_config.json"),
        "--turn-db", str(BASE / "aistudio_turns.sqlite3"),
        "--state-db", str(BASE / "continuous_distill.sqlite3"),
        "--limit", "24", "--batch-size", "6", "--apply",
    ], timeout=900) if CONTINUOUS_DISTILL.exists() and artifacts_ready() else subprocess.CompletedProcess([], 0, "", "")
    continuous_report = read_json(latest("continuous-distill-*.json"))
    continuous_review = run([
        PYTHON, str(CONTINUOUS_REVIEW), "--limit", "60", "--batch-size", "12", "--concurrency", "3",
    ], timeout=900) if CONTINUOUS_REVIEW.exists() and continuous.returncode == 0 else subprocess.CompletedProcess([], 0, "", "")
    continuous_review_report = read_json(latest("continuous-second-review-*.json"))
    if (
        sync.returncode == 0
        and not real_sync_errors
        and synced_count == 0
        and artifacts_ready()
        and state.get("input_fingerprint") == current_fingerprint
    ):
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        state.update({
            "last_run_at": now,
            "synced_count": 0,
            "sync_error_count": 0,
            "fast_path": True,
            "continuous_distill_returncode": continuous.returncode,
            "continuous_processed_user_turns": int(continuous_report.get("processed_user_turns") or 0),
            "continuous_total_user_turns": int(continuous_report.get("total_user_turns") or 0),
            "continuous_processing_coverage_rate": float(continuous_report.get("processing_coverage_rate") or 0.0),
            "continuous_proposals": int(continuous_report.get("proposal_count") or 0),
            "continuous_clarifications": int(continuous_report.get("clarification_count") or 0),
            "continuous_review_returncode": continuous_review.returncode,
            "continuous_reviewed": int(continuous_review_report.get("pending_reviewed") or 0),
            "continuous_review_approved": len((continuous_review_report.get("applied") or {}).get("approved") or []),
            "reports_pruned": prune_reports(),
        })
        save_state(state)
        if continuous.returncode != 0 or continuous_review.returncode != 0:
            print(f"- continuous_distill_returncode={continuous.returncode}")
            print(f"- continuous_review_returncode={continuous_review.returncode}")
            if continuous.stderr:
                print(continuous.stderr[-1000:])
            return 1
        return 0

    # Rebuild safe metadata index only when Drive or local distillation inputs changed.
    parse = run([str(PARSE)], timeout=600)
    parse_report = read_json(latest("parse-report-*.json"))

    fts = run([str(FTS), "--quiet"], timeout=900)
    fts_report = read_json(latest("fts-index-report-*.json"))

    turn = run([str(TURN), "--quiet"], timeout=600)
    turn_report = read_json(latest("turn-extract-report-*.json"))
    turn_index = run([str(TURN_INDEX), "--quiet"], timeout=300)
    turn_index_report = read_json(latest("turn-index-report-*.json"))
    treasure = run([str(TREASURE), "--quiet", "--min-score", "14"], timeout=600)
    treasure_report = read_json(latest("treasure-review-report-*.json"))
    convert = run([PYTHON, str(CONVERT), "--replace-aistudio"], timeout=300)
    try:
        convert_report = json.loads(convert.stdout) if convert.stdout.strip() else {}
    except Exception:
        convert_report = {}
    distill_report_path = REPORTS / "aistudio-distill-latest.json"
    distill = run([
        PYTHON, str(DISTILL),
        "--input", str(BASE / "review_queue.jsonl"),
        "--rules", str(BASE / "distillation_rules.json"),
        "--apply", "--report", str(distill_report_path),
    ], timeout=300)
    distill_report = read_json(distill_report_path)

    after_manifest = sum(1 for _ in (BASE / "manifest.jsonl").open("r", encoding="utf-8")) if (BASE / "manifest.jsonl").exists() else 0
    state = load_state()
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary = {
        "last_run_at": now,
        "fast_path": False,
        "input_fingerprint": input_fingerprint(),
        "reports_pruned": prune_reports(),
        "manifest_lines": after_manifest,
        "sync_report": str(latest("drive-sync-*.json") or ""),
        "parse_report": str(latest("parse-report-*.json") or ""),
        "fts_report": str(latest("fts-index-report-*.json") or ""),
        "turn_report": str(latest("turn-extract-report-*.json") or ""),
        "turn_index_report": str(latest("turn-index-report-*.json") or ""),
        "treasure_report": str(latest("treasure-review-report-*.json") or ""),
        "synced_count": int(sync_report.get("synced_count") or 0),
        "sync_error_count": len(real_sync_errors),
        "parse_errors": int(parse_report.get("errors") or 0),
        "newly_indexed": int(fts_report.get("newly_indexed") or 0),
        "db_conversations": int(fts_report.get("db_conversations") or 0),
        "db_prompt_chars": int(fts_report.get("db_prompt_chars") or 0),
        "turns": int(turn_report.get("turns") or 0),
        "review_new_candidates": int(treasure_report.get("new_candidates") or 0),
        "review_total_candidates": int(treasure_report.get("total_candidates") or 0),
        "unified_imported_new": int(convert_report.get("imported_new") or 0),
        "unified_review_total": int(convert_report.get("total_after") or 0),
        "unified_review_output": str(convert_report.get("output") or ""),
        "distilled_proposals": int(distill_report.get("proposal_count") or 0),
        "distilled_ready_memory": int(distill_report.get("ready_memory") or 0),
        "distilled_needs_dedup": int(distill_report.get("needs_dedup_review") or 0),
        "distilled_clarifications": int(distill_report.get("clarification_count") or 0),
        "distilled_already_canonical": int(distill_report.get("already_canonical") or 0),
        "continuous_distill_returncode": continuous.returncode,
        "continuous_processed_user_turns": int(continuous_report.get("processed_user_turns") or 0),
        "continuous_total_user_turns": int(continuous_report.get("total_user_turns") or 0),
        "continuous_processing_coverage_rate": float(continuous_report.get("processing_coverage_rate") or 0.0),
        "continuous_proposals": int(continuous_report.get("proposal_count") or 0),
        "continuous_clarifications": int(continuous_report.get("clarification_count") or 0),
        "continuous_review_returncode": continuous_review.returncode,
        "continuous_reviewed": int(continuous_review_report.get("pending_reviewed") or 0),
        "continuous_review_approved": len((continuous_review_report.get("applied") or {}).get("approved") or []),
    }
    state.update(summary)
    save_state(state)

    # Cron no_agent delivery semantics: empty stdout = silent.
    # Print only user-actionable changes or real failures. Routine review-queue
    # normalization can change `unified_imported_new` without new AI Studio data,
    # so it must not page Telegram by itself.
    should_print = (
        summary["synced_count"] > 0
        or summary["newly_indexed"] > 0
        or summary["review_new_candidates"] > 0
        or summary["sync_error_count"] > 0
        or sync.returncode != 0
        or fts.returncode != 0
        or turn.returncode != 0
        or turn_index.returncode != 0
        or treasure.returncode != 0
        or convert.returncode != 0
        or distill.returncode != 0
        or continuous.returncode != 0
        or continuous_review.returncode != 0
    )
    if should_print:
        print("AI Studio memory sync:")
        print(f"- synced_new_or_changed={summary['synced_count']}")
        print(f"- newly_indexed={summary['newly_indexed']}")
        print(f"- db_conversations={summary['db_conversations']}")
        print(f"- db_prompt_chars={summary['db_prompt_chars']}")
        print(f"- turns={summary['turns']}")
        print(f"- review_new_candidates={summary['review_new_candidates']}")
        print(f"- review_total_candidates={summary['review_total_candidates']}")
        print(f"- unified_imported_new={summary['unified_imported_new']}")
        print(f"- unified_review_total={summary['unified_review_total']}")
        print(f"- unified_review_output={summary['unified_review_output']}")
        print(f"- distilled_proposals={summary['distilled_proposals']}")
        print(f"- distilled_ready_memory={summary['distilled_ready_memory']}")
        print(f"- distilled_needs_dedup={summary['distilled_needs_dedup']}")
        print(f"- distilled_clarifications={summary['distilled_clarifications']}")
        print(f"- distilled_already_canonical={summary['distilled_already_canonical']}")
        print(f"- manifest_lines={after_manifest} (before={before_manifest})")
        if sync.returncode != 0:
            print(f"- sync_returncode={sync.returncode}")
            if sync.stderr:
                print(sync.stderr[-1000:])
        if summary["sync_error_count"]:
            print(f"- sync_errors={summary['sync_error_count']}: {real_sync_errors[:3]}")
        if fts.returncode != 0:
            print(f"- fts_error_returncode={fts.returncode}")
            if fts.stderr:
                print(fts.stderr[-1000:])
        if turn.returncode != 0:
            print(f"- turn_extract_returncode={turn.returncode}")
            if turn.stderr:
                print(turn.stderr[-1000:])
        if turn_index.returncode != 0:
            print(f"- turn_index_returncode={turn_index.returncode}")
            if turn_index.stderr:
                print(turn_index.stderr[-1000:])
        if treasure.returncode != 0:
            print(f"- treasure_review_returncode={treasure.returncode}")
            if treasure.stderr:
                print(treasure.stderr[-1000:])
        if convert.returncode != 0:
            print(f"- convert_review_returncode={convert.returncode}")
            if convert.stderr:
                print(convert.stderr[-1000:])
        if distill.returncode != 0:
            print(f"- distill_review_returncode={distill.returncode}")
            if distill.stderr:
                print(distill.stderr[-1000:])
        print(f"- state={STATE}")
    # Do not fail cron for known parse non-JSON artifacts; fail for sync/index/review real errors.
    if summary["sync_error_count"] or sync.returncode != 0 or fts.returncode != 0 or turn.returncode != 0 or turn_index.returncode != 0 or treasure.returncode != 0 or convert.returncode != 0 or distill.returncode != 0 or continuous.returncode != 0 or continuous_review.returncode != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
