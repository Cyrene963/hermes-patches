"""Regression tests for Memory Write Pipeline auto-write gating."""

from typing import Any

import pytest

from agent.memory_clarification_queue import build_clarification_context_block
from agent.memory_write_pipeline import CandidateFact, MemoryWritePipeline


class FakeGraphClient:
    def __init__(self):
        self.calls = []

    def write_candidate(self, candidate, classification, readback_queries):
        self.calls.append((candidate, classification, readback_queries))
        return {
            "written": True,
            "duplicate": False,
            "readback_ok": True,
            "uri": "core://auto-test",
            "node_uuid": "node-auto-test",
        }


@pytest.fixture
def shadow_repair_queue_path(tmp_path):
    return tmp_path / "repair_queue.jsonl"


@pytest.fixture
def shadow_pipeline_config(shadow_repair_queue_path):
    return {"mode": "shadow", "repair_queue_path": str(shadow_repair_queue_path)}


def make_candidate(**overrides):
    data: dict[str, Any] = dict(
        subject="Project Alpha",
        predicate="decision",
        object_value="Prefer durable architecture over local hacks",
        importance=0.95,
        memory_type="decision",
        target_store="memory_graph",
        target_path="项目/Project Alpha/决策",
        evidence_quote="Use the durable architecture, not a local hack.",
        confidence=0.95,
        source_type="user_direct",
        namespace="telegram:u1",
    )
    data.update(overrides)
    return CandidateFact(**data)


def test_default_shadow_mode_never_writes_even_high_confidence(shadow_pipeline_config):
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(graph_client=graph, config=shadow_pipeline_config)
    candidate = make_candidate()
    classification = pipeline.classify_write(candidate, namespace="telegram:u1")

    result = pipeline.write_and_verify(candidate, classification)

    assert result["auto_write_allowed"] is False
    assert result["written"] is False
    assert graph.calls == []


def test_limited_auto_writes_high_confidence_user_candidate_and_verifies_readback():
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(
        graph_client=graph,
        config={
            "mode": "limited_auto",
            "auto_write_threshold": 0.85,
            "allowed_auto_types": ["decision"],
            "never_auto_write_to_core": True,
            "require_llm_classifier": False,
        },
    )
    candidate = make_candidate()
    classification = pipeline.classify_write(candidate, namespace="telegram:u1")

    result = pipeline.write_and_verify(candidate, classification)

    assert result["auto_write_allowed"] is True
    assert result["written"] is True
    assert result["readback_ok"] is True
    assert result["uri"] == "core://auto-test"
    assert len(graph.calls) == 1
    _, called_classification, readback_queries = graph.calls[0]
    assert called_classification["namespace"] == "telegram:u1"
    assert "Project Alpha decision" in readback_queries


def test_limited_auto_refuses_core_namespace_by_policy():
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(
        graph_client=graph,
        config={
            "mode": "limited_auto",
            "auto_write_threshold": 0.85,
            "allowed_auto_types": ["decision"],
            "never_auto_write_to_core": True,
            "require_llm_classifier": False,
        },
    )
    candidate = make_candidate(namespace="")
    classification = pipeline.classify_write(candidate, namespace="")

    result = pipeline.write_and_verify(candidate, classification)

    assert result["auto_write_allowed"] is False
    assert result["written"] is False
    assert graph.calls == []


def test_auto_store_heuristic_adds_default_on_candidate_but_shadow_does_not_write(shadow_pipeline_config):
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(graph_client=graph, config=shadow_pipeline_config)

    reflection = pipeline.reflect_and_extract("记住我喜欢用 PostgreSQL", "好的")

    candidate = next(
        c for c in reflection["candidates"]
        if c.memory_type == "preference" and c.target_store == "memory_graph"
    )
    assert candidate.memory_type == "preference"
    assert candidate.target_store == "memory_graph"
    assert candidate.source_type == "user_direct"
    classification = pipeline.classify_write(candidate, namespace="telegram:u1")
    result = pipeline.write_and_verify(candidate, classification)
    assert result["auto_write_allowed"] is False
    assert result["written"] is False
    assert graph.calls == []


def test_auto_store_heuristic_preference_can_write_through_limited_auto_gate():
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(
        graph_client=graph,
        config={
            "mode": "limited_auto",
            "auto_write_threshold": 0.85,
            "allowed_auto_types": ["explicit_preference"],
            "never_auto_write_to_core": True,
            "require_llm_classifier": False,
        },
    )

    reflection = pipeline.reflect_and_extract("记住我喜欢用 PostgreSQL", "好的")
    candidate = next(
        c for c in reflection["candidates"]
        if c.memory_type == "preference" and c.target_store == "memory_graph"
    )
    candidate.requires_review = False
    candidate.llm_durable = True
    classification = pipeline.classify_write(candidate, namespace="telegram:u1")
    result = pipeline.write_and_verify(candidate, classification)

    assert result["auto_write_allowed"] is True
    assert result["written"] is True
    assert result["readback_ok"] is True
    assert len(graph.calls) == 1


def test_user_correction_maps_to_explicit_correction_policy_type():
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(
        graph_client=graph,
        config={
            "mode": "limited_auto",
            "auto_write_threshold": 0.85,
            "allowed_auto_types": ["explicit_correction"],
            "never_auto_write_to_core": True,
            "require_llm_classifier": False,
        },
    )
    candidate = make_candidate(
        source_type="user_correction",
        memory_type="user_fact",
        predicate="correction",
        object_value="Not version 1.2, version 1.3",
    )
    classification = pipeline.classify_write(candidate, namespace="telegram:u1")

    result = pipeline.write_and_verify(candidate, classification)

    assert result["auto_write_allowed"] is True
    assert result["written"] is True
    assert len(graph.calls) == 1


def test_extracts_digital_stand_in_correction_as_procedural_memory_candidate(shadow_pipeline_config):
    pipeline = MemoryWritePipeline(config=shadow_pipeline_config)
    reflection = pipeline.reflect_and_extract(
        "你又没主动存，太气人了。以后我纠正你错误时要先调查根因，再抽象通用防复发机制。",
        "",
    )

    candidates = reflection["candidates"]
    assert any(c.subject == "agent_memory_workflow" and c.memory_type == "procedural_memory" for c in candidates)
    c = next(c for c in candidates if c.subject == "agent_memory_workflow")
    assert c.importance >= 0.95
    assert c.source_type == "user_correction"
    assert "程序性记忆" in c.target_path


def test_extracts_creative_target_function_from_writing_taste(shadow_pipeline_config):
    pipeline = MemoryWritePipeline(config=shadow_pipeline_config)
    reflection = pipeline.reflect_and_extract(
        "我觉得低频心跳的小说写作应该避免 AI 味，要有普通生活细节的重量和漫画质感。",
        "",
    )

    candidates = reflection["candidates"]
    assert any(c.subject == "creative_target_function" and c.memory_type == "target_function" for c in candidates)


def test_extracts_tool_credential_route_without_auto_writing_secret_route(tmp_path):
    graph = FakeGraphClient()
    queue_path = tmp_path / "clarification.jsonl"
    pipeline = MemoryWritePipeline(
        graph_client=graph,
        config={
            "mode": "limited_auto",
            "auto_write_threshold": 0.85,
            "allowed_auto_types": ["procedural_memory"],
            "never_auto_write_to_core": True,
            "require_llm_classifier": False,
            "clarification_queue_path": str(queue_path),
        },
    )
    reflection = pipeline.reflect_and_extract(
        "以后需要 Claude Code 审计时可以用 Claude，not logged in 时先查已有配置和凭据路径。",
        "",
    )

    c = next(c for c in reflection["candidates"] if c.subject == "tool_credential_route")
    classification = pipeline.classify_write(c, namespace="telegram:u1")
    result = pipeline.write_and_verify(c, classification)

    assert c.requires_review is True
    assert classification["target_store"] == "clarification"
    assert result["auto_write_allowed"] is False
    assert result["queued_for_clarification"] is True
    assert graph.calls == []


def test_extracts_exam_context_for_future_recall(shadow_pipeline_config):
    pipeline = MemoryWritePipeline(config=shadow_pipeline_config)
    reflection = pipeline.reflect_and_extract(
        "我下周要考试，这是时间表和考试范围，帮我按 DSE 科目安排复习。",
        "",
    )

    candidates = reflection["candidates"]
    assert any(c.subject == "exam_context" and c.memory_type == "user_fact" for c in candidates)



def test_model_semantic_classifier_is_config_gated_shadow_only(shadow_pipeline_config):
    def model(_prompt):
        return {
            'memory_kind': 'creative_preference',
            'durability': 'long_term',
            'confidence': 0.96,
            'evidence_quote': 'Prefer vivid human prose',
            'target_store': 'memory_graph',
            'target_path': 'profile/creative',
            'requires_review': False,
            'privacy_scope': 'user_private',
            'readback_queries': ['future creative prose preference'],
            'reject_gate': 'Reject generic prose.',
            'reason': 'explicit preference',
        }
    pipeline = MemoryWritePipeline(config={**shadow_pipeline_config, "semantic_classifier":{"model_enabled": True, "model_callable": model}})
    reflection = pipeline.reflect_and_extract('Any multilingual phrasing should use the model path.', '')
    assert any(c.subject == 'creative_target_function' for c in reflection['candidates'])
    c = next(c for c in reflection['candidates'] if c.subject == 'creative_target_function')
    cls = pipeline.classify_write(c, namespace='telegram:u1')
    result = pipeline.write_and_verify(c, cls)
    assert result['auto_write_allowed'] is False
    assert result['written'] is False


def test_model_semantic_classifier_disabled_does_not_call_model():
    called = {'n': 0}
    def model(_prompt):
        called['n'] += 1
        return {'memory_kind':'user_fact'}
    pipeline = MemoryWritePipeline(config={"mode":"shadow", "semantic_classifier":{"model_enabled": False, "model_callable": model}})
    pipeline.reflect_and_extract('哈哈可以', '')
    assert called['n'] == 0


def test_high_confidence_target_function_auto_writes_without_batch_review():
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(
        graph_client=graph,
        config={
            "mode": "limited_auto",
            "auto_write_threshold": 0.85,
            "allowed_auto_types": ["target_function"],
            "never_auto_write_to_core": True,
            "require_llm_classifier": False,
        },
    )
    candidate = make_candidate(
        subject="creative_target_function",
        predicate="semantic_signal",
        object_value="User explicitly wants fiction to avoid AI-ish generic prose and preserve manga-like realism.",
        memory_type="target_function",
        target_path="用户档案/目标函数",
        source_type="user_direct",
        confidence=0.96,
        importance=0.96,
    )

    classification = pipeline.classify_write(candidate, namespace="telegram:u1")
    result = pipeline.write_and_verify(candidate, classification)

    assert classification["target_store"] == "memory_graph"
    assert result["auto_write_allowed"] is True
    assert result["written"] is True
    assert graph.calls


def test_clarification_queue_surfaces_only_when_relevant(tmp_path):
    queue_path = tmp_path / "clarification.jsonl"
    pipeline = MemoryWritePipeline(
        config={
            "mode": "limited_auto",
            "clarification_queue_path": str(queue_path),
        },
    )
    candidate = make_candidate(
        subject="tool_credential_route",
        predicate="semantic_signal",
        object_value="Claude Code credential route may already exist in config and should be checked before claiming unavailable.",
        memory_type="procedural_memory",
        target_path="用户档案/工具凭据查找规则",
        source_type="user_direct",
        requires_review=True,
        confidence=0.90,
        importance=0.90,
    )
    classification = pipeline.classify_write(candidate, namespace="telegram:u1")
    result = pipeline.write_and_verify(candidate, classification)

    assert result["queued_for_clarification"] is True
    unrelated = build_clarification_context_block("帮我写一段中史答题框架", queue_path=str(queue_path))
    relevant = build_clarification_context_block("Claude Code not logged in 怎么查凭据", queue_path=str(queue_path))

    assert unrelated == ""
    assert "Memory Clarification Candidates" in relevant
    assert "tool_credential_route" in relevant
    assert "ask the user" in relevant


def test_meta_memory_assessment_question_is_rejected_by_quality_gate():
    pipeline = MemoryWritePipeline(
        graph_client=FakeGraphClient(),
        config={
            "mode": "limited_auto",
            "allowed_auto_types": ["procedural_memory"],
            "auto_write_threshold": 0.85,
        },
    )
    candidate = make_candidate(
        subject="agent_memory_workflow",
        predicate="derived_from_user_signal",
        object_value="也就是说，单论补丁项目的记忆系统来讲，已经是99%的数字替身和外置大脑了？",
        source_type="user_correction",
        memory_type="procedural_memory",
        importance=0.95,
        confidence=0.9,
    )

    classification = pipeline.classify_write(candidate, namespace="telegram:test-user")

    assert classification["action"] == "ignore"
    assert classification["reason"] == "meta_memory_assessment_question_not_a_durable_fact"


def test_real_agent_memory_correction_still_passes_quality_gate():
    pipeline = MemoryWritePipeline(
        graph_client=FakeGraphClient(),
        config={
            "mode": "limited_auto",
            "allowed_auto_types": ["procedural_memory"],
            "auto_write_threshold": 0.85,
            "never_auto_write_to_core": True,
            "require_llm_classifier": False,
        },
    )
    candidate = make_candidate(
        subject="agent_memory_workflow",
        predicate="derived_from_user_signal",
        object_value="用户纠错后必须抽象成通用防复发方案，并在未来相关任务前主动召回。",
        source_type="user_correction",
        memory_type="procedural_memory",
        importance=0.95,
        confidence=0.9,
    )

    classification = pipeline.classify_write(candidate, namespace="telegram:test-user")

    assert classification["action"] == "write"
