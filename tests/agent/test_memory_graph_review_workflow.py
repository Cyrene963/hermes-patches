import json
from pathlib import Path

import importlib

from fastapi.testclient import TestClient

from agent.memory_graph.services.snapshot import ChangesetStore


def _write_changeset(base_dir: Path, changeset_id: str, payload: dict) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / f"{changeset_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


class _DummyGraphService:
    async def get_memory_by_path(self, *args, **kwargs):
        return None

    async def get_children(self, *args, **kwargs):
        return []

    async def log_access(self, *args, **kwargs):
        return None

    async def create_memory(self, *args, **kwargs):
        return {"uri": "core://x", "node_uuid": "n1"}

    async def update_memory(self, *args, **kwargs):
        return {"uri": "core://x", "node_uuid": "n1"}

    async def delete_memory(self, *args, **kwargs):
        return True

    async def add_alias(self, *args, **kwargs):
        return {"ok": True}


class _DummySearchIndexer:
    async def search(self, *args, **kwargs):
        return []

    async def refresh_search_documents_for_node(self, *args, **kwargs):
        return None


class _DummyGlossaryService:
    async def add_keyword(self, *args, **kwargs):
        return {"ok": True}

    async def scan_content(self, *args, **kwargs):
        return []


def _patch_auth(monkeypatch, namespace="telegram:alice"):
    auth = importlib.import_module("agent.memory_graph.auth")
    monkeypatch.setattr(
        auth,
        "authenticate",
        lambda username, password: {
            "username": username,
            "namespace": namespace,
        } if username == "alice" and password == "pw" else None,
    )
    monkeypatch.setattr(auth, "verify_session_token", lambda token: "alice" if token == "token" else None)
    monkeypatch.setattr(
        auth,
        "get_user",
        lambda username: {
            "username": username,
            "namespace": namespace,
        } if username == "alice" else None,
    )


def _patch_store(monkeypatch, changesets: Path):
    snapshot_mod = importlib.import_module("agent.memory_graph.services.snapshot")
    monkeypatch.setattr(snapshot_mod, "ChangesetStore", lambda *args, **kwargs: ChangesetStore(str(changesets)))


def test_review_endpoints_keep_legacy_changesets_visible(tmp_path, monkeypatch):
    changesets = tmp_path / "changesets"
    _write_changeset(
        changesets,
        "legacy",
        {
            "id": "legacy",
            "action": "memories",
            "uri": "core://alpha",
            "node_uuid": "n1",
            "before": {"content": "old"},
            "after": {"content": "new"},
            "timestamp": "2026-06-12T00:00:00+00:00",
        },
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _patch_auth(monkeypatch)
    _patch_store(monkeypatch, changesets)

    server = importlib.import_module("agent.memory_graph.server")
    client = TestClient(server.create_app(_DummyGraphService(), _DummySearchIndexer(), _DummyGlossaryService()))
    client.cookies.set("mg_session", "token")

    changes = client.get("/api/memory-graph/review/changes", params={"changeset_id": "legacy"})
    assert changes.status_code == 200
    assert changes.json()[0]["id"] == "legacy"

    listing = client.get("/api/memory-graph/review/list")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == "legacy"

    approve = client.post("/api/memory-graph/review/approve", json={"changeset_id": "legacy"})
    assert approve.status_code == 200
    assert not (changesets / "legacy.json").exists()


def test_review_endpoints_skip_malformed_changesets(tmp_path, monkeypatch):
    changesets = tmp_path / "changesets"
    _write_changeset(
        changesets,
        "good",
        {
            "id": "good",
            "action": "memories",
            "uri": "core://alpha",
            "node_uuid": "n1",
            "timestamp": "2026-06-12T00:00:00+00:00",
        },
    )
    (changesets / "bad.json").write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _patch_auth(monkeypatch)
    _patch_store(monkeypatch, changesets)

    server = importlib.import_module("agent.memory_graph.server")
    client = TestClient(server.create_app(_DummyGraphService(), _DummySearchIndexer(), _DummyGlossaryService()))
    client.cookies.set("mg_session", "token")

    listing = client.get("/api/memory-graph/review/list")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == ["good"]
