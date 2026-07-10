#!/usr/bin/env python3
"""Daily Memory OS health regression against the configured owner namespace."""
import datetime
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import yaml

LOG_DIR = Path.home() / ".hermes" / "logs" / "memory_regression"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _default_namespace():
    try:
        cfg = yaml.safe_load((Path.home() / ".hermes" / "config.yaml").read_text()) or {}
        user_id = str((cfg.get("memory_graph") or {}).get("default_terminal_user") or "").strip()
        return f"telegram:{user_id}" if user_id else ""
    except Exception:
        return ""


NAMESPACE = _default_namespace()


def _quote(value):
    return str(value).replace("'", "''")


def sql(query):
    result = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-d", "hindsight", "-t", "-A", "-c", query],
        capture_output=True, text=True, timeout=10, cwd="/tmp",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "psql failed")
    return result.stdout.strip()


def positive_count(query):
    value = sql(query)
    return bool(value and int(value) > 0)


def test_namespace_configured():
    return bool(NAMESPACE)


def test_private_paths():
    return positive_count(f"SELECT COUNT(*) FROM mg_paths WHERE namespace = '{_quote(NAMESPACE)}'")


def test_private_documents():
    return positive_count(f"SELECT COUNT(*) FROM mg_search_documents WHERE namespace = '{_quote(NAMESPACE)}'")


def test_memory_rules_file():
    path = Path.home() / ".hermes" / "memories" / "MEMORY.md"
    return path.is_file() and path.stat().st_size > 0


def test_unknown_canary():
    marker = "__memory_regression_unknown_fact_7f3c9a__"
    return not positive_count(
        "SELECT COUNT(*) FROM mg_search_documents "
        f"WHERE namespace = '{_quote(NAMESPACE)}' AND content ILIKE '%{marker}%'"
    )


def test_graph_tables():
    return all(positive_count(f"SELECT COUNT(*) FROM {table}") for table in ("mg_nodes", "mg_memories", "mg_paths"))


def test_search_index():
    return positive_count("SELECT COUNT(*) FROM mg_search_documents")


def test_glossary():
    return positive_count("SELECT COUNT(*) FROM mg_glossary_keywords")


def test_hindsight_health():
    try:
        return urllib.request.urlopen("http://localhost:9177/health", timeout=5).status == 200
    except Exception:
        return False


def test_namespace_isolation():
    if not NAMESPACE:
        return False
    private_count = positive_count(f"SELECT COUNT(*) FROM mg_paths WHERE namespace = '{_quote(NAMESPACE)}'")
    other_count = positive_count(f"SELECT COUNT(*) FROM mg_paths WHERE namespace <> '{_quote(NAMESPACE)}'")
    return private_count and other_count


def run_tests():
    tests = [
        ("namespace_configured", test_namespace_configured),
        ("private_paths", test_private_paths),
        ("private_search_documents", test_private_documents),
        ("memory_rules_file", test_memory_rules_file),
        ("unknown_canary", test_unknown_canary),
        ("graph_tables", test_graph_tables),
        ("search_index", test_search_index),
        ("glossary", test_glossary),
        ("hindsight_health", test_hindsight_health),
        ("namespace_isolation", test_namespace_isolation),
    ]
    rows = []
    for name, function in tests:
        started = time.time()
        error = None
        try:
            passed = function()
        except Exception as exc:
            passed, error = False, f"{type(exc).__name__}: {exc}"
        row = {"name": name, "pass": bool(passed), "latency_ms": int((time.time() - started) * 1000)}
        if error:
            row["error"] = error
        rows.append(row)
    passed_count = sum(1 for row in rows if row["pass"])
    report = {
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "namespace_configured": bool(NAMESPACE),
        "tests": rows,
        "total": len(rows),
        "passed": passed_count,
        "failed": len(rows) - passed_count,
        "pass_rate": round(passed_count / len(rows), 2) if rows else 0,
    }
    (LOG_DIR / f"{report['date']}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    result = run_tests()
    raise SystemExit(0 if result["failed"] == 0 else 1)
