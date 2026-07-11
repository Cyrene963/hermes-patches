#!/usr/bin/env python3
"""Verify cross-day correction replay promotion; silent only on full evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

base = Path(
    os.environ.get("MEMORY_OS_BASELINE_DIR")
    or (Path.home() / ".hermes" / "tasks" / "digital-brain-99-baselines")
)
history = base / "correction-regression-history"
result_path = base / "memory-os-scorecard-result.json"
valid = []
for path in sorted(history.glob("????-??-??.json")):
    try:
        item = json.loads(path.read_text())
    except Exception:
        continue
    if item.get("date") != path.stem:
        continue
    if item.get("total", 0) > 0 and item.get("failed") == 0 and item.get("invalid") == 0:
        valid.append(path.stem)
try:
    result = json.loads(result_path.read_text())
except Exception:
    result = {}
if len(valid) >= 2 and result.get("passed_gates") == result.get("total_gates") == 41:
    raise SystemExit(0)
print(
    "Memory OS cross-day replay promotion incomplete: "
    f"valid_days={len(valid)} passed_gates={result.get('passed_gates')} "
    f"total_gates={result.get('total_gates')}"
)
raise SystemExit(1)
