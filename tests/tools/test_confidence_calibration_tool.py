from tools.confidence_calibration_tool import _calibrate
from tools.registry import discover_builtin_tools, registry
from toolsets import resolve_toolset


def test_confidence_tool_registered_visible_and_executes():
    assert "tools.confidence_calibration_tool" in discover_builtin_tools()
    entry = registry.get_entry("confidence_calibrate")
    assert entry is not None
    for bundle in ("hermes-cli", "hermes-telegram", "hermes-cron"):
        assert "confidence_calibrate" in resolve_toolset(bundle)
    result = _calibrate({
        "directness": 1, "consistency": 1, "recency": 1,
        "namespace_match": 1, "independent_sources": 2,
        "explicit_user_confirmation": True,
    })
    assert result["action"] == "answer"


def test_confidence_tool_abstains_on_cross_namespace_claim():
    result = _calibrate({"directness": 1, "consistency": 1, "recency": 1, "namespace_match": 0, "independent_sources": 3})
    assert result["action"] == "abstain"
    assert result["confidence"] == 0
