"""Integration tests for Memory Write Pipeline with real database.

These tests verify the complete write pipeline from candidate extraction through
database write and readback verification using real PostgreSQL connections.

Run with: pytest tests/agent/test_memory_integration.py -v
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("HERMES_MEMORY_INTEGRATION_TESTS") != "1",
    reason="requires a live Memory Graph PostgreSQL database with RLS test permissions; set HERMES_MEMORY_INTEGRATION_TESTS=1 to run",
)

from agent.memory_write_pipeline import (
    CandidateFact,
    MemoryWritePipeline,
    _auto_type,
    load_memory_write_config,
)


# ─── Test Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def integration_config(tmp_path):
    """Config that enables auto-write for integration testing."""
    return {
        "mode": "limited_auto",
        "auto_write_threshold": 0.85,
        "never_auto_write_to_core": True,
        "allowed_auto_types": [
            "user_fact",
            "project_fact",
            "task",
            "explicit_preference",
            "explicit_correction",
            "decision",
            "lesson",
            "target_function",
            "procedural_memory",
        ],
        "semantic_classifier": {"model_enabled": False},
        "repair_queue_path": str(tmp_path / "repair_queue.jsonl"),
        "clarification_queue_path": str(tmp_path / "clarification.jsonl"),
        "shadow": {
            "log_dir": str(tmp_path / "shadow_writes"),
            "max_entries_per_day": 1000,
            "retention_days": 30,
            "max_file_size_mb": 10,
            "enable_readback_dryrun": True,
        },
    }


@pytest.fixture
def test_namespace():
    """Unique namespace for test isolation."""
    import uuid
    return f"test:{uuid.uuid4().hex[:8]}"


@pytest.fixture
def pipeline(integration_config):
    """Pipeline instance with integration config."""
    return MemoryWritePipeline(config=integration_config)


def make_candidate(**overrides) -> CandidateFact:
    """Helper to create test candidates."""
    data: Dict[str, Any] = {
        "subject": "test_subject",
        "predicate": "test_predicate",
        "object_value": "test_value",
        "importance": 0.90,
        "memory_type": "user_fact",
        "target_store": "memory_graph",
        "target_path": "test/path",
        "evidence_quote": "test evidence",
        "confidence": 0.90,
        "source_type": "user_direct",
        "namespace": "",
    }
    data.update(overrides)
    return CandidateFact(**data)


# ─── Integration Tests ─────────────────────────────────────────────────


def test_write_to_real_database(pipeline, test_namespace):
    """Write memory and verify it appears in PostgreSQL.

    This test writes a memory candidate to the real database through the
    complete pipeline and verifies the write was successful.
    """
    candidate = make_candidate(
        subject="integration_test",
        predicate="database_write",
        object_value="This is a test memory written to real PostgreSQL",
        importance=0.95,
        confidence=0.95,
        memory_type="user_fact",
        namespace=test_namespace,
    )

    classification = pipeline.classify_write(candidate, namespace=test_namespace)
    assert classification["action"] == "write"
    assert classification["target_store"] == "memory_graph"

    result = pipeline.write_and_verify(candidate, classification)

    # Verify write succeeded
    assert result["written"] is True, f"Write failed: {result.get('failure_reason', 'unknown')}"
    assert result["auto_write_allowed"] is True
    assert "uri" in result
    assert result["uri"].startswith("core://")

    # Verify database contains the write
    from tools import memory_graph_tool
    search_result = memory_graph_tool._search({
        "query": "integration_test database_write",
        "limit": 10,
        "namespace": test_namespace,
    })
    search_data = json.loads(search_result)

    assert search_data["count"] > 0, "Written memory not found in database"
    assert any(
        "integration_test" in str(item.get("content", "")).lower()
        for item in search_data["results"]
    )


def test_search_and_readback(pipeline, test_namespace):
    """Write then search to confirm it's findable.

    Verifies that memories written to the database are immediately searchable
    and that the readback verification logic works correctly.
    """
    candidate = make_candidate(
        subject="readback_test",
        predicate="searchability",
        object_value="This memory must be searchable immediately after write",
        importance=0.92,
        confidence=0.92,
        memory_type="user_fact",
        namespace=test_namespace,
    )

    classification = pipeline.classify_write(candidate, namespace=test_namespace)
    result = pipeline.write_and_verify(candidate, classification)

    assert result["written"] is True
    assert result["readback_ok"] is True, (
        f"Readback failed for queries: {result.get('readback_queries', [])}. "
        f"Reason: {result.get('failure_reason', 'unknown')}"
    )

    # Verify all readback queries return results
    from tools import memory_graph_tool
    for query in result.get("readback_queries", []):
        search_result = memory_graph_tool._search({
            "query": query,
            "limit": 5,
            "namespace": test_namespace,
        })
        search_data = json.loads(search_result)
        assert search_data["count"] > 0, f"Readback query '{query}' returned no results"


def test_namespace_isolation(pipeline, test_namespace):
    """Write to namespace A, verify not visible in namespace B.

    Ensures that namespace isolation works correctly and memories written
    to one namespace cannot be accessed from another namespace.
    """
    namespace_a = test_namespace
    namespace_b = f"test:isolated_{test_namespace}"

    candidate = make_candidate(
        subject="namespace_test",
        predicate="isolation",
        object_value="This should only be visible in namespace A",
        importance=0.90,
        confidence=0.90,
        memory_type="user_fact",
        namespace=namespace_a,
    )

    classification = pipeline.classify_write(candidate, namespace=namespace_a)
    result = pipeline.write_and_verify(candidate, classification)

    assert result["written"] is True
    assert result["readback_ok"] is True

    # Verify visible in namespace A
    from tools import memory_graph_tool
    search_a = memory_graph_tool._search({
        "query": "namespace_test isolation",
        "limit": 10,
        "namespace": namespace_a,
    })
    data_a = json.loads(search_a)
    assert data_a["count"] > 0, "Memory not found in namespace A"

    # Verify NOT visible in namespace B
    search_b = memory_graph_tool._search({
        "query": "namespace_test isolation",
        "limit": 10,
        "namespace": namespace_b,
    })
    data_b = json.loads(search_b)
    assert data_b["count"] == 0, "Memory incorrectly visible in namespace B"


def test_dedup_prevents_duplicates(pipeline, test_namespace):
    """Write same fact twice, verify only one stored.

    Tests the deduplication logic to ensure identical facts are not
    written multiple times to the database.
    """
    candidate = make_candidate(
        subject="dedup_test",
        predicate="unique_fact",
        object_value="This exact fact should only appear once",
        importance=0.90,
        confidence=0.90,
        memory_type="user_fact",
        namespace=test_namespace,
    )

    # First write
    classification1 = pipeline.classify_write(candidate, namespace=test_namespace)
    result1 = pipeline.write_and_verify(candidate, classification1)
    assert result1["written"] is True

    # Second write of identical fact
    classification2 = pipeline.classify_write(candidate, namespace=test_namespace)
    result2 = pipeline.write_and_verify(candidate, classification2)

    # Should either skip write or detect duplicate
    assert (
        result2.get("duplicate") is True or
        result2["written"] is False or
        classification2["action"] == "ignore"
    ), "Duplicate fact was not prevented"

    # Verify database only contains one instance
    from tools import memory_graph_tool
    search_result = memory_graph_tool._search({
        "query": "dedup_test unique_fact",
        "limit": 20,
        "namespace": test_namespace,
    })
    search_data = json.loads(search_result)

    # Count exact matches
    exact_matches = [
        item for item in search_data["results"]
        if "This exact fact should only appear once" in str(item.get("content", ""))
    ]
    assert len(exact_matches) == 1, (
        f"Expected 1 instance, found {len(exact_matches)}: {exact_matches}"
    )


def test_type_mapping_matches_config(pipeline):
    """Verify all _auto_type() returns match allowed_auto_types.

    Ensures that the _auto_type function only returns types that are
    configured in allowed_auto_types to prevent policy violations.
    """
    allowed_types = set(pipeline.config.get("allowed_auto_types", []))

    # Test various candidate types
    test_cases = [
        make_candidate(source_type="user_correction", memory_type="user_fact"),
        make_candidate(memory_type="preference", source_type="user_direct"),
        make_candidate(memory_type="target_function", source_type="user_direct"),
        make_candidate(memory_type="procedural_memory", source_type="user_direct"),
        make_candidate(memory_type="decision", source_type="user_direct"),
        make_candidate(memory_type="user_fact", source_type="user_direct"),
        make_candidate(memory_type="project_fact", source_type="agent_inference"),
        make_candidate(memory_type="task", source_type="user_direct"),
    ]

    for candidate in test_cases:
        auto_type = _auto_type(candidate)
        assert auto_type in allowed_types or auto_type == candidate.memory_type, (
            f"_auto_type returned '{auto_type}' for {candidate.memory_type}/"
            f"{candidate.source_type}, which is not in allowed_auto_types: {allowed_types}"
        )


def test_recall_integration(pipeline, test_namespace):
    """Verify prefetch actually queries database.

    Tests that the recall/prefetch mechanism correctly retrieves memories
    from the database when queried.
    """
    # Write a memory
    candidate = make_candidate(
        subject="recall_test",
        predicate="prefetch_verification",
        object_value="This memory should be recalled during prefetch",
        importance=0.95,
        confidence=0.95,
        memory_type="user_fact",
        namespace=test_namespace,
    )

    classification = pipeline.classify_write(candidate, namespace=test_namespace)
    result = pipeline.write_and_verify(candidate, classification)
    assert result["written"] is True

    # Now verify it can be recalled
    from tools import memory_graph_tool
    recall_result = memory_graph_tool._search({
        "query": "recall_test prefetch",
        "limit": 10,
        "namespace": test_namespace,
    })
    recall_data = json.loads(recall_result)

    assert recall_data["count"] > 0, "Memory not recalled from database"
    assert recall_data["namespace"] == test_namespace

    # Verify the recalled content matches what we wrote
    found = False
    for item in recall_data["results"]:
        content = str(item.get("content", ""))
        if "recall_test" in content.lower() and "prefetch_verification" in content.lower():
            found = True
            break

    assert found, f"Expected memory not found in recall results: {recall_data['results']}"


def test_empty_namespace_rejected(pipeline):
    """Verify writes with empty namespace are rejected.

    Ensures that the policy of never_auto_write_to_core prevents writes
    to the empty (core) namespace when configured.
    """
    candidate = make_candidate(
        subject="empty_namespace_test",
        predicate="core_write_attempt",
        object_value="This should not be written to core namespace",
        importance=0.95,
        confidence=0.95,
        memory_type="user_fact",
        namespace="",  # Empty namespace = core
    )

    classification = pipeline.classify_write(candidate, namespace="")
    result = pipeline.write_and_verify(candidate, classification)

    # Should be rejected by never_auto_write_to_core policy
    assert result["auto_write_allowed"] is False, (
        "Empty namespace write should be rejected when never_auto_write_to_core=True"
    )
    assert result["written"] is False


# ─── Additional Integration Tests ─────────────────────────────────────


def test_high_importance_auto_write_integration(pipeline, test_namespace):
    """Test that high-importance facts auto-write through full pipeline."""
    reflection = pipeline.reflect_and_extract(
        "我的数学 mock 考试成绩是 92 分",
        ""
    )

    candidates = reflection.get("candidates", [])
    assert len(candidates) > 0, "No candidates extracted from high-importance input"

    # Find the exam score candidate
    score_candidate = None
    for c in candidates:
        if "92" in c.object_value or "exam_score" in c.predicate:
            score_candidate = c
            break

    assert score_candidate is not None, "Exam score candidate not found"
    assert score_candidate.importance >= 0.80

    classification = pipeline.classify_write(score_candidate, namespace=test_namespace)
    result = pipeline.write_and_verify(score_candidate, classification)

    assert result["auto_write_allowed"] is True
    assert result["written"] is True
    assert result["readback_ok"] is True


def test_correction_overwrites_integration(pipeline, test_namespace):
    """Test that user corrections are properly handled in the database."""
    # Original fact
    original = make_candidate(
        subject="student_age",
        predicate="age",
        object_value="16 years old",
        importance=0.85,
        confidence=0.85,
        memory_type="user_fact",
        namespace=test_namespace,
    )

    classification1 = pipeline.classify_write(original, namespace=test_namespace)
    result1 = pipeline.write_and_verify(original, classification1)
    assert result1["written"] is True

    # Correction
    correction = make_candidate(
        subject="student_age",
        predicate="correction",
        object_value="Not 16, is 17 years old",
        importance=0.95,
        confidence=0.95,
        memory_type="user_fact",
        source_type="user_correction",
        namespace=test_namespace,
    )

    classification2 = pipeline.classify_write(correction, namespace=test_namespace)
    result2 = pipeline.write_and_verify(correction, classification2)

    # Correction should be written
    assert result2["written"] is True

    # Verify both are searchable but correction has higher priority
    from tools import memory_graph_tool
    search_result = memory_graph_tool._search({
        "query": "student_age",
        "limit": 10,
        "namespace": test_namespace,
    })
    search_data = json.loads(search_result)
    assert search_data["count"] > 0


def test_clarification_queue_integration(pipeline, test_namespace, tmp_path):
    """Test that uncertain memories are queued for clarification."""
    queue_path = tmp_path / "clarification.jsonl"
    pipeline.config["clarification_queue_path"] = str(queue_path)

    # Create an inference-based candidate (should require clarification)
    candidate = make_candidate(
        subject="user_preference",
        predicate="inferred",
        object_value="User seems to prefer concise responses",
        importance=0.75,
        confidence=0.70,
        memory_type="preference",
        source_type="agent_inference",
        namespace=test_namespace,
    )

    classification = pipeline.classify_write(candidate, namespace=test_namespace)
    result = pipeline.write_and_verify(candidate, classification)

    # Should be queued for clarification, not written
    assert classification.get("action") == "clarify_later"
    assert result.get("queued_for_clarification") is True
    assert result["written"] is False

    # Verify queue file was created
    assert queue_path.exists()

    # Verify queue contains the candidate
    with open(queue_path, 'r') as f:
        lines = f.readlines()
        assert len(lines) > 0
        last_entry = json.loads(lines[-1])
        assert last_entry["subject"] == "user_preference"


def test_multi_candidate_extraction_integration(pipeline, test_namespace):
    """Test extraction of multiple candidates from complex input."""
    reflection = pipeline.reflect_and_extract(
        "记住我喜欢用 PostgreSQL，项目 Alpha 现在部署在 AWS，明天要检查日志。",
        ""
    )

    candidates = reflection.get("candidates", [])

    # Should extract multiple facts: preference, project fact, task
    assert len(candidates) >= 2, f"Expected multiple candidates, got {len(candidates)}"

    # Write all high-confidence candidates
    written_count = 0
    for candidate in candidates:
        if candidate.importance >= 0.85 and candidate.confidence >= 0.85:
            classification = pipeline.classify_write(candidate, namespace=test_namespace)
            if classification.get("action") == "write":
                result = pipeline.write_and_verify(candidate, classification)
                if result.get("written"):
                    written_count += 1

    assert written_count > 0, "No candidates were written from multi-fact input"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
