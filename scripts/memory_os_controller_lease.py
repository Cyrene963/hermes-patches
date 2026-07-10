#!/usr/bin/env python3
"""Single-writer lease and verified handoff helpers for Memory OS controllers."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import time
from pathlib import Path

_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_TASKS_DIR = _HERMES_HOME / "tasks"
LOCK_DIR = _TASKS_DIR / "memory-os-writer.lock"
HANDOFF = _TASKS_DIR / "digital-brain-99-baselines" / "controller-handoff.json"


def acquire(owner: str, ttl: int = 7200) -> dict:
    now = int(time.time())
    LOCK_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        LOCK_DIR.mkdir()
    except FileExistsError:
        lease_path = LOCK_DIR / "lease.json"
        try:
            lease = json.loads(lease_path.read_text())
        except Exception:
            lease = {}
        expires = int(lease.get("expires_at") or 0)
        if expires > now:
            return {"acquired": False, "holder": lease.get("owner", "unknown"), "expires_at": expires}
        shutil.rmtree(LOCK_DIR, ignore_errors=True)
        try:
            LOCK_DIR.mkdir()
        except FileExistsError:
            return {"acquired": False, "holder": "raced", "expires_at": 0}
    lease = {
        "owner": owner,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "acquired_at": now,
        "expires_at": now + max(60, ttl),
    }
    (LOCK_DIR / "lease.json").write_text(json.dumps(lease, sort_keys=True) + "\n")
    return {"acquired": True, **lease}


def release(owner: str) -> dict:
    lease_path = LOCK_DIR / "lease.json"
    try:
        lease = json.loads(lease_path.read_text())
    except Exception:
        lease = {}
    if LOCK_DIR.exists() and lease.get("owner") not in {None, "", owner}:
        return {"released": False, "holder": lease.get("owner")}
    shutil.rmtree(LOCK_DIR, ignore_errors=True)
    return {"released": True}


def validate_handoff(path: Path = HANDOFF) -> dict:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return {"valid": False, "error": exc.__class__.__name__}
    required = ("commit", "tests_passed", "fresh_replay_passed", "remote_parity", "live_restart_required")
    missing = [key for key in required if key not in data]
    valid = not missing and bool(data["commit"]) and bool(data["tests_passed"]) and bool(data["fresh_replay_passed"]) and bool(data["remote_parity"])
    return {"valid": valid, "missing": missing, "handoff": data if valid else None}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p_acquire = sub.add_parser("acquire")
    p_acquire.add_argument("--owner", required=True)
    p_acquire.add_argument("--ttl", type=int, default=7200)
    p_release = sub.add_parser("release")
    p_release.add_argument("--owner", required=True)
    p_validate = sub.add_parser("validate-handoff")
    p_validate.add_argument("--path", default=str(HANDOFF))
    args = parser.parse_args()
    if args.action == "acquire":
        result = acquire(args.owner, args.ttl)
    elif args.action == "release":
        result = release(args.owner)
    else:
        result = validate_handoff(Path(args.path))
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("acquired", result.get("released", result.get("valid", False))) else 2


if __name__ == "__main__":
    raise SystemExit(main())
