#!/usr/bin/env python3
"""Memory Graph lifecycle/conflict canary.

Creates a temporary memory, updates it to a newer value, verifies read/search prefer
the current value, then deletes the canary subtree. This proves lifecycle update
semantics are exercised instead of only checking service health.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import subprocess
import sys
from pathlib import Path


def run_py(code: str) -> str:
    proc = subprocess.run(
        [str(Path(os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent"))) / "venv" / "bin" / "python"), "-c", code],
        cwd=os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")),
        text=True,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    title = f"lifecycle_canary_{stamp}"
    old_value = f"old_value_{stamp}_deprecated"
    new_value = f"new_value_{stamp}_current"
    create_code = f'''
import json
import tools.memory_graph_tool as mg
print(mg._create({{"domain":"core","parent_uri":"core://测试/生命周期临时","title":{title!r},"content":{old_value!r},"priority":0}}))
'''
    created = json.loads(run_py(create_code))
    uri = created.get("uri") or created.get("path") or created.get("node", {}).get("uri")
    if not uri:
        raise RuntimeError(f"create returned no uri: {created}")
    try:
        update_code = f'''
import json
import tools.memory_graph_tool as mg
print(mg._update({{"domain":"core","uri":{uri!r},"content":{new_value!r},"priority":0}}))
'''
        updated = json.loads(run_py(update_code))
        read_code = f'''
import tools.memory_graph_tool as mg
print(mg._read({{"domain":"core","uri":{uri!r}}}))
'''
        read = json.loads(run_py(read_code))
        read_text = json.dumps(read, ensure_ascii=False)
        search_code = f'''
import tools.memory_graph_tool as mg
print(mg._search({{"query":{new_value!r},"limit":5,"domain":"core"}}))
'''
        search_new = json.loads(run_py(search_code))
        search_new_text = json.dumps(search_new, ensure_ascii=False)
        search_old_code = f'''
import tools.memory_graph_tool as mg
print(mg._search({{"query":{old_value!r},"limit":5,"domain":"core"}}))
'''
        search_old = json.loads(run_py(search_old_code))
        search_old_text = json.dumps(search_old, ensure_ascii=False)
        checks = {
            "read_has_new": new_value in read_text,
            "read_hides_old": old_value not in read_text,
            "search_new_finds_uri": uri in search_new_text,
            "search_old_not_current_top": not (search_old.get("results") and search_old["results"][0].get("uri") == uri and old_value in json.dumps(search_old["results"][0], ensure_ascii=False)),
        }
        status = "pass" if all(checks.values()) else "fail"
        print(json.dumps({"status": status, "uri": uri, "checks": checks, "updated": updated}, ensure_ascii=False))
        return 0 if status == "pass" else 2
    finally:
        delete_code = f'''
import tools.memory_graph_tool as mg
print(mg._delete({{"domain":"core","uri":{uri!r}}}))
'''
        try:
            run_py(delete_code)
        except Exception as exc:
            print(json.dumps({"cleanup_error": str(exc), "uri": uri}, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
