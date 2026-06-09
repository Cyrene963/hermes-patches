"""Tests for Hindsight recall access tracking."""

import importlib


def test_record_recall_flushes_immediately_and_uses_configured_database(monkeypatch, tmp_path):
    tracker = importlib.import_module("agent.hindsight_access_tracker")
    tracker._batch = []

    env_dir = tmp_path / ".hindsight" / "profiles"
    env_dir.mkdir(parents=True)
    env_dir.joinpath("hermes.env").write_text("HINDSIGHT_API_DATABASE_URL=postgresql://user:pass@db/hindsight\n")
    monkeypatch.setattr(tracker.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("HINDSIGHT_API_DATABASE_URL", raising=False)

    calls = []

    class FakeCursor:
        rowcount = 2

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            calls.append((sql, params))

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    class FakePsycopg2:
        def connect(self, database_url):
            calls.append(("connect", database_url))
            return FakeConnection()

    monkeypatch.setitem(__import__("sys").modules, "psycopg2", FakePsycopg2())

    tracker.record_recall(["mem-1", "mem-1", "mem-2"])

    assert calls[0] == ("connect", "postgresql://user:pass@db/hindsight")
    assert calls[1][1] == (["mem-1", "mem-2"],)
    assert tracker._batch == []


def test_record_recall_skips_without_database_url(monkeypatch, tmp_path):
    tracker = importlib.import_module("agent.hindsight_access_tracker")
    tracker._batch = []
    monkeypatch.setattr(tracker.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("HINDSIGHT_API_DATABASE_URL", raising=False)

    tracker.record_recall(["mem-1"])

    assert tracker._batch == []
