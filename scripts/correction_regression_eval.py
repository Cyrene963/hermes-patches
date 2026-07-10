#!/usr/bin/env python3
"""Replay privacy-safe correction regression cases against the current classifier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.correction_regression import evaluate_correction_case
from agent.memory_semantic_classifier import classify_memory_semantics


def replay_cases(path: str | Path) -> dict[str, Any]:
    ledger = Path(path).expanduser()
    results = []
    invalid = 0
    if not ledger.exists():
        return {"total": 0, "passed": 0, "failed": 0, "invalid": 0, "results": []}
    for raw in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            case = json.loads(raw)
        except Exception:
            invalid += 1
            continue
        if case.get("status", "active") != "active":
            continue
        # Raw evidence is intentionally absent. Replay a neutral fixture for the
        # recorded behavior class plus the stored reject gate. This checks current
        # routing without reconstructing private text.
        fixtures = {
            "continuation": "错了，不应中途停止；应持续推进并完成真实验收。",
            "verification": "错了，完成前必须验证并建立防复发回归。",
            "memory_recall": "纠正：先召回已有记忆并验证，避免同类问题复发。",
            "privacy": "纠正：必须保持 namespace 隐私隔离并验证无泄漏。",
            "overengineering": "有必要吗？这个做法过度设计，应简化为通用机制。",
            "tool_route": "纠正：工具失败时先核对正确配置路线并建立防复发门。",
            "factual_correction": "不是旧事实，是新事实；以后先召回并核对。",
            "workflow_correction": "错了，应调查根因、应用 reject gate 并防复发。",
        }
        synthetic = fixtures.get(str(case.get("behavior_class") or ""), fixtures["workflow_correction"])
        classification = classify_memory_semantics(synthetic).to_dict()
        result = evaluate_correction_case(case, classification)
        results.append(result)
    passed = sum(1 for item in results if item["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "invalid": invalid,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ledger",
        default="~/.hermes/logs/memory_correction_regressions.jsonl",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = replay_cases(args.ledger)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"correction regressions: {report['passed']}/{report['total']} passed; "
            f"failed={report['failed']} invalid={report['invalid']}"
        )
        for item in report["results"]:
            if not item["passed"]:
                print(f"FAIL {item['case_id']}: {'; '.join(item['failures'])}")
    return 0 if report["failed"] == 0 and report["invalid"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
