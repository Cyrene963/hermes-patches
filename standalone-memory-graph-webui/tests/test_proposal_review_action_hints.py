import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from api.proposal_review import _proposal_summary


def _payload(*, target_store="review", kind="procedural_memory", target_path="用户档案/程序性记忆/示例"):
    return {
        "proposal_id": "rp_test_safe_hint",
        "status": "pending",
        "candidate": {
            "kind": kind,
            "evidence_quote": "sensitive raw evidence should not leak",
            "value": "sensitive raw value should not leak",
            "subject": "Synthetic subject",
            "scope": "private",
            "confidence": 0.88,
            "risk_level": "medium",
            "requires_review": True,
            "suggested_store": target_store,
            "namespace_security_scope": "telegram:test-user",
            "target_path": target_path,
            "readback_queries": ["synthetic query"],
        },
        "decision": {
            "target_store": target_store,
            "risk_level": "medium",
            "requires_review": True,
        },
        "changeset": {"namespace": "telegram:test-user"},
    }


def test_review_procedural_candidate_gets_safe_action_hint_and_redacted_previews():
    summary = _proposal_summary(_payload())

    assert summary["action_hint_action"] == "needs_skill_or_procedural_memory_conversion"
    assert summary["action_hint_label"] == "Convert to procedural memory / skill"
    assert summary["target_store"] == "review"
    assert summary["content_preview"]["text"] == "[redacted]"
    assert summary["evidence_preview"]["text"] == "[redacted]"
    assert "sensitive raw" not in str(summary)


def test_tool_route_candidate_gets_private_route_hint():
    summary = _proposal_summary(
        _payload(kind="procedural_memory", target_path="用户档案/工具凭据查找规则/示例")
    )

    assert summary["action_hint_action"] == "needs_private_tool_route_memory_conversion"
    assert summary["action_hint_label"] == "Convert to private tool-route memory"


def test_memory_graph_candidate_is_direct_approval_review_only():
    summary = _proposal_summary(
        _payload(target_store="memory_graph", kind="user_fact", target_path="用户档案/纠错/示例")
    )

    assert summary["action_hint_action"] == "eligible_memory_graph_approval_review"
    assert summary["action_hint_label"] == "Ready for Memory Graph approval review"
