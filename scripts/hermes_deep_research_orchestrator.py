#!/usr/bin/env python3
"""Hermes unified deep-research orchestrator.

This script stitches together the local smart-search planner, optional browser
escalation through the configured CloakBrowser/Chromium executable, and an
optional Grok/OpenAI-compatible reviewer lane. Secrets are read from environment
only and redacted from all saved output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\.\-]{12,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|token|authorization)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
DEFAULT_OUTPUT_ROOT = HERMES_HOME / "tasks" / "deep-research-runs"
GROK_REVIEWER = HERMES_HOME / "scripts" / "grok_research_reviewer.py"
SEARCH_AS_CODE_RUNNER = Path(os.getenv("HERMES_SEARCH_AS_CODE_RUNNER", str(HERMES_HOME / "scripts" / "hermes_search_as_code_research.py")))
HERMES_ENV = Path(os.getenv("HERMES_ENV_FILE", str(HERMES_HOME / ".env")))
SMART_SEARCH_BUDGET_ALIASES = {"fast": "quick", "quick": "quick", "standard": "standard", "deep": "deep"}


def load_env_defaults() -> None:
    """Load non-secret runtime defaults from Hermes .env when not already set."""
    if not HERMES_ENV.exists():
        return
    allowed = {"AGENT_BROWSER_EXECUTABLE_PATH"}
    for raw in HERMES_ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed or os.getenv(key):
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def redact(text: str) -> str:
    out = text
    for pattern in SECRET_PATTERNS:
        out = pattern.sub(lambda m: m.group(0).split("=")[0] + "=[REDACTED]" if "=" in m.group(0) else "[REDACTED]", out)
    return out


def slugify(value: str, limit: int = 48) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = cleaned.strip("-._") or "research"
    return cleaned[:limit]


def safe_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    if re.match(r"^(10|127|169\.254|172\.(1[6-9]|2\d|3[01])|192\.168)\.", host):
        return False
    if SECRET_PATTERNS[0].search(url) or SECRET_PATTERNS[2].search(url):
        return False
    return True


def run_command(cmd: list[str], timeout: int, cwd: str | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    return proc.returncode, redact(proc.stdout), redact(proc.stderr)


def smart_search_deep(query: str, budget: str, timeout: int) -> dict[str, Any]:
    resolved_budget = SMART_SEARCH_BUDGET_ALIASES.get(budget, budget)
    cmd = ["smart-search", "deep", query, "--budget", resolved_budget, "--format", "json"]
    try:
        code, stdout, stderr = run_command(cmd, timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "budget": resolved_budget, "error_type": "missing_binary", "error": "smart-search command not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "budget": resolved_budget, "error_type": "timeout", "error": f"smart-search timed out after {timeout}s"}
    if code != 0:
        return {"ok": False, "budget": resolved_budget, "error_type": "process_error", "error": stderr or stdout, "exit_code": code}
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "budget": resolved_budget, "error_type": "json_error", "error": str(exc), "raw": stdout[:4000]}
    if isinstance(data, dict):
        data.setdefault("ok", True)
        data.setdefault("budget", resolved_budget)
    return data


def run_search_as_code(query: str, timeout: int, output_root: str | None = None) -> dict[str, Any]:
    """Run the restricted Search-as-Code evidence sidecar and return its manifest.

    The sidecar is intentionally a subprocess: it executes only a statically
    checked Python retrieval plan with whitelisted SDK primitives, keeping
    generated-code experimentation out of the gateway process.
    """
    if not SEARCH_AS_CODE_RUNNER.exists():
        return {"ok": False, "error_type": "missing_runner", "error": str(SEARCH_AS_CODE_RUNNER)}
    cmd = [sys.executable, str(SEARCH_AS_CODE_RUNNER), query, "--timeout", str(max(30, timeout))]
    if output_root:
        cmd.extend(["--output-root", output_root])
    try:
        code, stdout, stderr = run_command(cmd, timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_type": "timeout", "error": f"Search-as-Code runner timed out after {timeout}s"}
    try:
        manifest = json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error_type": "json_error", "error": "Search-as-Code runner did not return JSON", "stdout": stdout[:2000], "stderr": stderr[:2000], "exit_code": code}
    manifest["ok"] = code == 0 and manifest.get("overall_status") == "Verified working"
    if stderr:
        manifest["stderr"] = stderr[:2000]
    manifest["exit_code"] = code
    return manifest

def source_health_from_manifest(manifest: dict[str, Any]) -> dict[str, int]:
    """Return a small, comparable source-health summary for any retrieval lane."""
    raw = manifest.get("source_health") if isinstance(manifest.get("source_health"), dict) else {}
    return {
        "source_count": int(manifest.get("source_count") or raw.get("source_count") or 0),
        "with_content": int(raw.get("with_content") or 0),
        "with_error": int(raw.get("with_error") or 0),
        "primary_like": int(raw.get("primary_like") or 0),
    }


def lane_is_healthy(manifest: dict[str, Any], *, min_sources: int = 2, min_with_content: int = 1) -> bool:
    if not manifest.get("ok"):
        return False
    health = source_health_from_manifest(manifest)
    # A lane with extraction/provider errors is usable evidence, but not healthy
    # enough to be the only lane in auto mode. Run an independent complement so
    # bad/provider-error artifacts do not silently pass as “perfectly usable”.
    if health["with_error"] > 0:
        return False
    return health["source_count"] >= min_sources and health["with_content"] >= min_with_content


def should_run_classic_complement(code_plan: dict[str, Any], budget: str) -> bool:
    """Decide whether classic smart-search adds necessary independent coverage.

    Search-as-Code is the structured evidence builder. Classic smart-search is
    useful as an independent planning/retrieval lane, especially for standard
    and deep research. Fast/quick budgets avoid extra work unless the primary
    lane is shallow or failed.
    """
    if budget in {"standard", "deep"}:
        return True
    return not lane_is_healthy(code_plan, min_sources=2, min_with_content=1)


def build_unified_retrieval_state(query: str, budget: str, mode: str, timeout: int, output_root: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run the necessary retrieval lanes and return (smart_state, code_plan, classic).

    The architecture is intentionally additive rather than a bag of features:
    - Search-as-Code creates executable, inspectable evidence programs.
    - Classic smart-search provides an independent broad-retrieval/planning lane.
    - Auto mode composes them when the budget justifies it or when one lane is
      shallow, so users get graceful degradation without hiding weak evidence.
    """
    code_plan: dict[str, Any] = {"skipped": True, "reason": "mode is classic"}
    classic: dict[str, Any] = {"skipped": True, "reason": "mode is code_plan"}

    if mode == "classic":
        classic = smart_search_deep(query, budget, timeout)
        classic.setdefault("mode", "classic")
        return classic, code_plan, classic

    code_plan_root = str(Path(output_root) / "code-plan-runs")
    code_plan = run_search_as_code(query, timeout, output_root=code_plan_root)

    if mode == "code_plan":
        smart = {
            "ok": bool(code_plan.get("ok")),
            "budget": budget,
            "mode": "code_plan",
            "source_count": code_plan.get("source_count"),
            "source_health": code_plan.get("source_health"),
            "files": code_plan.get("files"),
            "run_dir": code_plan.get("run_dir"),
            "error": code_plan.get("error"),
            "error_type": code_plan.get("error_type"),
        }
        return smart, code_plan, classic

    # Unified auto mode. Code-plan is primary; classic is a complementary lane
    # when the budget warrants independent coverage or code-plan is shallow.
    if should_run_classic_complement(code_plan, budget):
        classic = smart_search_deep(query, budget, timeout)
        classic.setdefault("mode", "classic_complement")

    lanes = {
        "search_as_code": {
            "ok": bool(code_plan.get("ok")),
            "status": code_plan.get("overall_status"),
            "health": source_health_from_manifest(code_plan),
            "run_dir": code_plan.get("run_dir"),
        },
        "classic_smart_search": {
            "ok": bool(classic.get("ok")),
            "status": "skipped" if classic.get("skipped") else ("Verified working" if classic.get("ok") else "Degraded"),
            "budget": classic.get("budget", budget),
            "error_type": classic.get("error_type"),
        },
    }
    smart = {
        "ok": bool(code_plan.get("ok") or classic.get("ok")),
        "budget": budget,
        "mode": "unified_auto",
        "lanes": lanes,
        "source_count": code_plan.get("source_count"),
        "source_health": code_plan.get("source_health"),
        "files": code_plan.get("files"),
        "run_dir": code_plan.get("run_dir"),
    }
    if classic.get("ok"):
        smart["classic_smart_search"] = classic
    if not code_plan.get("ok"):
        smart["code_plan_fallback_reason"] = {
            "error_type": code_plan.get("error_type"),
            "error": code_plan.get("error"),
            "overall_status": code_plan.get("overall_status"),
        }
    return smart, code_plan, classic


def overall_status(smart: dict[str, Any], browser_results: list[dict[str, Any]], reviewer: dict[str, Any]) -> str:
    smart_ok = bool(smart.get("ok"))
    browser_requested = bool(browser_results)
    browser_ok = any(r.get("ok") for r in browser_results)
    reviewer_failed = reviewer.get("ok") is False and not reviewer.get("skipped")
    if smart_ok and (not browser_requested or browser_ok) and not reviewer_failed:
        return "Verified working"
    if smart_ok or browser_ok:
        return "Partially verified"
    return "Degraded"


def collect_urls(data: dict[str, Any], limit: int) -> list[str]:
    urls: list[str] = []

    def walk(obj: Any) -> None:
        if len(urls) >= limit:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in {"url", "link", "source_url"} and isinstance(value, str) and safe_url(value):
                    if value not in urls:
                        urls.append(value)
                else:
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return urls[:limit]


async def browser_fetch(url: str, timeout_ms: int) -> dict[str, Any]:
    if not safe_url(url):
        return {"url": url, "ok": False, "error": "unsafe_url_blocked"}
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        return {"url": url, "ok": False, "error": f"playwright_unavailable: {type(exc).__name__}: {exc}"}

    executable = os.getenv("AGENT_BROWSER_EXECUTABLE_PATH") or None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=executable, headless=True)
            page = await browser.new_page()
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                title = await page.title()
                text = await page.locator("body").inner_text(timeout=timeout_ms)
                return {
                    "url": url,
                    "ok": True,
                    "status": response.status if response else None,
                    "title": title,
                    "text": text[:20000],
                    "chars": len(text),
                    "browser_executable": executable or "playwright-default",
                }
            except Exception as exc:
                return {"url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            finally:
                await browser.close()
    except Exception as exc:
        return {"url": url, "ok": False, "error": f"browser_launch_failed: {type(exc).__name__}: {exc}"}


def build_evidence_markdown(
    query: str,
    smart: dict[str, Any],
    browser_results: list[dict[str, Any]],
    generated_at: str,
) -> str:
    lines = [
        f"# Hermes Deep Research Evidence Pack",
        "",
        f"Generated: {generated_at}",
        f"Query: {query}",
        "",
        "## Status Labels",
        "",
        f"- smart-search: {'Verified working' if smart.get('ok') else 'Degraded'}",
        f"- browser escalation: {'Verified working' if any(r.get('ok') for r in browser_results) else ('Partially verified' if browser_results else 'Not requested')}",
        "- reviewer lane: Optional; only runs when --review is set and GROK_API_KEY exists.",
        "",
        "## Smart Search Result",
        "",
        "```json",
        json.dumps(smart, ensure_ascii=False, indent=2)[:50000],
        "```",
        "",
    ]
    if browser_results:
        lines.extend(["## Browser Escalation", ""])
        for item in browser_results:
            lines.extend([
                f"### {item.get('url')}",
                "",
                f"- ok: {item.get('ok')}",
                f"- status: {item.get('status')}",
                f"- title: {item.get('title', '')}",
                f"- chars: {item.get('chars', 0)}",
                "",
                "```text",
                str(item.get("text") or item.get("error") or "")[:12000],
                "```",
                "",
            ])
    return redact("\n".join(lines))


def run_reviewer(evidence_path: Path, timeout: int) -> dict[str, Any]:
    if not GROK_REVIEWER.exists():
        return {"ok": False, "error_type": "missing_reviewer", "error": str(GROK_REVIEWER)}
    if not os.getenv("GROK_API_KEY"):
        return {"ok": False, "error_type": "missing_key", "error": "GROK_API_KEY is not set"}
    try:
        code, stdout, stderr = run_command([str(GROK_REVIEWER), str(evidence_path)], timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_type": "timeout", "error": f"reviewer timed out after {timeout}s"}
    return {"ok": code == 0, "exit_code": code, "stdout": stdout, "stderr": stderr}


def main() -> int:
    load_env_defaults()
    parser = argparse.ArgumentParser(description="Run a unified Hermes deep-research evidence pass.")
    parser.add_argument("query", help="Research query")
    parser.add_argument("--budget", default="standard", choices=sorted(SMART_SEARCH_BUDGET_ALIASES), help="Research budget. 'fast' is accepted as an alias for smart-search 'quick'.")
    parser.add_argument("--mode", default="auto", choices=["auto", "classic", "code_plan"], help="auto tries the restricted Search-as-Code evidence sidecar first and falls back to classic smart-search; classic uses smart-search deep; code_plan requires Search-as-Code as the primary retrieval layer.")
    parser.add_argument("--browser-url", action="append", default=[], help="URL to fetch via configured browser escalation")
    parser.add_argument("--auto-browser", action="store_true", help="Browser-fetch URLs discovered from smart-search output")
    parser.add_argument("--max-browser-urls", type=int, default=3)
    parser.add_argument("--review", action="store_true", help="Run optional Grok reviewer lane")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--browser-timeout-ms", type=int, default=45000)
    args = parser.parse_args()

    generated_at = datetime.now(timezone.utc).isoformat()
    run_dir = Path(args.output_root) / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slugify(args.query)}"
    run_dir.mkdir(parents=True, exist_ok=True)

    smart, code_plan, classic = build_unified_retrieval_state(
        args.query, args.budget, args.mode, args.timeout, args.output_root
    )
    urls = list(dict.fromkeys([u for u in args.browser_url if safe_url(u)]))
    if args.auto_browser:
        urls.extend(u for u in collect_urls(smart, args.max_browser_urls) if u not in urls)
    urls = urls[: max(0, args.max_browser_urls)]

    browser_results: list[dict[str, Any]] = []
    if urls:
        async def fetch_all() -> list[dict[str, Any]]:
            return await asyncio.gather(*(browser_fetch(u, args.browser_timeout_ms) for u in urls))
        browser_results = asyncio.run(fetch_all())

    evidence = build_evidence_markdown(args.query, smart, browser_results, generated_at)
    evidence_path = run_dir / "evidence.md"
    evidence_path.write_text(evidence, encoding="utf-8")

    reviewer = {"ok": False, "skipped": True, "reason": "--review not set"}
    if args.review:
        reviewer = run_reviewer(evidence_path, args.timeout)
        (run_dir / "reviewer.json").write_text(
            redact(json.dumps(reviewer, ensure_ascii=False, indent=2)), encoding="utf-8"
        )
        if reviewer.get("stdout"):
            (run_dir / "reviewer.md").write_text(redact(str(reviewer["stdout"])), encoding="utf-8")

    manifest = {
        "query": args.query,
        "generated_at": generated_at,
        "run_dir": str(run_dir),
        "overall_status": overall_status(smart, browser_results, reviewer),
        "smart_search_ok": bool(smart.get("ok")),
        "smart_search_budget": smart.get("budget"),
        "smart_search_mode": smart.get("mode"),
        "retrieval_lanes": smart.get("lanes"),
        "search_as_code": {k: v for k, v in code_plan.items() if k not in {"stdout", "stderr"}},
        "classic_smart_search": {k: v for k, v in classic.items() if k not in {"stdout", "stderr", "raw"}},
        "browser_urls": urls,
        "browser_ok_count": sum(1 for item in browser_results if item.get("ok")),
        "reviewer": {k: v for k, v in reviewer.items() if k not in {"stdout", "stderr"}},
        "files": {
            "evidence": str(evidence_path),
            "manifest": str(run_dir / "manifest.json"),
        },
    }
    (run_dir / "manifest.json").write_text(
        redact(json.dumps(manifest, ensure_ascii=False, indent=2)), encoding="utf-8"
    )

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["overall_status"] in {"Verified working", "Partially verified"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
