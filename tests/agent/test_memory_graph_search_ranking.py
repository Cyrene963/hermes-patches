"""Regression tests for Memory Graph search ranking policy."""

from pathlib import Path


def test_search_sql_prefers_current_namespace_before_path_bucket():
    """User-namespace results must outrank generic core path buckets when score is stronger.

    A previous ordering put path buckets (用户档案/项目/系统架构/经验教训) before
    namespace and score. That let a generic shared-core lesson outrank a freshly
    written user-namespace memory for broad/future-phrased readback queries.
    """
    source = Path("agent/memory_graph/services/search.py").read_text(encoding="utf-8")
    order_idx = source.index("ORDER BY\n                            CASE WHEN sd.path ILIKE")
    block = source[order_idx: source.index("LIMIT :candidate_limit", order_idx)]

    namespace_idx = block.index("namespace_rank ASC")
    score_idx = block.index("score DESC")
    path_bucket_idx = block.index("WHEN sd.path LIKE '用户档案%'")

    assert namespace_idx < path_bucket_idx
    assert score_idx < path_bucket_idx
