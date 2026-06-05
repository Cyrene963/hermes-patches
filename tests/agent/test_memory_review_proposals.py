"""Tests for generic Memory OS review proposals generated from shadow candidates."""

from dataclasses import asdict

from agent.memory_review_proposals import (
    build_shadow_report,
    make_review_proposal,
    proposals_from_shadow,
)
from agent.memory_write_pipeline import MemoryWritePipeline


def _entry(candidate):
    return {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "conversation_id": "session-neutral",
        "user_id": "user-neutral",
        "namespace": "tenant:user-neutral",
        "user_message": "This memory architecture must remain open-source generic, not private special-casing.",
        "candidate_writes": [candidate],
    }


def test_shadow_report_groups_required_dimensions():
    entry = _entry({
        "memory_type": "target_function",
        "importance_score": 0.92,
        "target_store": "review",
        "subject": "memory_architecture_standard",
        "predicate": "semantic_signal",
        "object": "Memory architecture must remain generic and open-source safe.",
        "requires_review": True,
        "failure_reason": "auto-write gate rejected candidate",
        "actually_written": False,
        "readback_queries": ["memory architecture generic open-source"],
    })

    report = build_shadow_report([entry])

    assert report["entries"] == 1
    assert report["candidates"] == 1
    assert report["by_would_review"]["true"] == 1
    assert report["by_actually_written"]["false"] == 1
    assert report["by_failure_reason"]["auto-write gate rejected candidate"] == 1
    assert report["by_target_store"]["review"] == 1
    assert report["by_subject_kind"]["memory_architecture_standard::target_function"] == 1
    assert report["by_namespace"]["tenant:user-neutral"] == 1


def test_recent_style_open_source_generic_event_becomes_review_proposal_not_private_rule():
    pipeline = MemoryWritePipeline(config={"mode": "shadow", "semantic_classifier": {"model_enabled": False}})
    reflection = pipeline.reflect_and_extract(
        "This memory architecture must remain open-source generic, not private special-casing.",
        "Acknowledged.",
    )

    candidates = reflection["candidates"]
    assert candidates, "recent-style architecture rule should not be ignored"
    candidate = candidates[0]
    classification = pipeline.classify_write(candidate, namespace="tenant:user-neutral")
    write_result = pipeline.write_and_verify(candidate, classification)
    raw = {
        "memory_type": candidate.memory_type,
        "importance_score": candidate.importance,
        "target_store": classification.get("target_store", candidate.target_store),
        "target_path": classification.get("target_path", candidate.target_path),
        "subject": candidate.subject,
        "predicate": candidate.predicate,
        "object": candidate.object_value,
        "requires_review": candidate.requires_review or classification.get("requires_review", False),
        "reason": candidate.reason or classification.get("reason", ""),
        "actually_written": write_result.get("written", False),
        "readback_ok": write_result.get("readback_ok", False),
        "readback_queries": write_result.get("readback_queries", []),
        "failure_reason": write_result.get("failure_reason", ""),
    }

    proposal = make_review_proposal(_entry(raw), raw)
    payload = asdict(proposal)

    assert proposal.decision.action == "review"
    assert proposal.candidate.kind in {"target_function", "rule", "procedural_memory"}
    assert proposal.candidate.requires_review is True
    assert "generic" in proposal.candidate.content.lower() or "open-source" in proposal.candidate.content.lower()
    assert proposal.candidate.namespace_security_scope == "tenant:user-neutral"
    assert proposal.changeset.operation_type == "propose_write"
    assert proposal.readback.queries
    # Public/generic contract: no local deployment paths, chat IDs, or private names in proposal schema output.
    serialized = str(payload)
    forbidden = [
        "/" + "root" + "/" + ".hermes",
        "tele" + "gram:",
        "Cy" + "rene",
        "Ste" + "ven",
        "bei" + "bei",
        "Focus" + "Pomo",
    ]
    assert not any(marker in serialized for marker in forbidden)


def test_proposals_from_shadow_filters_high_value_pending_reviews():
    candidate = {
        "memory_type": "procedural_memory",
        "importance_score": 0.95,
        "target_store": "review",
        "subject": "reviewable_standard",
        "predicate": "semantic_signal",
        "object": "Review risky durable learning before storing.",
        "requires_review": True,
        "actually_written": False,
        "readback_queries": ["review risky durable learning"],
    }
    proposals = proposals_from_shadow([_entry(candidate)])
    assert len(proposals) == 1
    assert proposals[0].status == "pending"
    assert proposals[0].changeset.rollback_method
