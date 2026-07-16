#!/usr/bin/env python3
"""Zero-model watchdog for explicit Hermes continuation checkpoints."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import subprocess
import shutil
import time
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CHECKPOINTS = HOME / "runtime" / "continuations"
ACTIVE = HOME / "runtime" / "active_sessions.json"
STATE_DB = HOME / "state.db"
LOCK = HOME / "runtime" / "continuation-watchdog.lock"
LOG = HOME / "logs" / "continuation-watchdog.jsonl"


def resolve_hermes_cli() -> Path | None:
    explicit = os.environ.get("HERMES_CONTINUATION_CLI", "").strip()
    candidates = [
        Path(explicit).expanduser() if explicit else None,
        HOME / "hermes-agent" / "venv" / "bin" / "hermes",
    ]
    candidates.extend(sorted(HOME.glob("hermes-agent-candidate-*/venv/bin/hermes"), reverse=True))
    path_cli = shutil.which("hermes")
    if path_cli:
        candidates.append(Path(path_cli))
    return next((path for path in candidates if path is not None and path.is_file()), None)


HERMES = resolve_hermes_cli()
MODE = os.environ.get("HERMES_CONTINUATION_WATCHDOG_MODE", "execute").strip().lower()
STALE_SECONDS = int(os.environ.get("HERMES_CONTINUATION_STALE_SECONDS", "240"))
TIMEOUT_SECONDS = int(os.environ.get("HERMES_CONTINUATION_TIMEOUT_SECONDS", "1800"))


def log(event: str, **fields) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    payload = {"at": time.time(), "event": event, **fields}
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def active_session_ids() -> set[str]:
    try:
        payload = json.loads(ACTIVE.read_text(encoding="utf-8"))
        entries = payload.get("entries", []) if isinstance(payload, dict) else payload
        return {str(row.get("session_id")) for row in entries if isinstance(row, dict)}
    except Exception:
        return set()


def session_context(session_id: str) -> tuple[str, str] | None:
    try:
        db = sqlite3.connect(STATE_DB)
        row = db.execute(
            "SELECT source, cwd FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        db.close()
    except Exception as exc:
        log("db_error", session_id=session_id, error=str(exc)[:300])
        return None
    if not row:
        return None
    return str(row[0] or ""), str(row[1] or "")


def write_checkpoint(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def run_one(path: Path, now: float, active: set[str]) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log("invalid_checkpoint", path=str(path), error=str(exc)[:300])
        return
    sid = str(payload.get("session_id") or "")
    status = str(payload.get("status") or "")
    age = now - float(payload.get("updated_at") or 0)
    nudges = int(payload.get("nudge_count") or 0)
    max_nudges = int(payload.get("max_nudges") or 3)
    if not sid or sid in active or age < STALE_SECONDS:
        return
    if status not in {"running", "stalled_incomplete", "provider_interrupted"}:
        return
    if nudges >= max_nudges:
        log("circuit_open", session_id=sid, nudge_count=nudges)
        return
    context = session_context(sid)
    if not context:
        log("missing_session", session_id=sid)
        return
    source, cwd = context
    if source != "cli":
        log("unsupported_surface", session_id=sid, source=source)
        return
    workdir = Path(cwd).expanduser() if cwd else Path.home()
    if not workdir.is_dir():
        log("missing_cwd", session_id=sid, cwd=str(workdir))
        return
    if MODE != "execute":
        log("candidate", session_id=sid, status=status, age_seconds=int(age))
        return
    prompt = str(payload.get("next_prompt") or "").strip()
    if not prompt:
        log("missing_prompt", session_id=sid)
        return
    if HERMES is None:
        log("missing_cli", session_id=sid)
        return
    payload["status"] = "running"
    payload["updated_at"] = now
    payload["nudge_count"] = nudges + 1
    write_checkpoint(path, payload)
    log("resume_start", session_id=sid, nudge_count=nudges + 1, cwd=str(workdir))
    try:
        result = subprocess.run(
            [str(HERMES), "-z", prompt, "--resume", sid],
            cwd=workdir,
            text=True,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            env={**os.environ, "HERMES_CONTINUATION_WATCHDOG_CHILD": "1"},
        )
        log(
            "resume_exit",
            session_id=sid,
            exit_code=result.returncode,
            stdout=result.stdout[-1000:],
            stderr=result.stderr[-1000:],
        )
        if result.returncode != 0 and path.exists():
            latest = json.loads(path.read_text(encoding="utf-8"))
            latest["status"] = "provider_interrupted"
            latest["updated_at"] = time.time()
            write_checkpoint(path, latest)
    except subprocess.TimeoutExpired:
        log("resume_timeout", session_id=sid, timeout_seconds=TIMEOUT_SECONDS)
        if path.exists():
            latest = json.loads(path.read_text(encoding="utf-8"))
            latest["status"] = "provider_interrupted"
            latest["updated_at"] = time.time()
            write_checkpoint(path, latest)


def main() -> None:
    if not CHECKPOINTS.is_dir() or not STATE_DB.exists() or HERMES is None:
        return
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        now = time.time()
        active = active_session_ids()
        for path in sorted(CHECKPOINTS.glob("*.json")):
            run_one(path, now, active)


if __name__ == "__main__":
    main()
