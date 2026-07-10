from __future__ import annotations

from unittest.mock import MagicMock

from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider


class _Provider(MemoryProvider):
    def __init__(self) -> None:
        self.result = ""

    @property
    def name(self) -> str:
        return "outage-test"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        return None

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        return self.result

    def get_tool_schemas(self):
        return []


def test_provider_outage_uses_recent_session_local_recall():
    manager = MemoryManager()
    provider = _Provider()
    provider.result = "The user's active project is Atlas."
    manager.add_provider(provider)

    assert manager.prefetch_all("active project", session_id="session-a") == provider.result
    provider.prefetch = MagicMock(side_effect=ConnectionError("provider offline"))

    degraded = manager.prefetch_all("continue the project", session_id="session-a")

    assert "Memory recall degraded" in degraded
    assert provider.result in degraded


def test_provider_outage_never_crosses_session_boundary():
    manager = MemoryManager()
    provider = _Provider()
    provider.result = "Private context for session A"
    manager.add_provider(provider)
    manager.prefetch_all("private context", session_id="session-a")
    provider.prefetch = MagicMock(side_effect=ConnectionError("provider offline"))

    assert manager.prefetch_all("private context", session_id="session-b") == ""


def test_provider_outage_rejects_expired_recall(monkeypatch):
    manager = MemoryManager()
    provider = _Provider()
    provider.result = "Recent context"
    manager.add_provider(provider)
    clock = iter((100.0, 100.0 + 15 * 60 + 1))
    monkeypatch.setattr("agent.memory_manager.time.monotonic", lambda: next(clock))
    manager.prefetch_all("context", session_id="session-a")
    provider.prefetch = MagicMock(side_effect=ConnectionError("provider offline"))

    assert manager.prefetch_all("context", session_id="session-a") == ""


def test_empty_success_does_not_replay_previous_recall():
    manager = MemoryManager()
    provider = _Provider()
    provider.result = "Old context"
    manager.add_provider(provider)
    manager.prefetch_all("old query", session_id="session-a")

    provider.result = ""

    assert manager.prefetch_all("unrelated query", session_id="session-a") == ""
