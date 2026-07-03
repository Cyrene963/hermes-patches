"""Unit tests for agent.memory_fact_classifier — focus on the FAIL-CLOSED contract.
Run: pytest tests/agent/test_memory_fact_classifier.py -q  (no live LLM needed)
"""
import importlib.util
import os
import sys
import types

import pytest

_HERE = os.path.dirname(__file__)


@pytest.fixture(autouse=True)
def _restore_agent_modules():
    original_agent = sys.modules.get("agent")
    original_aux = sys.modules.get("agent.auxiliary_client")
    yield
    if original_agent is None:
        sys.modules.pop("agent", None)
    else:
        sys.modules["agent"] = original_agent
    if original_aux is None:
        sys.modules.pop("agent.auxiliary_client", None)
    else:
        sys.modules["agent.auxiliary_client"] = original_aux


def _load():
    # Provide a stub agent.auxiliary_client so import never hits the real client.
    pkg = types.ModuleType("agent")
    pkg.__path__ = []
    sys.modules.setdefault("agent", pkg)
    aux = types.ModuleType("agent.auxiliary_client")
    aux.call_llm = lambda **k: (_ for _ in ()).throw(RuntimeError("stub: not configured"))
    sys.modules["agent.auxiliary_client"] = aux
    path = os.path.normpath(os.path.join(_HERE, "..", "..", "agent", "memory_fact_classifier.py"))
    spec = importlib.util.spec_from_file_location("memory_fact_classifier", path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m, aux


def test_fail_closed_when_llm_unavailable():
    m, _ = _load()
    v = m.classify_fact("记住：我的部署命令是 pm2 reload all")
    assert v.durable is False and v.source == "unavailable"


def test_parses_durable_json_and_gates_on_confidence_and_kind():
    m, aux = _load()

    class R:
        class choices:
            pass
    def fake(**k):
        msg = types.SimpleNamespace(content='{"durable": true, "kind": "preference", "fact": "用户固定用 vim", "confidence": 0.9}')
        choice = types.SimpleNamespace(message=msg)
        return types.SimpleNamespace(choices=[choice])
    aux.call_llm = fake
    v = m.classify_fact("记住我用 vim")
    assert v.durable is True and v.kind == "preference" and v.fact == "用户固定用 vim"


def test_low_confidence_is_rejected():
    m, aux = _load()
    aux.call_llm = lambda **k: types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content='{"durable": true, "kind": "preference", "fact": "x maybe", "confidence": 0.4}'))])
    v = m.classify_fact("可能我喜欢深色模式吧")
    assert v.durable is False


def test_non_auto_kind_rejected():
    m, aux = _load()
    aux.call_llm = lambda **k: types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content='{"durable": true, "kind": "none", "fact": "", "confidence": 0.95}'))])
    v = m.classify_fact("今天天气不错")
    assert v.durable is False


def test_unparseable_response_fails_closed():
    m, aux = _load()
    aux.call_llm = lambda **k: types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content='I think this might be a preference?'))])
    v = m.classify_fact("随便说点什么")
    assert v.durable is False


def test_code_fence_json_is_parsed():
    m, aux = _load()
    aux.call_llm = lambda **k: types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content='```json\n{"durable": true, "kind": "correction", "fact": "数据库是 PostgreSQL", "confidence": 0.88}\n```'))])
    v = m.classify_fact("纠正：数据库是 PostgreSQL 不是 MySQL")
    assert v.durable is True and v.fact == "数据库是 PostgreSQL"


# ── subject routing ──────────────────────────────────────────────────────────
def test_parses_subject_field():
    m, aux = _load()
    aux.call_llm = lambda **k: __import__("types").SimpleNamespace(choices=[__import__("types").SimpleNamespace(
        message=__import__("types").SimpleNamespace(content='{"durable":true,"kind":"preference","fact":"Steven 喝美式","subject":"Steven","confidence":0.95}'))])
    v = m.classify_fact("Steven 喜欢喝美式咖啡")
    assert v.durable is True and v.subject == "Steven"


def test_resolve_subject_self_returns_speaker_ns():
    m, _ = _load()
    ns, other = m.resolve_subject_namespace("self", "telegram:111")
    assert ns == "telegram:111" and other is False


def test_resolve_subject_other_mapped(monkeypatch):
    m, _ = _load()
    monkeypatch.setattr(m, "load_user_registry", lambda: {"steven": "telegram:999"})
    ns, other = m.resolve_subject_namespace("Steven", "telegram:111")
    assert ns == "telegram:999" and other is True


def test_resolve_subject_other_unmapped(monkeypatch):
    m, _ = _load()
    monkeypatch.setattr(m, "load_user_registry", lambda: {})
    ns, other = m.resolve_subject_namespace("SomeStranger", "telegram:111")
    assert ns is None and other is True
