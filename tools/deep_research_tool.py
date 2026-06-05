#!/usr/bin/env python3
"""Hermes deep research tool.

This wraps the local non-invasive deep-research orchestrator as a first-class
Hermes tool so users can ask for research in natural language instead of running
shell commands themselves.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.registry import registry

DEFAULT_ORCHESTRATOR = Path.home() / ".hermes" / "scripts" / "hermes_deep_research_orchestrator.py"
MAX_QUERY_CHARS = 2000
MAX_URLS = 5
MAX_PREVIEW_CHARS = 6000
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\.\-]{12,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|token|authorization)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]


def _orchestrator_path() -> Path:
    configured = os.getenv("HERMES_DEEP_RESEARCH_ORCHESTRATOR", "").strip()
    return Path(configured) if configured else DEFAULT_ORCHESTRATOR


def _redact(text: str) -> str:
    out = text
    for pattern in SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def check_deep_research_requirements() -> bool:
    path = _orchestrator_path()
    return path.exists() and os.access(path, os.X_OK)


def _clean_budget(raw: Any) -> str:
    value = str(raw or "standard").strip().lower()
    if value not in {"fast", "quick", "standard", "deep"}:
        return "standard"
    return value


def _clean_timeout(raw: Any) -> int:
    try:
        return min(600, max(30, int(raw)))
    except Exception:
        return 180


def _clean_max_browser_urls(raw: Any) -> int:
    try:
        return min(MAX_URLS, max(0, int(raw)))
    except Exception:
        return 3


def _read_preview(manifest: dict[str, Any]) -> str:
    raw_files = manifest.get("files")
    files: dict[str, Any] = raw_files if isinstance(raw_files, dict) else {}
    evidence_path = files.get("evidence")
    if not evidence_path:
        return ""
    try:
        return _redact(Path(str(evidence_path)).read_text(encoding="utf-8", errors="ignore")[:MAX_PREVIEW_CHARS])
    except Exception:
        return ""


def _clean_mode(raw: Any) -> str:
    value = str(raw or "auto").strip().lower()
    if value in {"classic", "code_plan", "auto"}:
        return value
    return "auto"


def deep_research_tool(
    query: str,
    budget: str = "standard",
    browser_urls: list[str] | None = None,
    auto_browser: bool = True,
    max_browser_urls: int = 3,
    review: bool = False,
    timeout: int = 180,
    mode: str = "auto",
) -> str:
    query = str(query or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "query is required"}, ensure_ascii=False)
    if len(query) > MAX_QUERY_CHARS:
        query = query[:MAX_QUERY_CHARS]

    path = _orchestrator_path()
    if not check_deep_research_requirements():
        return json.dumps({
            "ok": False,
            "overall_status": "Degraded",
            "error": f"deep research orchestrator is unavailable or not executable: {path}",
        }, ensure_ascii=False)

    clean_urls = []
    for item in browser_urls or []:
        text = str(item or "").strip()
        if text and len(clean_urls) < MAX_URLS:
            clean_urls.append(text)

    timeout_s = _clean_timeout(timeout)
    requested_mode = _clean_mode(mode)
    cmd = [
        sys.executable,
        str(path),
        query,
        "--budget", _clean_budget(budget),
        "--max-browser-urls", str(_clean_max_browser_urls(max_browser_urls)),
        "--timeout", str(timeout_s),
        "--mode", requested_mode,
    ]
    if auto_browser:
        cmd.append("--auto-browser")
    if review:
        cmd.append("--review")
    for url in clean_urls:
        cmd.extend(["--browser-url", url])

    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_s + 30)
    except subprocess.TimeoutExpired:
        return json.dumps({
            "ok": False,
            "overall_status": "Degraded",
            "error": f"deep research timed out after {timeout_s}s",
        }, ensure_ascii=False)

    stdout = _redact(proc.stdout or "")
    stderr = _redact(proc.stderr or "")
    try:
        manifest = json.loads(stdout)
    except json.JSONDecodeError:
        return json.dumps({
            "ok": False,
            "overall_status": "Degraded",
            "exit_code": proc.returncode,
            "error": "orchestrator did not return JSON",
            "stdout_preview": stdout[:2000],
            "stderr_preview": stderr[:2000],
        }, ensure_ascii=False)

    status = manifest.get("overall_status") or ("Verified working" if proc.returncode == 0 else "Degraded")
    result = {
        "ok": status in {"Verified working", "Partially verified"},
        "overall_status": status,
        "query": manifest.get("query"),
        "run_dir": manifest.get("run_dir"),
        "smart_search_ok": manifest.get("smart_search_ok"),
        "smart_search_budget": manifest.get("smart_search_budget"),
        "smart_search_mode": manifest.get("smart_search_mode"),
        "retrieval_lanes": manifest.get("retrieval_lanes"),
        "browser_ok_count": manifest.get("browser_ok_count"),
        "reviewer": manifest.get("reviewer"),
        "search_as_code": manifest.get("search_as_code"),
        "classic_smart_search": manifest.get("classic_smart_search"),
        "files": manifest.get("files"),
        "evidence_preview": _read_preview(manifest),
    }
    if proc.returncode != 0 and stderr:
        result["stderr_preview"] = stderr[:2000]
    return json.dumps(result, ensure_ascii=False, indent=2)


DEEP_RESEARCH_SCHEMA = {
    "name": "deep_research",
    "description": (
        "Run Hermes' agentic deep-research pipeline from a natural-language query. "
        "Use this when the user asks for serious web research, current facts, source-backed analysis, "
        "or pages that may need browser escalation. The tool plans with smart-search, can escalate to "
        "the configured browser/CloakBrowser path, writes evidence and manifest artifacts, and can run "
        "an optional reviewer lane when review=true and GROK_API_KEY is available."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The research question or information need."
            },
            "budget": {
                "type": "string",
                "enum": ["fast", "quick", "standard", "deep"],
                "default": "standard",
                "description": "Research depth. fast is accepted as a user-friendly alias for quick."
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "classic", "code_plan"],
                "default": "auto",
                "description": "auto prefers the restricted Search-as-Code evidence sidecar and falls back to classic on failure; classic runs existing smart-search/browser pipeline; code_plan requires Search-as-Code as the primary retrieval layer."
            },
            "browser_urls": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_URLS,
                "description": "Known URLs to fetch through the browser escalation lane."
            },
            "auto_browser": {
                "type": "boolean",
                "default": True,
                "description": "Whether to browser-fetch URLs discovered by the research planner."
            },
            "max_browser_urls": {
                "type": "integer",
                "default": 3,
                "minimum": 0,
                "maximum": MAX_URLS,
                "description": "Maximum number of pages to fetch through browser escalation."
            },
            "review": {
                "type": "boolean",
                "default": False,
                "description": "Run the optional reviewer lane if configured. Fails closed when the key is absent."
            },
            "timeout": {
                "type": "integer",
                "default": 180,
                "minimum": 30,
                "maximum": 600,
                "description": "Timeout in seconds for the research pass."
            }
        },
        "required": ["query"]
    }
}


registry.register(
    name="deep_research",
    toolset="web",
    schema=DEEP_RESEARCH_SCHEMA,
    handler=lambda args, **kw: deep_research_tool(
        query=args.get("query", ""),
        budget=args.get("budget", "standard"),
        browser_urls=args.get("browser_urls") if isinstance(args.get("browser_urls"), list) else [],
        auto_browser=args.get("auto_browser", True),
        max_browser_urls=args.get("max_browser_urls", 3),
        review=args.get("review", False),
        timeout=args.get("timeout", 180),
        mode=args.get("mode", "auto"),
    ),
    check_fn=check_deep_research_requirements,
    emoji="🔎",
    max_result_size_chars=100_000,
)
