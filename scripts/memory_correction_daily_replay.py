#!/usr/bin/env python3
"""Daily correction-regression replay; silent on success, alert on regression."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
AGENT_DIR = Path(os.environ.get("HERMES_AGENT_DIR") or (HOME / "hermes-agent"))
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from scripts.correction_regression_eval import replay_cases

LEDGER = HOME / "logs" / "memory_correction_regressions.jsonl"
BASELINE = HOME / "tasks" / "digital-brain-99-baselines"
REPORT = BASELINE / "correction-regression-daily-latest.json"
HISTORY = BASELINE / "correction-regression-history"
SCORECARD = BASELINE / "memory-os-scorecard.json"
SCORE_RESULT = BASELINE / "memory-os-scorecard-result.json"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _ledger_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_history_once(path: Path, payload: dict) -> bool:
    """Create an immutable daily record, returning False when it already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(serialized)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        return True
    finally:
        tmp.unlink(missing_ok=True)


def _successful_history() -> list[Path]:
    valid = []
    for path in sorted(HISTORY.glob("????-??-??.json")):
        try:
            item = json.loads(path.read_text())
        except Exception:
            continue
        if item.get("date") != path.stem:
            continue
        ledger_sha256 = item.get("ledger_sha256")
        if not isinstance(ledger_sha256, str) or len(ledger_sha256) != 64:
            continue
        try:
            int(ledger_sha256, 16)
        except ValueError:
            continue
        if item.get("total", 0) > 0 and item.get("failed") == 0 and item.get("invalid") == 0:
            valid.append(path)
    return valid


def _promote_scorecard(history: list[Path]) -> None:
    if len(history) < 2 or not SCORECARD.exists():
        return
    data = json.loads(SCORECARD.read_text())
    changed = False
    for capability in data.get("capabilities", []):
        if capability.get("id") != "correction_learning":
            continue
        for gate in capability.get("gates", []):
            if gate.get("id") != "daily_replay_history":
                continue
            gate.clear()
            gate.update({
                "id": "daily_replay_history",
                "status": "PASS",
                "path": str(HISTORY),
                "evidence": f"successful correction replay on {history[-2].stem} and {history[-1].stem}",
            })
            changed = True
    if not changed:
        return
    _atomic_json(SCORECARD, data)
    evaluator = AGENT_DIR / "scripts" / "memory_os_scorecard.py"
    if not evaluator.exists():
        evaluator = HOME / "scripts" / "memory_os_scorecard.py"
    if evaluator.exists():
        subprocess.run(
            [sys.executable, str(evaluator), str(SCORECARD), "--output", str(SCORE_RESULT)],
            check=True,
            stdout=subprocess.DEVNULL,
        )


def main() -> int:
    report = replay_cases(LEDGER)
    now = datetime.now(timezone.utc).astimezone()
    payload = {
        "date": now.date().isoformat(),
        "evaluated_at": now.isoformat(),
        "ledger_sha256": _ledger_sha256(LEDGER) if LEDGER.exists() else None,
        **report,
    }
    _atomic_json(REPORT, payload)
    ok = report["total"] > 0 and report["failed"] == 0 and report["invalid"] == 0
    if not ok:
        print(
            "Memory correction regression alert: "
            f"passed={report['passed']} total={report['total']} "
            f"failed={report['failed']} invalid={report['invalid']}"
        )
        return 1
    _write_history_once(HISTORY / f"{payload['date']}.json", payload)
    _promote_scorecard(_successful_history())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
