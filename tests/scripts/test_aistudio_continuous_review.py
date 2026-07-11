import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "aistudio_continuous_review.py"
    spec = importlib.util.spec_from_file_location("continuous_review", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deterministic_block_rejects_one_off_and_sensitive_items():
    module = load_module()
    assert module.deterministic_block({"fact": "用户这次先这么用，出了问题再修。", "evidence_quote": "先这么用", "risk": "low", "volatility": "stable", "kind": "project"})
    assert module.deterministic_block({"fact": "用户的家庭关系状态。", "evidence_quote": "家庭关系", "risk": "high", "volatility": "sensitive", "kind": "relationship"})


def test_deterministic_block_accepts_stable_learning_weakness():
    module = load_module()
    assert module.deterministic_block({"fact": "用户英语阅读速度慢且经常做不完。", "evidence_quote": "做阅读速度太慢了，题目总是做不完", "risk": "low", "volatility": "stable", "kind": "learning"}) == ""


def test_review_prompt_contains_adversarial_long_term_gate():
    module = load_module()
    prompt = module.review_prompt([{"proposal_id": "p", "fact": "f"}])
    assert "multiple future conversations" in prompt
    assert "project implementation details" in prompt
    assert "below 10%" in prompt


def test_api_approval_happens_after_single_queue_snapshot_write():
    module = load_module()
    assert module.__file__
    text = Path(module.__file__).read_text(encoding="utf-8")
    before_loop, after_loop = text.split("for proposal_id in approval_ids:", 1)
    assert "atomic_jsonl(args.queue, rows)" in before_loop
    assert "atomic_jsonl(args.queue, rows)" not in after_loop


def _ready_row(*, role="user", risk="low", volatility="stable", status="pending", distilled=True):
    return {
        "status": status,
        "candidate": {
            "distilled": distilled,
            "risk_level": risk,
            "readback_queries": ["stable fact"],
            "metadata": {"role": role, "volatility": volatility},
        },
        "decision": {"target_store": "review"},
    }


def test_promote_ready_memory_requires_consensus_but_does_not_approve():
    module = load_module()
    row = _ready_row()
    module.promote_ready_memory(row, consensus_gate="independent_a_b", promoted_at="2026-01-01T00:00:00+00:00")
    assert row["status"] == "pending"
    assert row["candidate"]["suggested_store"] == "memory_graph"
    assert row["candidate"]["metadata"]["target_store"] == "memory_graph"
    assert row["candidate"]["metadata"]["consensus_gate"] == "independent_a_b"
    assert row["decision"]["target_store"] == "memory_graph"


def test_promote_ready_memory_rejects_non_user_sensitive_or_raw_candidates():
    module = load_module()
    import pytest
    for row in (
        _ready_row(role="model"),
        _ready_row(risk="medium"),
        _ready_row(volatility="time_bound"),
        _ready_row(distilled=False),
    ):
        with pytest.raises(ValueError):
            module.promote_ready_memory(row, consensus_gate="independent_a_b")


def test_demote_unconsented_ready_memory_fails_closed():
    module = load_module()
    row = _ready_row()
    row["candidate"]["suggested_store"] = "memory_graph"
    assert module.demote_unconsented_ready_memory(row, demoted_at="2026-01-01T00:00:00+00:00") is True
    assert row["candidate"]["suggested_store"] == "review"
    assert row["candidate"]["metadata"]["review_state"] == "needs_consensus_review"
    assert module.demote_unconsented_ready_memory(row) is False


def test_reviewer_uses_same_private_lock_as_distiller():
    module = load_module()
    assert module.LOCK.name == "continuous_distill.lock"
