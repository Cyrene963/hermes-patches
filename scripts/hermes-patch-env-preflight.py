#!/usr/bin/env python3
"""Hermes patch installer environment preflight.

This script is intentionally dependency-light. It checks whether a fresh machine
has enough Hermes/profile/database/service surface for the patch installer to do
more than copy files, and prints actionable remediation commands without reading
or printing secrets.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any


def which(name: str) -> bool:
    return shutil.which(name) is not None


def run(cmd: list[str], timeout: int = 8) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip()
    except Exception as exc:  # noqa: BLE001 - preflight should never crash install
        return 99, f"{type(exc).__name__}: {exc}"


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def add(checks: list[dict[str, Any]], name: str, status: str, detail: str = "", fix: str = "") -> None:
    checks.append({"name": name, "status": status, "detail": detail, "fix": fix})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hermes-dir", default=os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes" / "hermes-agent"))
    ap.add_argument("--profile-dir", default=os.environ.get("HERMES_PROFILE_DIR") or str(Path.home() / ".hermes"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    hermes_dir = Path(args.hermes_dir).expanduser().resolve()
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    checks: list[dict[str, Any]] = []

    if (hermes_dir / "toolsets.py").exists():
        add(checks, "hermes_repo", "ok", str(hermes_dir))
    else:
        add(
            checks,
            "hermes_repo",
            "fail",
            f"{hermes_dir}/toolsets.py not found",
            "Install Hermes Agent first, or set HERMES_HOME to the hermes-agent repository root.",
        )

    for cmd in ["git", "python3", "curl"]:
        add(checks, f"command:{cmd}", "ok" if which(cmd) else "warn", "found" if which(cmd) else "missing", f"Install `{cmd}` and rerun install.sh." if not which(cmd) else "")
    for cmd in ["psql", "sudo", "systemctl", "npm"]:
        add(checks, f"optional:{cmd}", "ok" if which(cmd) else "warn", "found" if which(cmd) else "missing", f"Install `{cmd}` if you want automatic DB/service/web-audit setup; otherwise installer will skip/degrade that part." if not which(cmd) else "")

    if (hermes_dir / "venv" / "bin" / "python").exists():
        py = str(hermes_dir / "venv" / "bin" / "python")
        add(checks, "hermes_venv", "ok", py)
    else:
        py = sys.executable
        add(checks, "hermes_venv", "warn", "repo venv not found; using current python for import preflight", "Create/install Hermes venv if imports fail.")

    missing = []
    for mod in ["bcrypt", "jieba", "asyncpg", "ahocorasick"]:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    add(
        checks,
        "python_deps",
        "ok" if not missing else "warn",
        "all present" if not missing else "missing: " + ", ".join(missing),
        "Root Debian: apt-get install -y python3-bcrypt python3-jieba python3-asyncpg python3-ahocorasick; or install equivalent packages into the Hermes venv.",
    )

    env_file = profile_dir / ".env"
    if env_file.exists():
        text = env_file.read_text(errors="ignore")
        mg_pw = "MEMORY_GRAPH_DB_PASSWORD=" in text
        add(checks, "profile_env", "ok", f"{env_file} exists; MEMORY_GRAPH_DB_PASSWORD={'present' if mg_pw else 'absent'}")
    else:
        add(checks, "profile_env", "warn", f"{env_file} missing", "install.sh will create it if needed; add provider/API secrets manually if your Hermes profile needs them.")

    # Suppress live-service probes during explicit no-side-effect installer smokes.
    skip_live = os.environ.get("HERMES_INSTALL_SYSTEMD") == "0" and os.environ.get("HERMES_INSTALL_DB") == "0"
    if skip_live:
        add(checks, "postgresql", "warn", "skipped: HERMES_INSTALL_DB=0 and HERMES_INSTALL_SYSTEMD=0", "Unset the skip flags on a real machine to verify PostgreSQL/Hindsight/Memory Graph service health.")
        add(checks, "memory_graph_http", "warn", "skipped: no-side-effect smoke mode", "Run without HERMES_INSTALL_SYSTEMD=0 on the target machine to verify/start Memory Graph HTTP.")
        add(checks, "hindsight_http", "warn", "skipped: no-side-effect smoke mode", "Start/configure Hindsight on the target profile, then rerun preflight.")
    elif which("pg_isready"):
        code, out = run(["pg_isready", "-h", "127.0.0.1", "-p", "5432"], timeout=5)
        add(checks, "postgresql", "ok" if code == 0 else "warn", out, "Install/start PostgreSQL and create the Hindsight database before expecting Memory Graph CRUD to work.")
    else:
        add(checks, "postgresql", "warn", "pg_isready missing", "Install PostgreSQL client/server if Memory Graph DB-backed tools are required.")

    if not skip_live:
        for port, name, url in [(8900, "memory_graph_http", "http://127.0.0.1:8900/health"), (9177, "hindsight_http", "http://127.0.0.1:9177/health")]:
            if which("curl"):
                code, out = run(["curl", "-fsS", "-m", "2", url], timeout=4)
                add(checks, name, "ok" if code == 0 else "warn", out[:300] if out else f"port_open={port_open('127.0.0.1', port)}", f"If this service is needed, install/start it, then rerun install.sh or the patch-chain guard.")
            else:
                add(checks, name, "warn", f"curl missing; raw port_open={port_open('127.0.0.1', port)}")

    hard_fail = any(c["status"] == "fail" for c in checks)
    warn_count = sum(c["status"] == "warn" for c in checks)
    result = {"hermes_dir": str(hermes_dir), "profile_dir": str(profile_dir), "hard_fail": hard_fail, "warn_count": warn_count, "checks": checks}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("🔎 Hermes patch installer preflight")
        print(f"   Hermes repo: {hermes_dir}")
        print(f"   Profile dir: {profile_dir}")
        for c in checks:
            icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}.get(c["status"], "•")
            print(f"   {icon} {c['name']}: {c.get('detail','')}")
            if c.get("fix") and c["status"] != "ok":
                print(f"      fix: {c['fix']}")
        if hard_fail:
            print("❌ Preflight has hard failures. Installer should stop until they are fixed.")
        elif warn_count:
            print(f"⚠️ Preflight completed with {warn_count} warning(s). Installer can continue, but affected services may be degraded until configured.")
        else:
            print("✅ Preflight passed with no warnings.")

    return 2 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
