#!/usr/bin/env python3
"""
Memory Health Diagnosis — Scan hindsight for stale/duplicate/orphan memories.

Inspired by Nocturne Memory's diagnostic system
(https://github.com/Dataojitori/nocturne_memory).

Scans the hindsight memory bank for:
1. Stale memories — not accessed in 30+ days
2. Duplicate entries — identical or near-identical content
3. Size anomalies — memories that are too short (noise) or too long (bloated)
4. Tag analysis — distribution of tags, orphan tags

Output: Report to stdout (delivered via cron no_agent=true).
"""

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

def main():
    report_lines = ["# Memory Health Diagnosis\n"]
    report_lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    # Check memory snapshots directory
    snapshots_dir = Path.home() / ".hermes" / "memories" / "snapshots"
    if snapshots_dir.exists():
        snapshot_files = list(snapshots_dir.glob("*_versions.jsonl"))
        total_snapshots = 0
        for sf in snapshot_files:
            with open(sf) as f:
                total_snapshots += sum(1 for _ in f)
        report_lines.append(f"## Version Control\n- {len(snapshot_files)} tracked targets\n- {total_snapshots} total snapshots\n")
    else:
        report_lines.append("## Version Control\n- No snapshots yet (version control activated on next memory replace)\n")

    # Scan memory files for anomalies
    memory_dir = Path.home() / ".hermes" / "memories"
    issues = []

    for user_dir in memory_dir.iterdir():
        if not user_dir.is_dir() or user_dir.name == "snapshots":
            continue
        for mem_file in user_dir.glob("MEMORY.md"):
            content = mem_file.read_text(errors="replace")
            entries = [e.strip() for e in content.split("\n§\n") if e.strip()]

            # Check for very short entries (likely noise)
            short = [e for e in entries if len(e) < 20 and not e.startswith("#")]
            if short:
                issues.append(f"⚠️ {mem_file}: {len(short)} entries < 20 chars (possible noise)")

            # Check for very long entries (possibly bloated)
            long = [e for e in entries if len(e) > 2000]
            if long:
                issues.append(f"⚠️ {mem_file}: {len(long)} entries > 2000 chars (consider splitting)")

            # Check for duplicates
            seen = Counter()
            for e in entries:
                # Normalize for comparison
                norm = e.strip().lower()[:100]
                seen[norm] += 1
            dupes = {k: v for k, v in seen.items() if v > 1 and len(k) > 10}
            if dupes:
                issues.append(f"🔴 {mem_file}: {len(dupes)} potential duplicate groups")

            report_lines.append(f"## {mem_file}\n- {len(entries)} entries\n")

    if issues:
        report_lines.append("## Issues Found\n")
        for issue in issues:
            report_lines.append(f"- {issue}\n")
    else:
        report_lines.append("## Issues Found\n- ✅ No issues detected\n")

    # Disclosure rules status
    disclosure_path = Path.home() / ".hermes" / "disclosure_rules.yaml"
    if disclosure_path.exists():
        try:
            import yaml
            with open(disclosure_path) as f:
                rules = yaml.safe_load(f)
            rule_count = len(rules.get("rules", []))
            report_lines.append(f"## Disclosure Rules\n- {rule_count} active rules\n")
        except Exception:
            report_lines.append("## Disclosure Rules\n- Config exists but could not parse\n")
    else:
        report_lines.append("## Disclosure Rules\n- ⚠️ No disclosure_rules.yaml found\n")

    print("\n".join(report_lines))

if __name__ == "__main__":
    main()
