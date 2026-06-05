"""Regression tests for atomic fallback route activation.

Fallback routes must switch the whole provider/model/base_url/api_mode/client
state together. These tests prevent a fallback provider/model from being paired
with the primary provider endpoint after activation or credential recovery.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class _FakeClient:
    def __init__(self, *, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url


class _FakePool:
    provider = "custom:dxb-huifei-net"


class _FakeAnthropicClient:
    pass


def _make_agent(**overrides):
    from run_agent import AIAgent

    kwargs = dict(
        provider="custom:Dxb.huifei.net",
        model="gpt-5.5",
        base_url="https://dxb.huifei.net/v1",
        api_key="sk-primary-test",
        api_mode="chat_completions",
        fallback_model=[],
        enabled_toolsets=[],
        disabled_toolsets=["all"],
        max_iterations=1,
        skip_memory=True,
        skip_context_files=True,
        quiet_mode=True,
    )
    kwargs.update(overrides)
    return AIAgent(**kwargs)


def test_anthropic_custom_fallback_preserves_explicit_api_mode_and_endpoint():
    agent = _make_agent(
        fallback_model=[
            {
                "provider": "custom:GetokenCCMax",
                "model": "claude-opus-4-8",
                "base_url": "https://api.getoken.tech",
                "api_key": "sk-fallback-test",
                "api_mode": "anthropic_messages",
            }
        ]
    )
    agent._credential_pool = _FakePool()

    fake_client = _FakeClient(api_key="sk-fallback-test", base_url="https://api.getoken.tech")

    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        return_value=(fake_client, "claude-opus-4-8"),
    ), patch(
        "agent.anthropic_adapter.build_anthropic_client",
        return_value=_FakeAnthropicClient(),
    ) as build_client:
        assert agent._try_activate_fallback() is True

    assert agent.provider == "custom:getokenccmax"
    assert agent.model == "claude-opus-4-8"
    assert str(agent.base_url).rstrip("/") == "https://api.getoken.tech"
    assert agent.api_mode == "anthropic_messages"
    assert agent.client is None
    assert isinstance(agent._anthropic_client, _FakeAnthropicClient)
    assert agent._credential_pool is None
    build_client.assert_called_once()
    assert build_client.call_args.args[:2] == ("sk-fallback-test", "https://api.getoken.tech")


def test_openai_compatible_custom_fallback_uses_explicit_chat_completions_not_model_inference():
    agent = _make_agent(
        fallback_model=[
            {
                "provider": "custom:Muyuan",
                "model": "gpt-5.5",
                "base_url": "https://muyuan.example/v1",
                "api_key": "sk-fallback-test",
                "api_mode": "chat_completions",
            }
        ]
    )

    fake_client = _FakeClient(api_key="sk-fallback-test", base_url="https://muyuan.example/v1")

    with patch(
        "agent.auxiliary_client.resolve_provider_client",
        return_value=(fake_client, "gpt-5.5"),
    ):
        assert agent._try_activate_fallback() is True

    assert agent.provider == "custom:muyuan"
    assert agent.model == "gpt-5.5"
    assert str(agent.base_url).rstrip("/") == "https://muyuan.example/v1"
    assert agent.api_mode == "chat_completions"
    assert agent.client is fake_client


def test_recovery_ignores_cross_provider_pool_after_fallback_activation():
    agent = _make_agent(provider="custom:GetokenCCMax", base_url="https://api.getoken.tech")
    agent._fallback_activated = True
    agent._credential_pool = MagicMock()
    agent._credential_pool.provider = "custom:dxb-huifei-net"
    agent._credential_pool.mark_exhausted_and_rotate.return_value = SimpleNamespace(
        id="primary-entry",
        runtime_api_key="sk-primary-test",
        runtime_base_url="https://dxb.huifei.net/v1",
        provider="custom:dxb-huifei-net",
    )
    agent._swap_credential = MagicMock()

    recovered, retried = agent._recover_with_credential_pool(
        status_code=402,
        has_retried_429=False,
    )

    assert recovered is False
    assert retried is False
    agent._credential_pool.mark_exhausted_and_rotate.assert_not_called()
    agent._swap_credential.assert_not_called()
