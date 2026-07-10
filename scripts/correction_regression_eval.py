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
        # Raw evidence is intentionally absent. Replay multiple neutral, surface-
        # distinct fixtures for the behavior class. Every variant must preserve
        # the correction route; this tests transfer rather than memorizing one
        # canonical sentence.
        fixtures = {
            "continuation": [
                "错了，不应中途停止；应持续推进并完成真实验收。",
                "不要把阶段性结果当终点，完成剩余步骤并验收。",
                "A partial checkpoint is not completion; carry the task through verification.",
            ],
            "verification": [
                "错了，完成前必须验证并建立防复发回归。",
                "结果还没有经过真实运行，就不要宣布完成；先测试再验收。",
                "Do not claim success from code presence; require runtime evidence.",
            ],
            "memory_recall": [
                "纠正：先召回已有记忆并验证，避免同类问题复发。",
                "不能只记录这次答案，应先回读既有记忆并建立防复发检查。",
                "Do not claim the lesson is learned before memory readback and recurrence testing.",
            ],
            "privacy": [
                "纠正：必须保持 namespace 隐私隔离并验证无泄漏。",
                "这类资料还没有隔离验证就不能写入共享区，必须证明没有跨用户泄漏。",
                "Do not claim isolation before cross-user verification; keep the evidence tenant-scoped.",
            ],
            "overengineering": [
                "有必要吗？这个做法过度设计，应简化为通用机制。",
                "不能只堆更多组件，应删除过度设计并用最小通用机制验收。",
                "Do not call complexity progress; simplify the over-engineered workflow and verify the smaller mechanism.",
            ],
            "tool_route": [
                "纠正：工具失败时先核对正确配置路线并建立防复发门。",
                "还没有核对协议和凭据路线就不能归因于模型，先做真实工具验证。",
                "Do not claim the model failed before checking the configured tool route and protocol.",
            ],
            "factual_correction": [
                "不是旧事实，是新事实；以后先召回并核对。",
                "纠正：当前值已经替代旧值，必须验证旧版本不再处于 active 状态。",
                "The prior value is outdated; supersede it and verify stale recall no longer wins.",
            ],
            "workflow_correction": [
                "错了，应调查根因、应用 reject gate 并防复发。",
                "不要把一次修补当完成，应定位根因并增加可执行回归。",
                "A one-off patch is not completion; identify the cause and add an executable regression gate.",
            ],
        }
        behavior = str(case.get("behavior_class") or "")
        variants = fixtures.get(behavior, fixtures["workflow_correction"])
        variant_results = []
        for variant_index, synthetic in enumerate(variants):
            classification = classify_memory_semantics(synthetic).to_dict()
            evaluated = evaluate_correction_case(case, classification)
            evaluated["variant_index"] = variant_index
            variant_results.append(evaluated)
        failures = [
            failure
            for item in variant_results
            for failure in item.get("failures", [])
        ]
        results.append({
            "case_id": case.get("case_id", ""),
            "passed": all(item["passed"] for item in variant_results),
            "failures": failures,
            "variant_count": len(variant_results),
            "variant_passed": sum(1 for item in variant_results if item["passed"]),
        })
    negative_fixtures = [
        "继续这个故事的下一段。",
        "验证这个数学等式是否成立。",
        "这个项目使用命名空间组织模块。",
    ]
    negative_false_positives = sum(
        1
        for text in negative_fixtures
        if classify_memory_semantics(text).memory_kind == "correction_learning_event"
    )
    passed = sum(1 for item in results if item["passed"])
    variant_total = sum(item.get("variant_count", 0) for item in results)
    variant_passed = sum(item.get("variant_passed", 0) for item in results)
    failed = len(results) - passed + negative_false_positives
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "invalid": invalid,
        "variant_total": variant_total,
        "variant_passed": variant_passed,
        "negative_total": len(negative_fixtures),
        "negative_false_positives": negative_false_positives,
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
