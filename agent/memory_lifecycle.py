"""Authorized, auditable memory deletion and rollback lifecycle."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


class DeleteGrantAuthority:
    """Issue and consume short-lived host-signed delete grants."""

    def __init__(self, secret: bytes, *, now: Callable[[], float] | None = None, consumed_dir: str | Path | None = None) -> None:
        import time
        self.secret = secret
        self.now = now or time.time
        self.consumed_dir = Path(consumed_dir or os.path.expanduser("~/.hermes/memory_delete_grants/consumed"))

    def issue(self, *, uri: str, namespace: str, user_message: str, ttl_seconds: int = 300) -> str:
        payload = {
            "uri": uri,
            "namespace": namespace,
            "message_sha256": hashlib.sha256(user_message.encode()).hexdigest(),
            "expires_at": int(self.now()) + max(1, min(int(ttl_seconds), 600)),
            "nonce": uuid.uuid4().hex,
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        import base64
        return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + signature

    def consume(self, token: str, *, uri: str, namespace: str) -> dict[str, Any]:
        import base64
        try:
            encoded, signature = token.split(".", 1)
            body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            expected = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return {"ok": False, "error": "invalid_delete_grant"}
            payload = json.loads(body)
        except Exception:
            return {"ok": False, "error": "invalid_delete_grant"}
        nonce = str(payload.get("nonce") or "")
        if not nonce:
            return {"ok": False, "error": "delete_grant_replayed"}
        consumed = self.consumed_dir / nonce
        if consumed.exists():
            return {"ok": False, "error": "delete_grant_replayed"}
        if int(payload.get("expires_at") or 0) < int(self.now()):
            return {"ok": False, "error": "delete_grant_expired"}
        if payload.get("uri") != uri or payload.get("namespace") != namespace:
            return {"ok": False, "error": "delete_grant_scope_mismatch"}
        self.consumed_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(consumed, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return {"ok": False, "error": "delete_grant_replayed"}
        with os.fdopen(fd, "w") as handle:
            handle.write(str(payload.get("expires_at") or ""))
        return {"ok": True, "message_sha256": payload["message_sha256"], "nonce": nonce}


def load_delete_grant_authority() -> DeleteGrantAuthority:
    key_path = Path(os.path.expanduser("~/.hermes/secrets/memory_delete_grant.key"))
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(os.urandom(32))
    return DeleteGrantAuthority(key_path.read_bytes())


@dataclass(frozen=True)
class DeleteDecision:
    action: str
    reason: str
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "reason": self.reason, "confidence": self.confidence}


def decide_delete_intent(request: Mapping[str, Any]) -> DeleteDecision:
    """Fail-closed policy for forgetting requests.

    execute is allowed only for an explicit user request resolving to one exact
    private URI. Automatic maintenance may archive, never destructively delete.
    """
    uri = str(request.get("uri") or "").strip()
    namespace = str(request.get("namespace") or "").strip()
    source = str(request.get("source") or "").strip().lower()
    explicit = bool(request.get("explicit_user_authorization"))
    candidate_count = int(request.get("candidate_count") or 0)
    is_leaf = bool(request.get("is_leaf"))
    if source == "maintenance":
        return DeleteDecision("archive", "maintenance may archive but cannot delete", 1.0)
    if not explicit or source != "user_direct":
        return DeleteDecision("clarify", "destructive forgetting requires direct user authorization", 1.0)
    if not namespace:
        return DeleteDecision("refuse", "write namespace is required", 1.0)
    if not re.match(r"^[A-Za-z0-9_.-]+://[^/].+", uri):
        return DeleteDecision("clarify", "one exact memory URI is required", 1.0)
    if candidate_count != 1:
        return DeleteDecision("clarify", "request must resolve to exactly one memory", 1.0)
    if not is_leaf:
        return DeleteDecision("refuse", "recursive subtree deletion is not allowed", 1.0)
    return DeleteDecision("execute", "explicit exact leaf deletion authorized", 0.99)


class MemoryLifecycleManager:
    def __init__(
        self,
        *,
        read: Callable[[str, str], Mapping[str, Any] | None],
        children: Callable[[str, str], list[Mapping[str, Any]]],
        delete: Callable[[str, str], bool],
        create: Callable[[str, str, str, str, int], Mapping[str, Any]],
        update: Callable[[str, str, str, int], Mapping[str, Any]] | None = None,
        journal_root: str | Path | None = None,
    ) -> None:
        self.read = read
        self.children = children
        self.delete = delete
        self.create = create
        self.update = update
        self.journal_root = Path(journal_root or os.path.expanduser("~/.hermes/memory_changesets"))

    @staticmethod
    def _namespace_dir(namespace: str) -> str:
        return hashlib.sha256(namespace.encode()).hexdigest()[:24]

    def _path(self, namespace: str, changeset_id: str) -> Path:
        return self.journal_root / self._namespace_dir(namespace) / f"{changeset_id}.json"

    def _write_changeset(self, namespace: str, item: dict[str, Any]) -> str:
        changeset_id = str(item.get("changeset_id") or uuid.uuid4().hex)
        item["changeset_id"] = changeset_id
        path = self._path(namespace, changeset_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, indent=2) + "\n")
        return changeset_id

    def record_create(self, *, uri: str, namespace: str, after: Mapping[str, Any]) -> str:
        return self._write_changeset(namespace, {
            "schema_version": 1, "operation": "create", "namespace": namespace,
            "uri": uri, "before": {"absent": True}, "after": dict(after),
            "created_at": datetime.now(timezone.utc).isoformat(), "rolled_back_at": None,
            "result": "created",
        })

    def record_update(self, *, uri: str, namespace: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
        return self._write_changeset(namespace, {
            "schema_version": 1, "operation": "update", "namespace": namespace,
            "uri": uri,
            "before": {"content": before.get("content", ""), "priority": int(before.get("priority") or 0)},
            "after": {"content": after.get("content", ""), "priority": int(after.get("priority") or 0)},
            "created_at": datetime.now(timezone.utc).isoformat(), "rolled_back_at": None,
            "result": "updated",
        })

    @staticmethod
    def _split_uri(uri: str) -> tuple[str, str, str]:
        domain, path = uri.split("://", 1)
        parent, _, title = path.rpartition("/")
        return domain, parent, title

    def delete_leaf(self, request: Mapping[str, Any]) -> dict[str, Any]:
        uri, namespace = str(request.get("uri") or ""), str(request.get("namespace") or "")
        child_rows = self.children(uri, namespace) if uri and namespace else []
        enriched = dict(request)
        enriched["is_leaf"] = not child_rows
        decision = decide_delete_intent(enriched)
        if decision.action != "execute":
            return {"ok": False, "decision": decision.as_dict()}
        before = self.read(uri, namespace)
        if not before:
            return {"ok": False, "decision": decision.as_dict(), "error": "not_found"}
        domain, parent, title = self._split_uri(uri)
        changeset_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        changeset = {
            "schema_version": 1,
            "changeset_id": changeset_id,
            "operation": "delete",
            "namespace": namespace,
            "uri": uri,
            "authorization_sha256": hashlib.sha256(str(request.get("authorization_evidence") or "").encode()).hexdigest(),
            "before": {"content": before.get("content", ""), "priority": int(before.get("priority") or 0), "domain": domain, "parent": parent, "title": title},
            "after": {"absent": True},
            "created_at": now,
            "rolled_back_at": None,
        }
        self._write_changeset(namespace, changeset)
        path = self._path(namespace, changeset_id)
        deleted = bool(self.delete(uri, namespace))
        absent = self.read(uri, namespace) is None
        if not deleted or not absent:
            changeset["result"] = "delete_failed"
            path.write_text(json.dumps(changeset, ensure_ascii=False, indent=2) + "\n")
            return {"ok": False, "changeset_id": changeset_id, "error": "delete_readback_failed"}
        changeset["result"] = "deleted"
        path.write_text(json.dumps(changeset, ensure_ascii=False, indent=2) + "\n")
        return {"ok": True, "changeset_id": changeset_id, "uri": uri, "readback_absent": True}

    def rollback(self, *, changeset_id: str, namespace: str) -> dict[str, Any]:
        path = self._path(namespace, changeset_id)
        if not path.exists():
            return {"ok": False, "error": "changeset_not_found"}
        item = json.loads(path.read_text())
        if item.get("namespace") != namespace:
            return {"ok": False, "error": "namespace_mismatch"}
        existing = self.read(item["uri"], namespace)
        operation = item.get("operation")
        if operation == "create":
            if not existing:
                return {"ok": True, "already_rolled_back": True, "uri": item["uri"]}
            if self.children(item["uri"], namespace):
                return {"ok": False, "error": "created_uri_has_children"}
            if not self.delete(item["uri"], namespace) or self.read(item["uri"], namespace) is not None:
                return {"ok": False, "error": "create_rollback_readback_failed"}
            item["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
            item["result"] = "rolled_back"
            path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n")
            return {"ok": True, "uri": item["uri"], "readback_absent": True}
        if operation == "update":
            if not existing:
                return {"ok": False, "error": "updated_uri_missing"}
            if existing.get("content") == item["before"]["content"]:
                return {"ok": True, "already_restored": True, "uri": item["uri"]}
            if self.update is None:
                return {"ok": False, "error": "update_adapter_unavailable"}
            self.update(item["uri"], namespace, item["before"]["content"], item["before"]["priority"])
            restored = self.read(item["uri"], namespace)
            if not restored or restored.get("content") != item["before"]["content"]:
                return {"ok": False, "error": "update_rollback_readback_failed"}
            item["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
            item["result"] = "rolled_back"
            path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n")
            return {"ok": True, "uri": item["uri"], "readback_restored": True}
        if existing:
            if existing.get("content") == item["before"]["content"]:
                return {"ok": True, "already_restored": True, "uri": item["uri"]}
            return {"ok": False, "error": "uri_reused_with_different_content"}
        before = item["before"]
        created = self.create(before["domain"], before["parent"], before["title"], before["content"], before["priority"])
        restored = self.read(item["uri"], namespace)
        if not restored or restored.get("content") != before["content"]:
            return {"ok": False, "error": "rollback_readback_failed", "created": bool(created)}
        item["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        item["result"] = "rolled_back"
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n")
        return {"ok": True, "uri": item["uri"], "readback_restored": True}
