from tools.cross_domain_consistency_tool import _assess
from tools.registry import discover_builtin_tools, registry
from toolsets import resolve_toolset


def test_cross_domain_tool_registered_visible_and_executes():
    assert "tools.cross_domain_consistency_tool" in discover_builtin_tools()
    assert registry.get_entry("cross_domain_consistency_assess") is not None
    for bundle in ("hermes-cli", "hermes-telegram", "hermes-cron"):
        assert "cross_domain_consistency_assess" in resolve_toolset(bundle)
    core = ["reversible_test", "real_evidence", "bounded_investment", "explicit_criteria", "review_and_adjust"]
    result = _assess({"domains": {"academic": core, "project": core, "personal": core}})
    assert result["status"] == "consistent"
    assert result["score"] == 1


def test_cross_domain_tool_surfaces_contradiction():
    result = _assess({"domains": {"academic": ["real_evidence"], "project": ["claim_without_evidence"]}})
    assert result["status"] == "inconsistent"
