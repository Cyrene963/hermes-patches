"""Regression tests for clarification-on-use memory candidates."""

from agent.memory_clarification_queue import record_clarification_candidate
from agent.memory_manager import MemoryManager
from agent.memory_write_pipeline import CandidateFact
from agent.request_context import RequestContext, reset_context, set_context


class EmptyProvider:
    name = "empty"

    def is_available(self):
        return True

    def system_prompt_block(self):
        return ""

    def prefetch(self, query, *, session_id=""):
        return ""

    def queue_prefetch(self, query, *, session_id=""):
        return None

    def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None):
        return None

    def get_tool_schemas(self):
        return []

    def call_tool(self, name, arguments):
        raise NotImplementedError


def test_memory_manager_injects_relevant_clarification_candidates(tmp_path, monkeypatch):
    queue_path = tmp_path / "clarification.jsonl"
    monkeypatch.setattr("agent.memory_clarification_queue.DEFAULT_QUEUE_PATH", str(queue_path))
    candidate = CandidateFact(
        subject="tool_credential_route",
        predicate="semantic_signal",
        object_value="Claude credential route may already exist in config.",
        importance=0.9,
        memory_type="procedural_memory",
        target_store="clarification",
        target_path="用户档案/工具凭据查找规则",
        evidence_quote="User said to check existing Claude config before claiming unavailable.",
        confidence=0.9,
        source_type="user_direct",
        requires_review=True,
        namespace="telegram:u1",
    )
    record_clarification_candidate(candidate, {"namespace": "telegram:u1", "target_path": candidate.target_path}, queue_path=str(queue_path))

    manager = MemoryManager()
    manager.add_provider(EmptyProvider())
    set_context(RequestContext(user_id="u1", platform="telegram", namespace="telegram:u1"))

    try:
        unrelated = manager.prefetch_all("中史 15 分题怎么写")
        relevant = manager.prefetch_all("Claude Code not logged in 凭据在哪")
    finally:
        reset_context()

    assert "Memory Clarification Candidates" not in unrelated
    assert "Memory Clarification Candidates" in relevant
    assert "tool_credential_route" in relevant


def test_memory_manager_clarification_is_fail_closed_without_or_with_wrong_namespace(tmp_path, monkeypatch):
    queue_path = tmp_path / "clarification.jsonl"
    monkeypatch.setattr("agent.memory_clarification_queue.DEFAULT_QUEUE_PATH", str(queue_path))
    candidate = CandidateFact(
        subject="private_family_state",
        predicate="needs_current_confirmation",
        object_value="Private family state may have changed.",
        importance=0.9,
        memory_type="relationship_state",
        target_store="clarification",
        target_path="用户档案/家庭/状态",
        evidence_quote="Private owner-authored evidence.",
        confidence=0.9,
        source_type="external_import",
        requires_review=True,
        namespace="telegram:owner",
    )
    record_clarification_candidate(candidate, {"namespace": "telegram:owner", "target_path": candidate.target_path}, queue_path=str(queue_path))
    manager = MemoryManager()
    manager.add_provider(EmptyProvider())

    reset_context()
    missing = manager.prefetch_all("private family state changed")
    set_context(RequestContext(user_id="other", platform="telegram", namespace="telegram:other"))
    try:
        wrong_owner = manager.prefetch_all("private family state changed")
    finally:
        reset_context()

    assert "Memory Clarification Candidates" not in missing
    assert "Memory Clarification Candidates" not in wrong_owner
