#!/usr/bin/env python3
"""Hindsight backlog watchdog for digital-brain readiness.

Reports active backlog separately from historical failed rows. Non-zero failed
history is not itself a stop-the-line if the worker is currently completing work,
but active stuck/pending growth or new provider errors are.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import subprocess
from pathlib import Path

OUT_DIR = Path.home() / ".hermes" / "tasks" / "digital-brain-99-baselines"


def psql(query: str) -> list[str]:
    out = subprocess.check_output(["sudo", "-u", "postgres", "psql", "-d", "hindsight", "-tAc", query], text=True, stderr=subprocess.STDOUT, timeout=60)
    return [line for line in out.splitlines() if line and "could not change directory" not in line]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"timestamp": datetime.now(timezone.utc).isoformat()}
    units = psql("select count(*) total, count(consolidated_at) consolidated, count(consolidation_failed_at) failed, count(*)-count(consolidated_at)-count(consolidation_failed_at) unprocessed from memory_units;")[0]
    total, consolidated, failed, unprocessed = [int(x) for x in units.split("|")]
    report["memory_units"] = {"total": total, "consolidated": consolidated, "failed": failed, "unprocessed": unprocessed, "consolidated_ratio": consolidated / total if total else 0}
    async_rows = psql("select operation_type, status, count(*) from async_operations group by 1,2 order by 3 desc;")
    report["async_operations"] = async_rows
    active_rows = psql("select operation_id, operation_type, status, extract(epoch from (now()-created_at))::int age_seconds, extract(epoch from (now()-coalesce(claimed_at,updated_at,created_at)))::int active_seconds, left(coalesce(error_message,''),160) from async_operations where status in ('pending','processing') order by created_at asc limit 50;")
    report["active_operations"] = active_rows
    recent_errors = psql("select left(coalesce(error_message,''),160), count(*) from async_operations where status='failed' and updated_at > now() - interval '6 hours' group by 1 order by 2 desc limit 20;")
    report["recent_failed_errors_6h"] = recent_errors
    stop = []
    processing_older_than_2h = []
    for row in active_rows:
        parts = row.split("|")
        if len(parts) >= 5 and parts[2] == "processing" and int(parts[4]) > 7200:
            processing_older_than_2h.append(row)
    if processing_older_than_2h:
        stop.append({"reason": "processing_claim_older_than_2h", "rows": processing_older_than_2h[:5]})
    if any("str' object has no attribute 'choices" in row or "str object has no attribute choices" in row for row in recent_errors):
        stop.append({"reason": "new_string_response_provider_errors", "rows": recent_errors})
    report["status"] = "pass" if not stop else "fail"
    report["stop_the_line"] = stop
    out = OUT_DIR / f"hindsight-backlog-watchdog-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    print(json.dumps({"status": report["status"], "unprocessed": unprocessed, "consolidated_ratio": report["memory_units"]["consolidated_ratio"], "active": len(active_rows), "stop": stop}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
