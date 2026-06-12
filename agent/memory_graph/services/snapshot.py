"""Changeset Store — row-level before/after state for review and rollback.

Records changes as JSON files on disk, providing a simple audit trail
without requiring additional database tables.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path as FilePath
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ChangesetStore:
    """File-based changeset storage for memory operations."""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = os.path.expanduser("~/.hermes/memory_graph/changesets")
        self._base_dir = base_dir
        os.makedirs(self._base_dir, exist_ok=True)

    def _changeset_path(self, changeset_id: str) -> str:
        return os.path.join(self._base_dir, f"{changeset_id}.json")

    def load(self, changeset_id: str, namespace: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Load a changeset by ID, optionally enforcing namespace.

        Legacy changesets written before namespace support are treated as
        global records and remain visible to any namespace.
        """
        path = self._changeset_path(changeset_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
        if namespace is not None:
            record_namespace = data.get("namespace", "")
            if record_namespace not in {"", namespace}:
                return None
        return data

    def save(self, changeset_id: str, data: Dict[str, Any]) -> str:
        """Save a changeset and return its path."""
        path = self._changeset_path(changeset_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        return path

    def record_change(self, action: str, uri: str, node_uuid: str,
                       before: Optional[Dict] = None, after: Optional[Dict] = None,
                       namespace: str = "") -> str:
        """Record a single change operation."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        changeset_id = f"{ts}_{node_uuid[:8]}"

        data = {
            "id": changeset_id,
            "action": action,
            "uri": uri,
            "node_uuid": node_uuid,
            "namespace": namespace,
            "before": before,
            "after": after,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return self.save(changeset_id, data)

    def get_changes(self, changeset_id: str, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return the stored change record for a specific changeset ID."""
        data = self.load(changeset_id, namespace=namespace)
        return [data] if data else []

    def clear(self, changeset_id: str, namespace: Optional[str] = None) -> bool:
        """Delete a changeset by ID, optionally enforcing namespace."""
        path = self._changeset_path(changeset_id)
        data = self.load(changeset_id, namespace=namespace)
        if not data:
            return False
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False

    def list_changesets(self, limit: int = 100, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """List recent changesets as dashboard-ready summaries."""
        summaries: List[Dict[str, Any]] = []
        for fname in sorted(os.listdir(self._base_dir), reverse=True):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self._base_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
            if namespace is not None and data.get("namespace", "") not in {"", namespace}:
                continue
            summaries.append({
                "id": data.get("id"),
                "namespace": data.get("namespace", ""),
                "created_at": data.get("timestamp"),
                "changes": [data],
                "action": data.get("action"),
                "uri": data.get("uri"),
                "node_uuid": data.get("node_uuid"),
            })
            if len(summaries) >= limit:
                break
        return summaries

    def purge_older_than_days(self, older_than_days: int = 30) -> int:
        """Clear changesets older than N days."""
        cutoff = datetime.now(timezone.utc).timestamp() - (older_than_days * 86400)
        removed = 0
        for fname in os.listdir(self._base_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self._base_dir, fname)
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        return removed
