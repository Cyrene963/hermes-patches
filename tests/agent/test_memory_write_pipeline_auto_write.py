"""Regression tests for Memory Write Pipeline auto-write gating."""

from typing import Any

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


def test_default_shadow_mode_never_writes_even_high_confidence():
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(graph_client=graph, config={"mode": "shadow"})
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
        },
    )
    candidate = make_candidate(namespace="")
    classification = pipeline.classify_write(candidate, namespace="")

    result = pipeline.write_and_verify(candidate, classification)

    assert result["auto_write_allowed"] is False
    assert result["written"] is False
    assert graph.calls == []


def test_auto_store_heuristic_adds_default_on_candidate_but_shadow_does_not_write():
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(graph_client=graph, config={"mode": "shadow"})

    reflection = pipeline.reflect_and_extract("记住我喜欢用 PostgreSQL", "好的")

    candidate = next(
        c for c in reflection["candidates"]
        if c.subject == "auto_store_heuristic"
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
        },
    )

    reflection = pipeline.reflect_and_extract("记住我喜欢用 PostgreSQL", "好的")
    candidate = next(
        c for c in reflection["candidates"]
        if c.subject == "auto_store_heuristic"
    )
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


def test_extracts_digital_stand_in_correction_as_procedural_memory_candidate():
    pipeline = MemoryWritePipeline(config={"mode": "shadow"})
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


def test_extracts_creative_target_function_from_writing_taste():
    pipeline = MemoryWritePipeline(config={"mode": "shadow"})
    reflection = pipeline.reflect_and_extract(
        "我觉得低频心跳的小说写作应该避免 AI 味，要有普通生活细节的重量和漫画质感。",
        "",
    )

    candidates = reflection["candidates"]
    assert any(c.subject == "creative_target_function" and c.memory_type == "target_function" for c in candidates)


def test_extracts_tool_credential_route_without_auto_writing_secret_route():
    graph = FakeGraphClient()
    pipeline = MemoryWritePipeline(
        graph_client=graph,
        config={
            "mode": "limited_auto",
            "auto_write_threshold": 0.85,
            "allowed_auto_types": ["procedural_memory"],
            "never_auto_write_to_core": True,
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
    assert classification["target_store"] == "review"
    assert result["auto_write_allowed"] is False
    assert graph.calls == []


def test_extracts_exam_context_for_future_recall():
    pipeline = MemoryWritePipeline(config={"mode": "shadow"})
    reflection = pipeline.reflect_and_extract(
        "我下周要考试，这是时间表和考试范围，帮我按 DSE 科目安排复习。",
        "",
    )

    candidates = reflection["candidates"]
    assert any(c.subject == "exam_context" and c.memory_type == "user_fact" for c in candidates)



def test_model_semantic_classifier_is_config_gated_shadow_only():
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
    pipeline = MemoryWritePipeline(config={"mode":"shadow", "semantic_classifier":{"model_enabled": True, "model_callable": model}})
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
