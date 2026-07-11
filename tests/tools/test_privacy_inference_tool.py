from tools.privacy_inference_tool import _assess
from tools.registry import discover_builtin_tools, registry
from toolsets import resolve_toolset


def test_privacy_inference_tool_registered_visible_and_executes():
    assert "tools.privacy_inference_tool" in discover_builtin_tools()
    assert registry.get_entry("privacy_inference_assess") is not None
    for bundle in ("hermes-cli", "hermes-telegram", "hermes-cron"):
        assert "privacy_inference_assess" in resolve_toolset(bundle)
    result = _assess({"category": "mental_health", "namespace_match": True, "source_role": "assistant"})
    assert result["action"] == "refuse"


def test_privacy_tool_allows_only_bounded_confirmed_sensitive_use():
    result = _assess({
        "category": "finances", "namespace_match": True, "source_role": "user",
        "explicit_user_statement": True, "confirmed_current_namespace_evidence": True,
        "user_requested_use": True,
    })
    assert result["action"] == "allow_bounded"
