"""20+ scenario deterministic Memory OS acceptance suite.

This suite uses synthetic neutral fixtures only. It is intentionally strict about
routing, review gates, redaction metadata, and auto-write safety, but it avoids
live Memory Graph writes so it can run in CI without leaking private data.
"""

import json
from pathlib import Path

from agent.memory_semantic_classifier import classify_memory_semantics
from agent.memory_write_pipeline import CandidateFact, MemoryWritePipeline, generate_readback_queries


class FakeGraphClient:
    def __init__(self):
        self.calls = []

    def write_candidate(self, candidate, classification, readback_queries):
        self.calls.append((candidate, classification, readback_queries))
        return {
            "written": True,
            "duplicate": False,
            "readback_ok": True,
            "uri": "core://synthetic-auto-write",
            "node_uuid": "synthetic-node",
        }


def classify(text):
    return classify_memory_semantics(text).to_dict()


def test_semantic_classifier_20_plus_scenarios():
    cases = [
        ("continue", "active_workstream_context", "review", True),
        ("继续", "active_workstream_context", "review", True),
        ("go on", "active_workstream_context", "review", True),
        ("刚刚那个继续", "active_workstream_context", "review", True),
        ("这是我的 AI 项目吗？", "project_identity_verification", "review", True),
        ("把这个长期记住：以后遇到同类问题要先做 readback 验证。", "explicit_memory_request", "review", True),
        ("错错错，你应该把用户纠错抽象成 reject gate 和防复发机制。", "correction_learning_event", "memory_graph", True),
        ("有必要吗？这个过度设计，简化成通用机制。", "correction_learning_event", "memory_graph", True),
        ("我下周 DSE 考试了，这是时间表和考试范围，帮我安排复习。", "exam_context", "memory_graph", False),
        ("继续写低频心跳，别有 AI 味。", "creative_preference", "memory_graph", False),
        ("Use Claude Code; if it says not logged in, inspect safe config paths first.", "credential_route", "memory_graph", True),
        ("Use GitHub PAT lookup route; never print token values.", "credential_route", "memory_graph", True),
        ("哈哈可以", "ignore", "ignore", False),
        ("我现在困", "temporary", "ignore", False),
        ("我现在困，但以后写报告我更关心真实数据和来源，不要编造。", "user_fact", "memory_graph", False),
        ("I prefer concise answers in technical reports.", "user_fact", "memory_graph", False),
        ("用户好像喜欢短答案。", "user_fact", "memory_graph", False),
        ("{\"id\":\"case-1\",\"reason\":\"retry\",\"score\":\"85\"}", "ignore", "ignore", False),
        ("[SILENT]", "ignore", "ignore", False),
        ("[IMPORTANT: user invoked serialized-comic-adaptation skill]", "ignore", "ignore", False),
        ("项目 Alpha 现在用 PostgreSQL。", "ignore", "ignore", False),
    ]
    for text, expected_kind, expected_store, expected_review in cases:
        r = classify(text)
        assert r["memory_kind"] == expected_kind, (text, r)
        assert r["target_store"] == expected_store, (text, r)
        assert r["requires_review"] is expected_review, (text, r)
        if expected_store != "ignore":
            assert r["readback_queries"], (text, r)


def test_write_pipeline_extraction_and_auto_gate_scenarios(tmp_path):
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(
        graph_client=graph,
        config={
            "mode": "limited_auto",
            "auto_write_threshold": 0.85,
            "allowed_auto_types": ["decision", "explicit_correction", "target_function", "user_fact"],
            "never_auto_write_to_core": True,
            "repair_queue_path": str(tmp_path / "repair.jsonl"),
        },
    )

    # Review-only credential route must never auto-write even if procedural_memory were allowed elsewhere.
    reflection = pipeline.reflect_and_extract(
        "Use Claude/Codex credential route; if not logged in, inspect safe config paths without printing secrets.",
        "",
    )
    cred = next(c for c in reflection["candidates"] if c.subject == "tool_credential_route")
    cls = pipeline.classify_write(cred, namespace="tenant:a")
    res = pipeline.write_and_verify(cred, cls)
    assert cls["target_store"] == "review"
    assert res["auto_write_allowed"] is False
    assert graph.calls == []

    # Safe high-confidence non-core candidate may auto-write in limited mode.
    candidate = CandidateFact(
        subject="Project Alpha",
        predicate="decision",
        object_value="Use framework-agnostic MemoryStore interface",
        importance=0.95,
        memory_type="decision",
        target_store="memory_graph",
        target_path="projects/alpha/decisions",
        evidence_quote="Use framework-agnostic MemoryStore interface",
        confidence=0.95,
        source_type="user_direct",
        namespace="tenant:a",
    )
    cls = pipeline.classify_write(candidate, namespace="tenant:a")
    res = pipeline.write_and_verify(candidate, cls)
    assert res["auto_write_allowed"] is True
    assert res["written"] is True
    assert graph.calls

    # Same candidate in core/empty namespace must fail closed.
    graph.calls.clear()
    candidate.namespace = ""
    cls = pipeline.classify_write(candidate, namespace="")
    res = pipeline.write_and_verify(candidate, cls)
    assert res["auto_write_allowed"] is False
    assert graph.calls == []


def test_repair_queue_redacts_sensitive_review_value(tmp_path):
    pipeline = MemoryWritePipeline(config={"mode": "shadow", "repair_queue_path": str(tmp_path / "repair.jsonl")})
    sensitive_value = "synthetic credential placeholder should never be stored raw"
    candidate = CandidateFact(
        subject="tool_credential_route",
        predicate="derived_from_user_signal",
        object_value=sensitive_value,
        importance=0.95,
        memory_type="procedural_memory",
        target_store="memory_graph",
        target_path="credentials/route",
        evidence_quote=sensitive_value,
        confidence=0.95,
        source_type="user_direct",
        namespace="tenant:a",
        requires_review=True,
    )
    cls = pipeline.classify_write(candidate, namespace="tenant:a")
    res = pipeline.write_and_verify(candidate, cls)
    assert res["written"] is False
    line = (tmp_path / "repair.jsonl").read_text(encoding="utf-8")
    assert sensitive_value not in line
    item = json.loads(line)
    assert "value" not in item
    assert "evidence_quote" not in item
    assert item["raw_secret_redacted"] is False
    assert item["value_sha256"]


def test_readback_queries_are_future_usable_for_cjk_and_english():
    cjk = CandidateFact(
        subject="考试上下文",
        predicate="revision_scope",
        object_value="Math Paper 1 before mock exam",
        importance=0.9,
        memory_type="user_fact",
        target_store="memory_graph",
        target_path="profile/exam",
        evidence_quote="exam scope",
        confidence=0.9,
        source_type="user_direct",
    )
    queries = generate_readback_queries(cjk)
    assert "考试上下文revision_scope" in queries
    assert any("Math Paper" in q for q in queries)


def test_conflict_routes_to_review_and_supersede_metadata():
    pipeline = MemoryWritePipeline(config={"mode": "shadow"})
    candidate = CandidateFact(
        subject="Project Alpha",
        predicate="version",
        object_value="1.3",
        importance=0.9,
        memory_type="project_fact",
        target_store="memory_graph",
        target_path="projects/alpha",
        evidence_quote="not 1.2, 1.3",
        confidence=0.9,
        source_type="user_correction",
        namespace="tenant:a",
    )
    cls = pipeline.classify_write(candidate, existing_facts=[{"subject": "Project Alpha", "predicate": "version", "object": "1.2", "uri": "core://old"}], namespace="tenant:a")
    assert cls["action"] == "review"
    assert cls["target_store"] == "review"
    assert candidate.conflict_with == "core://old"
