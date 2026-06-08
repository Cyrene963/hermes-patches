"""
Changeset Store — Single-pool accumulation of row-level before/after states.

Overwrite semantics:
  - First touch of a PK: record both `before` (pre-AI) and `after` (post-AI).
  - Subsequent touches of the same PK: overwrite `after` only; `before` is frozen.
  - Net-zero changes (before == after) are filtered from display automatically.

Storage: one JSON file at `snapshots/changeset.json`.
"""

import os
import json
import stat
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from filelock import FileLock


def _default_snapshot_dir() -> str:
    env_dir = os.environ.get("SNAPSHOT_DIR")
    if env_dir:
        return env_dir

    # Local layout: <repo>/backend/db/snapshot.py -> snapshots under <repo>/snapshots
    # Docker layout: /app/db/snapshot.py -> snapshots under /app/snapshots
    db_dir = Path(__file__).resolve().parent
    app_root = db_dir.parent.parent
    if app_root.name == "backend":
        app_root = app_root.parent
    return str(app_root / "snapshots")


TABLE_ORDER = ["nodes", "memories", "edges", "paths", "glossary_keywords"]
TABLE_PKS = {
    "nodes": "uuid",
    "memories": "id",
    "edges": "id",
    "paths": ("namespace", "domain", "path"),
    "glossary_keywords": ("keyword", "node_uuid", "namespace"),
}


def _make_row_key(table: str, row: Dict[str, Any]) -> str:
    pk_def = TABLE_PKS[table]
    if isinstance(pk_def, tuple):
        pk_val = "|".join(str(row.get(k, "")) for k in pk_def)
    else:
        pk_val = str(row.get(pk_def, ""))
    return f"{table}:{pk_val}"


def _rows_equal(table: str, a: Optional[dict], b: Optional[dict]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
        
    if table == "glossary_keywords":
        a_copy = {k: v for k, v in a.items() if k not in ("id", "created_at")}
        b_copy = {k: v for k, v in b.items() if k not in ("id", "created_at")}
        return a_copy == b_copy
        
    return a == b


class ChangesetStore:
    """
    Accumulates row-level before/after states in a single pool.

    The review page reads the frozen `before` and queries live DB state
    to present the user with a clean delta and compute rollback paths.
    """

    def __init__(self, snapshot_dir: Optional[str] = None):
        self.snapshot_dir = snapshot_dir or _default_snapshot_dir()
        Path(self.snapshot_dir).mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(os.path.join(self.snapshot_dir, "changeset.json.lock"))

    @property
    def _changeset_path(self) -> str:
        return os.path.join(self.snapshot_dir, "changeset.json")

    def _load(self) -> Dict[str, Any]:
        p = self._changeset_path
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            rows = data.get("rows", {})
            # Backward compatibility: migrate old paths and glossary_keywords without namespace
            # to include namespace="" and fix their keys
            migrated_rows = {}
            for old_key, row in list(rows.items()):
                table = row.get("table")
                if table in ("paths", "glossary_keywords"):
                    changed = False
                    if row.get("before") and "namespace" not in row["before"]:
                        row["before"]["namespace"] = ""
                        changed = True
                    if row.get("after") and "namespace" not in row["after"]:
                        row["after"]["namespace"] = ""
                        changed = True
                    
                    # For glossary_keywords we must re-key anyway because the TABLE_PKS tuple length changed,
                    # so old keys don't have the namespace component.
                    if changed or table == "glossary_keywords":
                        new_key = _make_row_key(table, row["before"] if row["before"] else row["after"])
                        migrated_rows[new_key] = row
                    else:
                        migrated_rows[old_key] = row
                else:
                    migrated_rows[old_key] = row
            
            data["rows"] = migrated_rows
            return data
        return {"rows": {}}

    def _save(self, data: Dict[str, Any]):
        p = self._changeset_path
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Core: record with overwrite semantics
    # ------------------------------------------------------------------

    def record(
        self,
        table: str,
        row_before: Optional[Dict[str, Any]],
        row_after: Optional[Dict[str, Any]],
    ):
        """
        Record one row change.

        First touch: store both `before` and `after`.
        Subsequent: overwrite `after` only.
        """
        ref_row = row_before if row_before is not None else row_after
        if ref_row is None:
            return
        key = _make_row_key(table, ref_row)

        with self._lock:
            data = self._load()
            existing = data["rows"].get(key)

            if existing is not None:
                # Keep net-zero (before=None, after=None) rows until GC runs.
                # _gc_noop_creates() needs these anchors to sweep dependent
                # create-only rows (nodes/memories/edges) in the same changeset.
                existing["after"] = row_after
            else:
                data["rows"][key] = {
                    "table": table,
                    "before": row_before,
                    "after": row_after,
                }

            self._gc_noop_creates(data)
            if data.get("rows"):
                self._save(data)
            else:
                self._remove_changeset()

    def record_many(
        self,
        before_state: Dict[str, List[Dict[str, Any]]],
        after_state: Dict[str, List[Dict[str, Any]]],
    ):
        """
        Batch-record changes across multiple tables.

        Both arguments map table name -> list of row dicts.
        Rows in `before_state` only = DELETE.
        Rows in `after_state` only = INSERT.
        Rows in both = UPDATE (matched by PK).
        """
        with self._lock:
            data = self._load()

            all_tables = set(before_state.keys()) | set(after_state.keys())
            for table in all_tables:
                before_rows = {_make_row_key(table, r): r for r in before_state.get(table, [])}
                after_rows = {_make_row_key(table, r): r for r in after_state.get(table, [])}

                all_keys = set(before_rows.keys()) | set(after_rows.keys())
                for key in all_keys:
                    b = before_rows.get(key)
                    a = after_rows.get(key)

                    existing = data["rows"].get(key)
                    if existing is not None:
                        # Keep net-zero anchors for _gc_noop_creates().
                        existing["after"] = a
                    else:
                        data["rows"][key] = {
                            "table": table,
                            "before": b,
                            "after": a,
                        }

            self._gc_noop_creates(data)
            if data.get("rows"):
                self._save(data)
            else:
                self._remove_changeset()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_change_count(self) -> int:
        """Return the number of net-changed rows in the pool."""
        with self._lock:
            data = self._load()
        return len(self._changed_rows(data))

    def get_snapshot_view(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Return both the full dictionary of rows and the changed rows in a single atomic read.
        
        This prevents race conditions where changeset.json might be modified by another
        process between separate reads of the data.
        """
        with self._lock:
            data = self._load()
            all_rows = data.get("rows", {})
            changed_rows = self._changed_rows(data)
            return all_rows, changed_rows

    def remove_keys(self, keys: List[str]) -> int:
        """Remove specific tracked rows by their keys."""
        if not keys:
            return 0
            
        with self._lock:
            data = self._load()
            removed = 0
            for k in keys:
                if k in data["rows"]:
                    data["rows"].pop(k)
                    removed += 1
                    
            remaining = self._changed_rows(data)
            if not remaining:
                self._remove_changeset()
            elif removed > 0:
                self._save(data)
                
        return removed

    def clear_all(self) -> int:
        """Clear the entire changeset pool (integrate all)."""
        with self._lock:
            data = self._load()
            count = len(self._changed_rows(data))
            self._remove_changeset()
        return count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _changed_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        result = []
        for entry in data.get("rows", {}).values():
            if not _rows_equal(entry.get("table", ""), entry.get("before"), entry.get("after")):
                result.append(entry)
        return result

    @staticmethod
    def _gc_noop_creates(data: Dict[str, Any]) -> bool:
        """Remove create-then-delete no-ops and their orphaned dependents.

        A path that goes through create→delete in one changeset ends up
        with before=None, after=None (net-zero).  Related node/memory/edge
        entries created in the same changeset (before=None) lose their
        path mapping and become invisible to the review UI while still
        being counted as pending changes.  This sweeps them out.
        """
        rows = data.get("rows", {})
        if not rows:
            return False

        net_zero = {
            k for k, e in rows.items()
            if e.get("before") is None and e.get("after") is None
        }
        if not net_zero:
            return False

        # Collect node_uuids still reachable from surviving path entries,
        # and nodes that were newly created in this changeset.
        reachable = set()
        created_nodes = set()
        for key, entry in rows.items():
            if key.startswith("nodes:") and entry.get("before") is None:
                # The uuid can be reliably extracted from the key "nodes:<uuid>",
                # which handles both surviving created nodes (after is not None)
                # and net-zero created nodes (after is None).
                node_uuid = key.split(":", 1)[1]
                created_nodes.add(node_uuid)

            if key in net_zero or not key.startswith("paths:"):
                continue
            ref = entry.get("after") or entry.get("before")
            if not ref:
                continue
            edge_id = ref.get("edge_id")
            if edge_id is not None:
                ek = f"edges:{edge_id}"
                ee = rows.get(ek)
                if ee and ek not in net_zero:
                    er = ee.get("after") or ee.get("before")
                    if er and er.get("child_uuid"):
                        reachable.add(er["child_uuid"])
            if ref.get("node_uuid"):
                reachable.add(ref["node_uuid"])

        to_remove = set(net_zero)
        for key, entry in rows.items():
            if key in to_remove or entry.get("before") is not None:
                continue
            ref = entry.get("after")
            if not ref:
                continue

            if key.startswith("nodes:"):
                if ref.get("uuid") not in reachable:
                    to_remove.add(key)
            elif key.startswith("memories:"):
                node_uuid = ref.get("node_uuid")
                if node_uuid in created_nodes and node_uuid not in reachable:
                    to_remove.add(key)
            elif key.startswith("glossary_keywords:"):
                node_uuid = ref.get("node_uuid")
                if node_uuid in created_nodes and node_uuid not in reachable:
                    to_remove.add(key)
            elif key.startswith("edges:"):
                eid = ref.get("id")
                if not any(
                    k not in to_remove and k.startswith("paths:")
                    and ((rows[k].get("after") or rows[k].get("before") or {}).get("edge_id") == eid)
                    for k in rows
                ):
                    to_remove.add(key)

        for key in to_remove:
            rows.pop(key, None)
        return True

    def _remove_changeset(self):
        p = self._changeset_path
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except PermissionError:
            os.chmod(p, stat.S_IWRITE)
            os.remove(p)


# ---------------------------------------------------------------------------
# Global store instance
# ---------------------------------------------------------------------------
# All namespaces share a single changeset.json file to avoid complex rollback 
# races and treat all AI modifications as a unified set of changes.
# ---------------------------------------------------------------------------

_store: Optional[ChangesetStore] = None


def get_changeset_store() -> ChangesetStore:
    """Return the global ChangesetStore."""
    global _store
    if _store is None:
        _store = ChangesetStore()
    return _store
