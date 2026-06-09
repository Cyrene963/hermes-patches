"""Track Hindsight recall usage — updates access_count and last_accessed_at."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_batch: list[str] = []
_BATCH_SIZE = 50


def _env_file_value(path: Path, key: str) -> str:
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _database_url() -> str:
    return (
        os.environ.get("HINDSIGHT_API_DATABASE_URL")
        or _env_file_value(Path.home() / ".hindsight" / "profiles" / "hermes.env", "HINDSIGHT_API_DATABASE_URL")
        or _env_file_value(Path.home() / ".hermes" / ".env", "HINDSIGHT_API_DATABASE_URL")
    )


def record_recall(memory_ids: list[str]) -> None:
    """Record that these memory IDs were recalled."""
    if not memory_ids:
        return
    with _lock:
        _batch.extend(str(memory_id) for memory_id in memory_ids if memory_id)
        if _batch:
            _flush_locked()


def flush_pending() -> None:
    """Flush any pending access records."""
    with _lock:
        _flush_locked()


def _flush_locked() -> None:
    """Flush batched memory IDs to database. Caller must hold _lock."""
    global _batch
    if not _batch:
        return
    ids = sorted(set(_batch))
    _batch = []
    database_url = _database_url()
    if not database_url:
        logger.debug("Access tracker skipped: HINDSIGHT_API_DATABASE_URL not configured")
        return
    try:
        import psycopg2

        with psycopg2.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE memory_units
                    SET access_count = COALESCE(access_count, 0) + 1,
                        last_accessed_at = NOW()
                    WHERE id::text = ANY(%s)
                    """,
                    (ids,),
                )
                updated = cur.rowcount
        logger.debug("Access tracker: updated %d / %d recalled memories", updated, len(ids))
    except Exception as exc:
        logger.debug("Access tracker failed: %s", exc, exc_info=True)
