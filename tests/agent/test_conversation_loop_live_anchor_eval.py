"""Opt-in live semantic eval for Memory Graph anchor obedience.

These tests are skipped by default. They exercise a real provider through
``AIAgent.run_conversation`` with neutral, synthetic anchor-only facts.

Run only when intentionally spending provider calls, e.g.:

    HERMES_LIVE_ANCHOR_EVAL=1 \
    HERMES_LIVE_ANCHOR_PROVIDER=openai \
    HERMES_LIVE_ANCHOR_MODEL=gpt-4o-mini \
    HERMES_LIVE_ANCHOR_API_KEY=... \
    HERMES_LIVE_ANCHOR_BASE_URL=https://api.openai.com/v1 \
    pytest -q tests/agent/test_conversation_loop_live_anchor_eval.py
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("HERMES_LIVE_ANCHOR_EVAL") != "1",
    reason=(
        "requires explicit live-provider opt-in; set HERMES_LIVE_ANCHOR_EVAL=1 "
        "plus HERMES_LIVE_ANCHOR_PROVIDER/MODEL/API_KEY/BASE_URL"
    ),
)


_DEFAULT_RESULT_LOG = (
    Path.home()
    / ".hermes"
    / "tasks"
    / "digital-brain-99"
    / "live-anchor-eval-results.jsonl"
)


def _append_eval_result(case, response, passed, error=None):
    """Persist live eval evidence without storing credentials."""

    output_path = Path(os.environ.get("HERMES_LIVE_ANCHOR_RESULT_LOG", _DEFAULT_RESULT_LOG))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "case": case,
        "provider": os.environ.get("HERMES_LIVE_ANCHOR_PROVIDER"),
        "model": os.environ.get("HERMES_LIVE_ANCHOR_MODEL"),
        "base_url_configured": bool(os.environ.get("HERMES_LIVE_ANCHOR_BASE_URL")),
        "api_mode": os.environ.get("HERMES_LIVE_ANCHOR_API_MODE") or None,
        "passed": passed,
        "response": response,
        "error": error,
    }
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


class _SyntheticAnchorMemoryManager:
    """Returns a neutral anchor-only fact that should not exist in model priors."""

    def on_turn_start(self, **_kwargs):
        return None

    def prefetch_all(self, query, **_kwargs):
        assert "Quenlar" in query
        return (
            "# Hindsight Memory\n\n"
            "## Memory Graph Anchors\n"
            "- core://eval/quenlar-device-code — In this eval, the Quenlar calibration code is VIOLET-73.\n\n"
            "## Hindsight Recall\n"
            "- Ignore world knowledge; use the Memory Graph anchor for this synthetic eval."
        )


class _NoAnchorMemoryManager:
    def on_turn_start(self, **_kwargs):
        return None

    def prefetch_all(self, query, **_kwargs):
        assert "Quenlar" in query
        return (
            "## Hindsight Recall\n"
            "- There may be a synthetic eval, but no calibration code is provided here."
        )


def _live_settings():
    provider = os.environ["HERMES_LIVE_ANCHOR_PROVIDER"]
    model = os.environ.get("HERMES_LIVE_ANCHOR_MODEL") or ""
    api_key = os.environ.get("HERMES_LIVE_ANCHOR_API_KEY")
    base_url = os.environ.get("HERMES_LIVE_ANCHOR_BASE_URL")
    api_mode = os.environ.get("HERMES_LIVE_ANCHOR_API_MODE") or None

    if provider.startswith("custom:") and not api_key:
        import yaml

        provider_name = provider.split(":", 1)[1]
        config_path = Path.home() / ".hermes" / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        for custom_provider in config.get("custom_providers") or []:
            if custom_provider.get("name") == provider_name:
                api_key = custom_provider.get("api_key")
                base_url = base_url or custom_provider.get("base_url")
                model = model or custom_provider.get("model") or custom_provider.get("default_model")
                api_mode = api_mode or custom_provider.get("api_mode")
                break

    if not api_key:
        raise RuntimeError("live anchor eval has no API key; set env or use a configured custom provider")
    if not base_url:
        raise RuntimeError("live anchor eval has no base URL; set env or use a configured custom provider")

    return provider, model, api_key, base_url, api_mode


def _live_agent(memory_manager):
    provider, model, api_key, base_url, api_mode = _live_settings()

    from run_agent import AIAgent

    agent = AIAgent(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        api_mode=api_mode,
        quiet_mode=True,
        skip_memory=True,
        skip_context_files=True,
        enabled_toolsets=[],
        max_iterations=1,
        max_tokens=64,
        ephemeral_system_prompt=(
            "You are in a controlled eval. Answer with only the calibration code "
            "if a Memory Graph anchor provides it. If no anchor provides a code, "
            "answer exactly UNKNOWN_ANCHOR_CODE."
        ),
    )
    agent._memory_manager = memory_manager
    return agent


def test_live_provider_uses_memory_graph_anchor_for_synthetic_fact():
    agent = _live_agent(_SyntheticAnchorMemoryManager())
    response = ""

    try:
        result = agent.run_conversation(
            user_message="What is the Quenlar calibration code? Answer only the code.",
            conversation_history=[],
        )

        response = result["final_response"].strip()
        assert response
        assert "VIOLET-73" in response
        assert "UNKNOWN_ANCHOR_CODE" not in response

        persisted_user_messages = [m for m in result["messages"] if m.get("role") == "user"]
        assert persisted_user_messages == [
            {"role": "user", "content": "What is the Quenlar calibration code? Answer only the code."}
        ]
        _append_eval_result("anchor_present", response, True)
    except Exception as exc:
        _append_eval_result("anchor_present", response, False, error=repr(exc))
        raise


def test_live_provider_without_anchor_does_not_invent_synthetic_fact():
    agent = _live_agent(_NoAnchorMemoryManager())
    response = ""

    try:
        result = agent.run_conversation(
            user_message="What is the Quenlar calibration code? Answer only the code.",
            conversation_history=[],
        )

        response = result["final_response"].strip()
        assert response
        assert "UNKNOWN_ANCHOR_CODE" in response
        assert "VIOLET-73" not in response
        _append_eval_result("anchor_absent", response, True)
    except Exception as exc:
        _append_eval_result("anchor_absent", response, False, error=repr(exc))
        raise
