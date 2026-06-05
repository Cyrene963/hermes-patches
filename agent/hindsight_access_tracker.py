"""Track Hindsight recall usage — updates access_count and last_accessed_at."""

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_batch = []  # Collect memory IDs to update in batches
_BATCH_SIZE = 50


def record_recall(memory_ids: list[str]) -> None:
    """Record that these memory IDs were recalled. Batched for efficiency."""
    if not memory_ids:
        return
    with _lock:
        _batch.extend(memory_ids)
        if len(_batch) >= _BATCH_SIZE:
            _flush()


def _flush():
    """Flush batched memory IDs to database."""
    global _batch
    if not _batch:
        return
    ids = list(set(_batch))  # deduplicate
    _batch = []
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='127.0.0.1', dbname='hindsight',
            user='postgres', password='postgres'
        )
        cur = conn.cursor()
        # Update access_count and last_accessed_at
        cur.execute("""
            UPDATE memory_units
            SET access_count = COALESCE(access_count, 0) + 1,
                last_accessed_at = NOW()
            WHERE id::text = ANY(%s)
        """, (ids,))
        updated = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        logger.debug("Access tracker: updated %d / %d recalled memories", updated, len(ids))
    except Exception as e:
        logger.debug("Access tracker failed: %s", e)
