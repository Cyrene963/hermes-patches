import json

from agent.correction_regression import build_correction_case
from scripts.correction_regression_eval import replay_cases


def test_replay_active_case_passes(tmp_path):
    case = build_correction_case(
        evidence_text="Do not stop before verification.",
        namespace="tenant:a",
        memory_kind="correction_learning_event",
        target_store="memory_graph",
        requires_review=True,
        reject_gate="Verify before completion.",
        future_queries=["user correction root cause prevent recurrence"],
    )
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps(case.to_dict(), ensure_ascii=False) + "\n")
    report = replay_cases(path)
    assert report["total"] == 1
    assert report["passed"] == 1
    assert report["failed"] == 0
    assert report["variant_total"] == 3
    assert report["variant_passed"] == 3
    assert report["negative_false_positives"] == 0


def test_replay_detects_schema_expectation_regression(tmp_path):
    case = build_correction_case(
        evidence_text="Do not stop before verification.",
        namespace="tenant:a",
        memory_kind="correction_learning_event",
        target_store="memory_graph",
        requires_review=True,
        reject_gate="Verify before completion.",
        future_queries=[],
    ).to_dict()
    case["expected_target_store"] = "ignore"
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps(case, ensure_ascii=False) + "\n")
    report = replay_cases(path)
    assert report["failed"] == 1
    assert any("target_store" in failure for failure in report["results"][0]["failures"])


def test_replay_counts_invalid_rows(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text("not-json\n")
    report = replay_cases(path)
    assert report["invalid"] == 1
