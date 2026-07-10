#!/usr/bin/env python3
"""Evaluate the Memory OS capability scorecard from verifiable evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PASS = "PASS"
ZERO = {"FAIL", "SKIP", "MISSING", "STALE", "ERROR"}


def _git_has_commit(repo: str | Path, commit: str) -> bool:
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=str(repo), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return True
    except Exception:
        return False


def _verify_gate(gate: dict[str, Any], *, scorecard_path: Path) -> tuple[str, str]:
    declared = str(gate.get("status") or "MISSING").upper()
    if declared in ZERO:
        return declared, "declared unproven"
    if declared != PASS:
        return "ERROR", f"unknown status {declared}"

    if gate.get("evidence_file"):
        path = Path(str(gate["evidence_file"])).expanduser()
        if not path.exists() or path.stat().st_size == 0:
            return "MISSING", f"evidence file missing: {path}"
    if gate.get("json"):
        path = Path(str(gate["json"])).expanduser()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return "ERROR", f"invalid JSON evidence: {exc.__class__.__name__}"
        for key, expected in (gate.get("json_require") or {}).items():
            if payload.get(key) != expected:
                return "FAIL", f"JSON {key}={payload.get(key)!r}, expected {expected!r}"
    if gate.get("git_commit"):
        repo = gate.get("repo") or scorecard_path.parent.parent
        if not _git_has_commit(repo, str(gate["git_commit"])):
            return "MISSING", f"commit unavailable: {gate['git_commit']}"
    if gate.get("repo") and gate.get("id") == "remote_parity":
        repo = str(gate["repo"])
        try:
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True, timeout=20).strip()
            remote = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=repo, text=True, timeout=20).strip()
        except Exception as exc:
            return "ERROR", f"git parity unavailable: {exc.__class__.__name__}"
        if head != remote:
            return "FAIL", "local HEAD differs from origin/main"
    if gate.get("config_key"):
        hermes_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
        config = yaml.safe_load((hermes_home / "config.yaml").read_text(encoding="utf-8")) or {}
        value: Any = config
        for part in str(gate["config_key"]).split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value != gate.get("expected"):
            return "FAIL", f"config value {value!r}, expected {gate.get('expected')!r}"
    if gate.get("health_url"):
        try:
            with urllib.request.urlopen(str(gate["health_url"]), timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
            if body.get("status") != "ok":
                return "FAIL", f"health status {body.get('status')!r}"
        except Exception as exc:
            return "FAIL", f"health check failed: {exc.__class__.__name__}"
    return PASS, "verified"


def evaluate_scorecard(path: str | Path) -> dict[str, Any]:
    scorecard_path = Path(path).expanduser()
    doc = json.loads(scorecard_path.read_text(encoding="utf-8"))
    capabilities = []
    total_weight = 0.0
    earned = 0.0
    for capability in doc.get("capabilities") or []:
        weight = float(capability.get("weight") or 0)
        total_weight += weight
        gates = []
        passed = 0
        for gate in capability.get("gates") or []:
            status, detail = _verify_gate(gate, scorecard_path=scorecard_path)
            gates.append({"id": gate.get("id"), "status": status, "detail": detail})
            if status == PASS:
                passed += 1
        gate_count = len(gates)
        ratio = passed / gate_count if gate_count else 0.0
        capability_score = weight * ratio
        earned += capability_score
        capabilities.append({
            "id": capability.get("id"),
            "weight": weight,
            "passed_gates": passed,
            "total_gates": gate_count,
            "score": round(capability_score, 3),
            "max_score": weight,
            "gates": gates,
        })
    score = 100.0 * earned / total_weight if total_weight else 0.0
    missing = []
    for cap in capabilities:
        for gate in cap["gates"]:
            if gate["status"] != PASS:
                missing.append({
                    "capability": cap["id"],
                    "weight": cap["weight"],
                    **gate,
                })
    missing.sort(key=lambda item: (-item["weight"], item["capability"], str(item["id"])))
    return {
        "schema_version": doc.get("schema_version"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "score": round(score, 2),
        "earned_weight": round(earned, 3),
        "total_weight": round(total_weight, 3),
        "passed_gates": sum(cap["passed_gates"] for cap in capabilities),
        "total_gates": sum(cap["total_gates"] for cap in capabilities),
        "capabilities": capabilities,
        "next_gaps": missing[:10],
        "release_passed": not missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scorecard")
    parser.add_argument("--output")
    parser.add_argument("--require-score", type=float)
    args = parser.parse_args()
    report = evaluate_scorecard(args.scorecard)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    if args.require_score is not None and report["score"] < args.require_score:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
