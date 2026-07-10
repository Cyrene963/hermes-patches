import json

from agent.correction_regression import (
    build_correction_case,
    evaluate_correction_case,
    record_correction_case,
)
from agent.memory_semantic_classifier import classify_memory_semantics
from agent.memory_write_pipeline import MemoryWritePipeline


def test_correction_case_is_privacy_safe_and_stable():
    evidence = "You stopped after one stage again. Continue until verified; private-token=REDACTED."
    kwargs = dict(
        evidence_text=evidence,
        namespace="tenant:private-user",
        memory_kind="correction_learning_event",
        target_store="memory_graph",
        requires_review=True,
        reject_gate="Continue through inferable stages and verify before completion.",
        future_queries=["user correction root cause prevent recurrence"],
    )
    first = build_correction_case(**kwargs)
    second = build_correction_case(**kwargs)

    assert first.case_id == second.case_id
    assert first.changeset_id == second.changeset_id
    payload = json.dumps(first.to_dict(), ensure_ascii=False)
    assert evidence not in payload
    assert "private-user" not in payload
    assert first.behavior_class == "continuation"


def test_record_is_idempotent(tmp_path):
    case = build_correction_case(
        evidence_text="Do not stop before verification.",
        namespace="tenant:a",
        memory_kind="correction_learning_event",
        target_store="memory_graph",
        requires_review=True,
        reject_gate="Verify before completion.",
        future_queries=["user correction root cause prevent recurrence"],
    )
    path = tmp_path / "corrections.jsonl"
    first = record_correction_case(case, ledger_path=path)
    second = record_correction_case(case, ledger_path=path)

    assert first["recorded"] is True
    assert second["duplicate"] is True
    assert len(path.read_text().splitlines()) == 1


def test_case_evaluator_detects_regression():
    case = build_correction_case(
        evidence_text="Do not stop before verification.",
        namespace="tenant:a",
        memory_kind="correction_learning_event",
        target_store="memory_graph",
        requires_review=True,
        reject_gate="Verify before completion.",
        future_queries=[],
    ).to_dict()
    good = {
        "memory_kind": "correction_learning_event",
        "target_store": "memory_graph",
        "requires_review": True,
        "reject_gate": "Verify before completion.",
    }
    bad = {**good, "memory_kind": "ignore", "reject_gate": ""}
    assert evaluate_correction_case(case, good)["passed"] is True
    failed = evaluate_correction_case(case, bad)
    assert failed["passed"] is False
    assert any("memory_kind" in item for item in failed["failures"])
    assert "reject_gate missing" in failed["failures"]


def test_pipeline_emits_correction_changeset_and_regression(tmp_path):
    path = tmp_path / "corrections.jsonl"
    pipeline = MemoryWritePipeline(config={
        "mode": "shadow",
        "semantic_classifier": {"model_enabled": False},
        "correction_regression_path": str(path),
    })
    reflection = pipeline.reflect_and_extract(
        "错错错，你又中途停了。不要问是否继续，应该持续推进直到真实验收。",
        "明白。",
    )
    candidates = [
        item for item in reflection["candidates"]
        if item.source_type == "user_correction" and hasattr(item, "correction_case_id")
    ]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.changeset_id.startswith("chg_")
    assert candidate.correction_case_id.startswith("corr_")
    row = json.loads(path.read_text().splitlines()[0])
    assert row["case_id"] == candidate.correction_case_id
    assert "错错错" not in json.dumps(row, ensure_ascii=False)

    classification = classify_memory_semantics(
        "错错错，你又中途停了。不要问是否继续，应该持续推进直到真实验收。"
    ).to_dict()
    assert evaluate_correction_case(row, classification)["passed"] is True
