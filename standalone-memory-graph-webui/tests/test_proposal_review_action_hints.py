import asyncio
import pathlib
import sys
from unittest.mock import Mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from api.proposal_review import _proposal_summary, _review_stage, _verify_readback


def _payload(*, target_store="review", kind="procedural_memory", target_path="用户档案/程序性记忆/示例", distilled=False, source="test"):
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
            "distilled": distilled,
            "source": source,
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


def test_memory_graph_raw_excerpt_requires_distillation_even_if_target_store_says_memory_graph():
    payload = _payload(target_store="memory_graph", kind="user_fact", target_path="用户档案/纠错/示例", source="state_db_message")
    summary = _proposal_summary(payload)

    assert _review_stage(payload) == "raw_material"
    assert summary["review_stage"] == "raw_material"
    assert summary["action_hint_action"] == "needs_distillation"
    assert summary["action_hint_label"] == "Needs distillation before memory write"


def test_distilled_memory_graph_candidate_is_direct_approval_review_only():
    payload = _payload(
        target_store="memory_graph",
        kind="user_fact",
        target_path="用户档案/纠错/示例",
        distilled=True,
    )
    summary = _proposal_summary(payload)

    assert _review_stage(payload) == "ready_memory"
    assert summary["review_stage"] == "ready_memory"
    assert summary["action_hint_action"] == "eligible_memory_graph_approval_review"
    assert summary["action_hint_label"] == "Ready for Memory Graph approval review"


def test_owner_or_admin_can_see_preview_for_review_decision():
    summary = _proposal_summary(
        _payload(target_store="memory_graph", kind="user_fact", target_path="用户档案/纠错/示例"),
        user={"username": "reviewer", "namespace": "telegram:test-user", "role": "user"},
    )

    assert summary["content_preview"]["redacted"] is False
    assert summary["evidence_preview"]["redacted"] is False
    assert "sensitive raw value" in summary["content_preview"]["text"]
    assert "sensitive raw evidence" in summary["evidence_preview"]["text"]


def test_readback_accepts_at_least_one_successful_search_query(monkeypatch):
    class FakeGraph:
        async def get_memory_by_path(self, path, domain, namespace):
            assert path == "用户档案/示例"
            assert domain == "core"
            assert namespace == "telegram:test-user"
            return {"content": "durable memory content"}

    class FakeSearch:
        async def search(self, query, limit, domain, namespace):
            if query == "strong unique query":
                return [{"uri": "core://用户档案/示例"}]
            return []

    monkeypatch.setattr("api.proposal_review.get_graph_service", Mock(return_value=FakeGraph()))
    monkeypatch.setattr("api.proposal_review.get_search_indexer", Mock(return_value=FakeSearch()))

    result = asyncio.run(
        _verify_readback(
            "telegram:test-user",
            "core",
            "core://用户档案/示例",
            "durable memory content",
            ["strong unique query", "overly broad query"],
        )
    )

    assert result["read_ok"] is True
    assert result["search_ok"] is True
    assert [check["found"] for check in result["checks"]] == [True, False]
