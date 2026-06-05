#!/usr/bin/env python3
"""Experimental Search-as-Code deep research runner for Hermes.

This is an MVP sandbox for testing the architecture before wiring it into the
Hermes tool surface. It executes a restricted Python retrieval plan against a
small SDK of approved primitives, saves the generated/executed plan, raw data,
and evidence pack, and supports offline fixtures for deterministic tests.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import html
import urllib.request
from html.parser import HTMLParser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
HERMES_REPO = Path(os.getenv("HERMES_REPO", str(HERMES_HOME / "hermes-agent")))
if HERMES_REPO.exists() and str(HERMES_REPO) not in sys.path:
    sys.path.insert(0, str(HERMES_REPO))

DEFAULT_OUTPUT_ROOT = Path(os.getenv("HERMES_SAC_OUTPUT_ROOT", str(HERMES_HOME / "tasks" / "search-as-code-runs")))
MAX_QUERY_CHARS = 500
MAX_RESULTS_PER_QUERY = 10
MAX_URLS_TO_EXTRACT = 12
MAX_PLAN_CHARS = 20000

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\.\-]{12,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|token|authorization)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]

PRIMARY_SOURCE_HINTS = (
    ".gov", ".edu", "arxiv.org", "github.com", "research.", "docs.", "developer.", "blog.",
)

SAFE_BUILTINS = {
    "len": len,
    "range": range,
    "min": min,
    "max": max,
    "sum": sum,
    "sorted": sorted,
    "enumerate": enumerate,
    "list": list,
    "dict": dict,
    "set": set,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "any": any,
    "all": all,
    "zip": zip,
}

FORBIDDEN_AST = (
    ast.Import,
    ast.ImportFrom,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Raise,
    ast.Global,
    ast.Nonlocal,
    ast.ClassDef,
    ast.Lambda,
)
FORBIDDEN_CALL_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "getattr", "setattr", "delattr", "globals", "locals", "vars",
}
FORBIDDEN_ATTR_PREFIXES = ("__",)
FORBIDDEN_ATTR_NAMES = {"system", "popen", "spawn", "remove", "unlink", "rmdir", "mkdir", "write", "read"}


def redact(text: str) -> str:
    out = text
    for pattern in SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def slugify(value: str, limit: int = 54) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = cleaned.strip("-._") or "research"
    return cleaned[:limit]


def safe_url(url: str) -> bool:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    if re.match(r"^(10|127|169\.254|172\.(1[6-9]|2\d|3[01])|192\.168)\.", host):
        return False
    if any(p.search(url) for p in SECRET_PATTERNS):
        return False
    return True


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


@dataclass
class SourceItem:
    url: str
    title: str = ""
    description: str = ""
    query: str = ""
    source: str = "search"
    content: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": stable_id(self.url, self.title),
            "url": self.url,
            "title": self.title,
            "description": self.description,
            "query": self.query,
            "source": self.source,
            "content": self.content[:12000],
            "score": self.score,
            "metadata": self.metadata,
        }


class PlanSecurityError(ValueError):
    pass


def validate_plan_ast(code: str) -> None:
    if len(code) > MAX_PLAN_CHARS:
        raise PlanSecurityError(f"plan too large: {len(code)} chars")
    tree = ast.parse(code, mode="exec")
    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_AST):
            raise PlanSecurityError(f"forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALL_NAMES:
                raise PlanSecurityError(f"forbidden call: {func.id}")
            if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_ATTR_NAMES:
                raise PlanSecurityError(f"forbidden attribute call: {func.attr}")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith(FORBIDDEN_ATTR_PREFIXES):
                raise PlanSecurityError(f"forbidden dunder attribute: {node.attr}")


class SearchSDK:
    """Approved retrieval primitives exposed to Search-as-Code plans."""

    def __init__(self, *, fixture: dict[str, Any] | None = None, timeout: int = 60):
        self.fixture = fixture or {}
        self.timeout = timeout
        self.events: list[dict[str, Any]] = []

    def _record(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append({"kind": kind, "payload": payload, "ts": datetime.now(timezone.utc).isoformat()})

    async def search_web(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query = str(query or "").strip()[:MAX_QUERY_CHARS]
        limit = min(MAX_RESULTS_PER_QUERY, max(1, int(limit or 5)))
        self._record("search_web", {"query": query, "limit": limit})
        fixture_search = self.fixture.get("search", {})
        if query in fixture_search:
            return fixture_search[query][:limit]
        cmd = ["smart-search", "search", query, "--validation", "balanced", "--format", "json"]
        proc = await asyncio.to_thread(subprocess.run, cmd, text=True, capture_output=True, timeout=self.timeout)
        if proc.returncode != 0:
            fallback = await self._fallback_web_search(query, limit)
            if fallback:
                return fallback
            return [{"error": redact(proc.stderr or proc.stdout), "query": query}]
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            fallback = await self._fallback_web_search(query, limit)
            if fallback:
                return fallback
            return [{"error": "smart-search returned non-json", "query": query, "raw": redact(proc.stdout[:1000])}]
        items = []
        for obj in _walk_dicts(data):
            url = obj.get("url") or obj.get("link") or obj.get("source_url")
            if isinstance(url, str) and safe_url(url):
                items.append({
                    "url": url,
                    "title": str(obj.get("title") or ""),
                    "description": str(obj.get("description") or obj.get("snippet") or obj.get("content") or "")[:2000],
                    "query": query,
                })
            if len(items) >= limit:
                break
        if not items:
            fallback = await self._fallback_web_search(query, limit)
            if fallback:
                return fallback
            if isinstance(data, dict) and data.get("ok") is False:
                return [{"error": redact(json.dumps(data, ensure_ascii=False)[:4000]), "query": query}]
        return items

    async def _fallback_web_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Fallback through Hermes' configured web_search tool when smart-search is unavailable/degraded."""
        self._record("fallback_web_search", {"query": query, "limit": limit})
        try:
            from tools.web_tools import web_search_tool
            raw = await asyncio.to_thread(web_search_tool, query, limit)
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:
            return [{"error": f"fallback_web_search_failed: {type(exc).__name__}: {redact(str(exc))}", "query": query}]
        items: list[dict[str, Any]] = []
        for obj in _walk_dicts(data):
            url = obj.get("url") or obj.get("link") or obj.get("source_url")
            if isinstance(url, str) and safe_url(url):
                items.append({
                    "url": url,
                    "title": str(obj.get("title") or ""),
                    "description": str(obj.get("description") or obj.get("snippet") or obj.get("content") or "")[:2000],
                    "query": query,
                    "metadata": {"retrieval_backend": "hermes_web_search_fallback"},
                })
            if len(items) >= limit:
                break
        return items

    async def extract_pages(self, urls: list[str], max_chars: int = 6000) -> list[dict[str, Any]]:
        clean_urls = []
        for url in urls:
            text = str(url or "").strip()
            if safe_url(text) and text not in clean_urls:
                clean_urls.append(text)
            if len(clean_urls) >= MAX_URLS_TO_EXTRACT:
                break
        self._record("extract_pages", {"urls": clean_urls, "max_chars": max_chars})
        fixture_extract = self.fixture.get("extract", {})
        out: list[dict[str, Any]] = []
        missing: list[str] = []
        for url in clean_urls:
            if url in fixture_extract:
                item = dict(fixture_extract[url])
                item.setdefault("url", url)
                item["content"] = str(item.get("content") or "")[:max_chars]
                out.append(item)
            else:
                missing.append(url)
        if not missing:
            return out
        # Prefer Hermes web_extract implementation when available; if that backend
        # is search-only or degraded, continue to other fetch paths instead of
        # returning empty-content evidence as "verified".
        try:
            from tools.web_tools import web_extract_tool
            raw = await web_extract_tool(missing, use_llm_processing=False)
            data = json.loads(raw) if isinstance(raw, str) else raw
            extracted_results = data.get("results", []) if isinstance(data, dict) else []
            for result in extracted_results:
                content = str(result.get("content") or "")[:max_chars]
                if content:
                    out.append({
                        "url": result.get("url"),
                        "title": result.get("title") or "",
                        "content": content,
                        "error": result.get("error"),
                    })
            found = {x.get("url") for x in out if x.get("content")}
            missing = [u for u in missing if u not in found]
            if not missing:
                return out
        except Exception:
            pass
        for url in missing:
            proc = await asyncio.to_thread(subprocess.run, ["smart-search", "fetch", url, "--format", "json"], text=True, capture_output=True, timeout=self.timeout)
            if proc.returncode != 0:
                direct = await self._direct_fetch_page(url, max_chars=max_chars)
                out.append(direct)
                continue
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                data = {"content": proc.stdout}
            content = str(data.get("content") or data)[:max_chars]
            if content:
                out.append({"url": url, "title": str(data.get("title") or ""), "content": content})
            else:
                out.append(await self._direct_fetch_page(url, max_chars=max_chars))
        return out

    async def _direct_fetch_page(self, url: str, max_chars: int = 6000) -> dict[str, Any]:
        """Last-resort stdlib HTTP fetch for public pages when configured extractors are unavailable."""
        def fetch() -> dict[str, Any]:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 HermesSearchAsCode/1.0 (+https://hermes-agent.nousresearch.com)",
                        "Accept": "text/html,text/plain,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
                with urllib.request.urlopen(req, timeout=max(10, min(self.timeout, 45))) as resp:
                    raw = resp.read(max_chars * 4)
                    ctype = resp.headers.get_content_charset() or "utf-8"
                    text = raw.decode(ctype, errors="ignore")
                stripped = html_to_text(text)
                return {"url": url, "title": "", "content": stripped[:max_chars], "metadata": {"retrieval_backend": "direct_urllib_fallback"}}
            except Exception as exc:
                return {"url": url, "error": f"direct_fetch_failed: {type(exc).__name__}: {redact(str(exc))}"}
        return await asyncio.to_thread(fetch)

    def dedupe(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for item in items:
            url = str(item.get("url") or "").split("#", 1)[0].rstrip("/")
            key = url or stable_id(str(item.get("title", "")), str(item.get("description", "")))
            if key not in by_key:
                by_key[key] = dict(item)
                order.append(key)
                continue
            # Merge rather than drop duplicates: search hits often have query/snippet,
            # extract hits often have page content. Keeping only the first hit loses
            # the evidence payload and makes source-health look green but shallow.
            existing = by_key[key]
            for field in ("title", "description", "query", "source", "content"):
                if item.get(field) and not existing.get(field):
                    existing[field] = item[field]
            if item.get("content") and len(str(item.get("content"))) > len(str(existing.get("content") or "")):
                existing["content"] = item["content"]
            metadata = dict(existing.get("metadata") or {})
            metadata.update(item.get("metadata") or {})
            if metadata:
                existing["metadata"] = metadata
        out = [by_key[key] for key in order]
        self._record("dedupe", {"input": len(items), "output": len(out)})
        return out

    def authority_score(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored = []
        for item in items:
            url = str(item.get("url") or "")
            host = (urlparse(url).hostname or "").lower()
            content = str(item.get("content") or item.get("description") or "")
            score = 1.0
            if any(h in host for h in PRIMARY_SOURCE_HINTS):
                score += 2.0
            if item.get("content"):
                score += min(2.0, len(content) / 4000)
            if "error" in item and item.get("error"):
                score -= 3.0
            copy = dict(item)
            copy["score"] = round(score, 3)
            scored.append(copy)
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        self._record("authority_score", {"count": len(scored)})
        return scored

    def evidence_pack(self, items: list[dict[str, Any]], query: str = "") -> dict[str, Any]:
        valid_items = [x for x in items if x.get("url") and not x.get("error")]
        error_items = [x for x in items if x.get("error") or not x.get("url")]
        pack = {
            "query": query,
            "source_count": len(valid_items),
            "items": valid_items,
            "source_health": {
                "with_content": sum(1 for x in valid_items if x.get("content")),
                "with_error": len(error_items),
                "primary_like": sum(1 for x in valid_items if any(h in (urlparse(str(x.get("url") or "")).hostname or "") for h in PRIMARY_SOURCE_HINTS)),
            },
        }
        if error_items:
            pack["retrieval_errors"] = [
                {
                    "source": x.get("source"),
                    "query": x.get("query"),
                    "error_type": x.get("error_type") or (x.get("metadata") or {}).get("error_type"),
                    "error": str(x.get("error") or "")[:500],
                }
                for x in error_items[:5]
            ]
        self._record("evidence_pack", {"source_count": len(valid_items), "error_count": len(error_items)})
        return pack


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if tag.lower() in {"p", "br", "li", "div", "section", "article", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if tag.lower() in {"p", "li", "div", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            text = data.strip()
            if text:
                self.parts.append(text)


def html_to_text(value: str) -> str:
    if "<" not in value or ">" not in value:
        return value
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_dicts(item)


def default_plan_for_query(query: str) -> str:
    safe_query = json.dumps(query, ensure_ascii=False)
    return f'''async def plan(sdk):
    topic = {safe_query}
    # Generic retrieval expansion: keep the user's topic anchored while asking
    # for source-backed, primary, and independent context. Domain-specific
    # expansions belong in future planner output, not in this fallback plan.
    seed_queries = [
        topic,
        topic + " primary sources",
        topic + " official documentation",
        topic + " independent analysis",
    ]
    batches = await asyncio.gather(*(sdk.search_web(q, limit=5) for q in seed_queries))
    results = [item for batch in batches for item in batch]
    unique = sdk.dedupe(results)
    urls = [item.get("url") for item in unique if item.get("url")]
    pages = await sdk.extract_pages(urls[:8], max_chars=5000)
    merged = sdk.dedupe(unique + pages)
    ranked = sdk.authority_score(merged)
    return sdk.evidence_pack(ranked[:12], query=topic)
'''


async def execute_plan(code: str, sdk: SearchSDK) -> dict[str, Any]:
    validate_plan_ast(code)
    env: dict[str, Any] = {"__builtins__": SAFE_BUILTINS, "asyncio": asyncio}
    compiled = compile(code, "<search_as_code_plan>", "exec")
    exec(compiled, env, env)
    plan = env.get("plan")
    if not callable(plan):
        raise PlanSecurityError("plan must define async def plan(sdk)")
    result = plan(sdk)
    if asyncio.iscoroutine(result):
        result = await result
    if not isinstance(result, dict):
        raise PlanSecurityError("plan must return a dict evidence pack")
    return result


def build_markdown(pack: dict[str, Any], events: list[dict[str, Any]], plan_code: str) -> str:
    lines = [
        "# Search-as-Code Evidence Pack",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Query: {pack.get('query', '')}",
        "",
        "## Source health",
        "",
        "```json",
        json.dumps(pack.get("source_health", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Top sources",
        "",
    ]
    for i, item in enumerate(pack.get("items", []), 1):
        lines.extend([
            f"### {i}. {item.get('title') or item.get('url')}",
            f"- URL: {item.get('url')}",
            f"- Score: {item.get('score')}",
            f"- Query: {item.get('query', '')}",
            "",
            str(item.get("description") or item.get("content") or item.get("error") or "")[:1200],
            "",
        ])
    lines.extend([
        "## Executed retrieval program",
        "",
        "```python",
        plan_code,
        "```",
        "",
        "## SDK events",
        "",
        "```json",
        json.dumps(events, ensure_ascii=False, indent=2)[:20000],
        "```",
    ])
    return redact("\n".join(lines))


def privacy_scan_text(text: str) -> list[str]:
    findings = []
    for idx, pattern in enumerate(SECRET_PATTERNS):
        if pattern.search(text):
            findings.append(f"secret_pattern_{idx}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Run experimental Search-as-Code deep research.")
    parser.add_argument("query")
    parser.add_argument("--plan-file")
    parser.add_argument("--fixture")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    fixture = {}
    if args.fixture:
        fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    plan_code = Path(args.plan_file).read_text(encoding="utf-8") if args.plan_file else default_plan_for_query(args.query)

    run_dir = Path(args.output_root) / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slugify(args.query)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "plan.py").write_text(plan_code, encoding="utf-8")

    sdk = SearchSDK(fixture=fixture, timeout=args.timeout)
    try:
        pack = asyncio.run(execute_plan(plan_code, sdk))
        status = "Verified working"
        error = None
    except Exception as exc:
        pack = {"query": args.query, "source_count": 0, "items": [], "source_health": {}, "error": f"{type(exc).__name__}: {exc}"}
        status = "Degraded"
        error = pack["error"]

    raw_json = redact(json.dumps(pack, ensure_ascii=False, indent=2))
    evidence_md = build_markdown(pack, sdk.events, plan_code)
    findings = privacy_scan_text(raw_json + evidence_md + plan_code)
    if findings and status == "Verified working":
        status = "Degraded"
        error = "privacy_scan_failed: " + ",".join(findings)
    health = pack.get("source_health") if isinstance(pack.get("source_health"), dict) else {}
    source_count = int(pack.get("source_count") or 0)
    with_content = int(health.get("with_content") or 0)
    if status == "Verified working" and source_count <= 0:
        status = "Degraded"
        error = "evidence_gate_failed: no sources collected"
    elif status == "Verified working" and with_content <= 0:
        status = "Degraded"
        error = "evidence_gate_failed: no extracted source content"

    (run_dir / "evidence.json").write_text(raw_json, encoding="utf-8")
    (run_dir / "evidence.md").write_text(evidence_md, encoding="utf-8")
    manifest = {
        "query": args.query,
        "run_dir": str(run_dir),
        "overall_status": status,
        "source_count": pack.get("source_count", 0),
        "source_health": pack.get("source_health", {}),
        "privacy_scan": "PASS" if not findings else "FAIL",
        "privacy_findings": findings,
        "error": error,
        "files": {
            "plan": str(run_dir / "plan.py"),
            "evidence_json": str(run_dir / "evidence.json"),
            "evidence_md": str(run_dir / "evidence.md"),
            "manifest": str(run_dir / "manifest.json"),
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if status == "Verified working" else 1


if __name__ == "__main__":
    raise SystemExit(main())
