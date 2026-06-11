"""Unit tests for agent.memory_write_earn — typed/hygiene/readback/quarantine gates.
Run: pytest tests/agent/test_memory_write_earn.py -q  (injected fakes; no DB needed)
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(__file__)
_MOD = os.path.normpath(os.path.join(_HERE, "..", "..", "agent", "memory_write_earn.py"))
spec = importlib.util.spec_from_file_location("memory_write_earn", _MOD)
we = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = we  # required so @dataclass can resolve its module
spec.loader.exec_module(we)

Action = we.Action


class FakeStore:
    def __init__(self, *, retrievable=True):
        self.nodes = {}
        self.retrievable = retrievable
        self._n = 0

    def write(self, ns, title, content):
        self._n += 1
        uuid = f"uuid-{self._n}"
        self.nodes[(ns, title)] = (uuid, content)
        return uuid

    def search(self, query, ns, limit):
        if not self.retrievable:
            return []
        items = [(u, c) for (n, _t), (u, c) in self.nodes.items() if n == ns]
        if not items:
            return []
        u, c = items[-1]
        return [{"node_uuid": u, "snippet": c}]

    def delete(self, ns, title):
        self.nodes.pop((ns, title), None)


def _cand(memory_type, obj, reason=""):
    return {"memory_type": memory_type, "object": obj, "reason": reason}


def test_chatter_is_rejected():
    assert we.decide(_cand("", "在吗"), namespace="u:1").action == Action.REJECT


def test_project_fact_always_proposed():
    assert we.decide(_cand("project_fact", "项目用 PM2 部署"), namespace="u:1").action == Action.PROPOSE


def test_secret_bearing_is_rejected():
    d = we.decide(_cand("explicit_preference", "我的 key 是 sk-abcdefgh12345678"), namespace="u:1")
    assert d.action == Action.REJECT and "contains_secret" in d.hygiene_flags


def test_raw_truncated_copy_rejected():
    msg = "gpt-5.5-pro 你去问这个网关通不通然后把三次结果按时间顺序发给我谢谢辛苦了备注很多" * 3
    obj = msg[:80]  # a real slice of a much longer message (msg is ~120+ chars)
    assert len(obj) < len(msg) - 15  # guard: ensure this is genuinely truncated
    d = we.decide(_cand("explicit_preference", obj), namespace="u:1", source_message=msg)
    assert d.action == Action.REJECT and "raw_truncated_copy" in d.hygiene_flags


def test_clean_short_instruction_not_flagged_as_truncated():
    # content == source (user typed exactly this) must NOT be raw_truncated_copy
    msg = "纠正：数据库用 PostgreSQL 不是 MySQL"
    assert "raw_truncated_copy" not in we.hygiene_flags(msg, msg)


def test_question_goes_to_propose():
    d = we.decide(_cand("explicit_preference", "我应该用哪个编辑器？"), namespace="u:1")
    assert d.action == Action.PROPOSE and "is_question" in d.hygiene_flags


def test_clean_preference_auto_off_by_default():
    store = FakeStore(retrievable=True)
    d = we.decide(_cand("explicit_preference", "编辑器固定用 vim，不要用 nano。"),
                  namespace="u:1", anchor_query="编辑器偏好", title="pref",
                  search_fn=store.search, write_fn=store.write, delete_fn=store.delete)
    assert d.readback_ok is True and d.action == Action.PROPOSE


def test_clean_correction_auto_applies_when_enabled():
    store = FakeStore(retrievable=True)
    d = we.decide(_cand("explicit_correction", "纠正：数据库是 PostgreSQL 不是 MySQL。"),
                  namespace="u:1", anchor_query="数据库", title="corr",
                  search_fn=store.search, write_fn=store.write, delete_fn=store.delete, enable_auto=True)
    assert d.action == Action.AUTO_APPLY and d.readback_ok is True


def test_unretrievable_fact_proposed_not_applied():
    store = FakeStore(retrievable=False)
    d = we.decide(_cand("explicit_preference", "一个无法被检索回来的事实陈述句"),
                  namespace="u:1", anchor_query="zzz", title="x",
                  search_fn=store.search, write_fn=store.write, delete_fn=store.delete, enable_auto=True)
    assert d.action == Action.PROPOSE and d.readback_ok is False


def test_core_namespace_never_auto_applies():
    store = FakeStore(retrievable=True)
    d = we.decide(_cand("explicit_preference", "一个会写到共享区的偏好陈述"),
                  namespace="core", anchor_query="偏好", title="x",
                  search_fn=store.search, write_fn=store.write, delete_fn=store.delete, enable_auto=True)
    assert d.action == Action.PROPOSE and d.risk == "high"


def test_no_readback_io_cannot_prove_so_proposes():
    d = we.decide(_cand("explicit_preference", "干净的偏好但没有提供 readback IO 通道"),
                  namespace="u:1", enable_auto=True)
    assert d.action == Action.PROPOSE


def test_quarantine_namespace_is_used():
    seen = {}
    def wf(ns, title, content):
        seen["ns"] = ns
        return "u1"
    we.readback_check(content="x", anchor_query="x", namespace="u:42", title="t",
                      search_fn=lambda q, ns, limit: [{"node_uuid": "u1"}], write_fn=wf)
    assert seen["ns"] == "quarantine:u:42"
