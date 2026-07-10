"""Regression tests for Memory Graph search ranking policy."""

from pathlib import Path


import agent.memory_graph.services.search as search_module
from agent.memory_graph.services.search import _memory_source_rank
from agent.memory_graph.services.search_terms import expand_query_terms


def test_cross_language_query_expansion_is_generic():
    expanded = expand_query_terms("Is a localhost web app check enough for Safari compatibility?")
    for term in ("web", "safari", "公网", "真机", "真实路径"):
        assert term in expanded


def test_user_intent_prefers_private_structured_rule_over_project_and_conversation():
    query = "Where should personal preference evidence be stored?"
    private_rule = {"domain": "用户", "path": "Neutral preference rule", "namespace_rank": 0}
    project = {"domain": "项目", "path": "Neutral project", "namespace_rank": 0}
    conversation = {"domain": "core", "path": "对话记录/neutral", "namespace_rank": 0}
    assert _memory_source_rank(private_rule, query) < _memory_source_rank(project, query)
    assert _memory_source_rank(project, query) < _memory_source_rank(conversation, query)


def test_non_user_intent_does_not_special_case_user_domain():
    query = "What is the current project deployment state?"
    private_rule = {"domain": "用户", "path": "Neutral preference rule", "namespace_rank": 0}
    project = {"domain": "项目", "path": "Neutral project", "namespace_rank": 0}
    assert _memory_source_rank(private_rule, query) == _memory_source_rank(project, query)


def test_candidate_pool_supports_retrieve_then_rerank():
    source = Path(search_module.__file__).read_text(encoding="utf-8")
    assert '"candidate_limit": max(limit * 5, 100)' in source


def test_search_sql_prefers_current_namespace_before_path_bucket():
    """User-namespace results must outrank generic core path buckets when score is stronger.

    A previous ordering put path buckets (用户档案/项目/系统架构/经验教训) before
    namespace and score. That let a generic shared-core lesson outrank a freshly
    written user-namespace memory for broad/future-phrased readback queries.
    """
    source = Path(search_module.__file__).read_text(encoding="utf-8")
    order_idx = source.index("ORDER BY\n                            CASE WHEN sd.path ILIKE")
    block = source[order_idx: source.index("LIMIT :candidate_limit", order_idx)]

    namespace_idx = block.index("namespace_rank ASC")
    score_idx = block.index("score DESC")
    path_bucket_idx = block.index("WHEN sd.path LIKE '用户档案%'")

    assert namespace_idx < path_bucket_idx
    assert score_idx < path_bucket_idx
