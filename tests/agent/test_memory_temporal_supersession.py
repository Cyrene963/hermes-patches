from agent.memory_write_pipeline import CandidateFact, MemoryWritePipeline


class FakeVersioningGraph:
    def __init__(self, *, stale=False, snippet_shape=False):
        self.calls = []
        self.stale = stale
        self.snippet_shape = snippet_shape

    def supersede_candidate(self, candidate, classification):
        self.calls.append((candidate, classification))
        uri = classification["conflict_with"]
        new_content = f"Value: {candidate.object_value}"
        old_content = "Value: 1.2"
        key = "snippet" if self.snippet_shape else "content"
        return {
            "updated": True,
            "uri": uri,
            "memory_id": 2,
            "old_content": old_content,
            "current_content": old_content if self.stale else new_content,
            "new_results": [{"uri": uri, key: new_content}],
            "old_results": [{"uri": uri, key: old_content if self.stale else new_content}],
        }


def candidate(**overrides):
    values = dict(
        subject="Project Alpha",
        predicate="version",
        object_value="1.3",
        importance=0.95,
        memory_type="project_fact",
        target_store="memory_graph",
        target_path="projects/alpha",
        evidence_quote="not 1.2, use 1.3",
        confidence=0.95,
        source_type="user_correction",
        namespace="tenant:a",
    )
    values.update(overrides)
    return CandidateFact(**values)


def old_fact():
    return [{
        "subject": "Project Alpha",
        "predicate": "version",
        "object": "1.2",
        "uri": "core://projects/alpha",
    }]


def config(mode="limited_auto", repair_queue_path=None):
    out = {
        "mode": mode,
        "auto_write_threshold": 0.85,
        "auto_supersede_user_corrections": True,
        "require_llm_classifier": False,
    }
    if repair_queue_path:
        out["repair_queue_path"] = str(repair_queue_path)
    return out


def test_explicit_correction_supersedes_and_verifies_top1():
    graph = FakeVersioningGraph()
    pipe = MemoryWritePipeline(graph_client=graph, config=config())
    item = candidate()
    classification = pipe.classify_write(item, existing_facts=old_fact(), namespace="tenant:a")
    result = pipe.write_and_verify(item, classification)

    assert classification["action"] == "supersede"
    assert result["written"] is True
    assert result["readback_ok"] is True
    assert result["old_top1_stale"] is False
    assert len(graph.calls) == 1


def test_search_indexer_snippet_shape_verifies_top1():
    graph = FakeVersioningGraph(snippet_shape=True)
    pipe = MemoryWritePipeline(graph_client=graph, config=config())
    item = candidate()
    classification = pipe.classify_write(item, existing_facts=old_fact(), namespace="tenant:a")
    result = pipe.write_and_verify(item, classification)
    assert result["readback_ok"] is True
    assert result["old_top1_stale"] is False


def test_shadow_noncorrection_and_empty_namespace_still_review():
    cases = [
        (candidate(), config("shadow"), "tenant:a"),
        (candidate(source_type="user_direct"), config(), "tenant:a"),
        (candidate(namespace=""), config(), ""),
    ]
    for item, cfg, namespace in cases:
        pipe = MemoryWritePipeline(graph_client=FakeVersioningGraph(), config=cfg)
        classification = pipe.classify_write(item, existing_facts=old_fact(), namespace=namespace)
        assert classification["action"] in {"review", "ignore"}
        assert classification.get("action") != "supersede"
        assert classification.get("target_store") in {"review", "ignore"}


def test_stale_top1_fails_closed_and_records_repair(tmp_path):
    queue = tmp_path / "repair.jsonl"
    graph = FakeVersioningGraph(stale=True)
    pipe = MemoryWritePipeline(graph_client=graph, config=config(repair_queue_path=queue))
    item = candidate()
    classification = pipe.classify_write(item, existing_facts=old_fact(), namespace="tenant:a")
    result = pipe.write_and_verify(item, classification)

    assert result["written"] is True
    assert result["readback_ok"] is False
    assert result["old_top1_stale"] is True
    assert "temporal top-1" in result["failure_reason"]
    assert queue.exists()
