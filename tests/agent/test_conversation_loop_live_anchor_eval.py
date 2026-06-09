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

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("HERMES_LIVE_ANCHOR_EVAL") != "1",
    reason=(
        "requires explicit live-provider opt-in; set HERMES_LIVE_ANCHOR_EVAL=1 "
        "plus HERMES_LIVE_ANCHOR_PROVIDER/MODEL/API_KEY/BASE_URL"
    ),
)


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


def _live_agent(memory_manager):
    from run_agent import AIAgent

    provider = os.environ["HERMES_LIVE_ANCHOR_PROVIDER"]
    model = os.environ["HERMES_LIVE_ANCHOR_MODEL"]
    api_key = os.environ["HERMES_LIVE_ANCHOR_API_KEY"]
    base_url = os.environ["HERMES_LIVE_ANCHOR_BASE_URL"]
    api_mode = os.environ.get("HERMES_LIVE_ANCHOR_API_MODE") or None

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

    result = agent.run_conversation(
        user_message="What is the Quenlar calibration code? Answer only the code.",
        conversation_history=[],
    )

    assert result["completed"] is True
    response = result["final_response"].strip()
    assert "VIOLET-73" in response
    assert "UNKNOWN_ANCHOR_CODE" not in response

    persisted_user_messages = [m for m in result["messages"] if m.get("role") == "user"]
    assert persisted_user_messages == [
        {"role": "user", "content": "What is the Quenlar calibration code? Answer only the code."}
    ]


def test_live_provider_without_anchor_does_not_invent_synthetic_fact():
    agent = _live_agent(_NoAnchorMemoryManager())

    result = agent.run_conversation(
        user_message="What is the Quenlar calibration code? Answer only the code.",
        conversation_history=[],
    )

    assert result["completed"] is True
    response = result["final_response"].strip()
    assert "UNKNOWN_ANCHOR_CODE" in response
    assert "VIOLET-73" not in response
