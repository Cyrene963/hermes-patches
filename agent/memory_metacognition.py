"""Memory Metacognition Framework — interfaces + policy loader.

Provides three pluggable extension points for enhancing the agent's
awareness of its own persistent memory:

1. MemoryIndexProvider  — generates a compact index of what's in the memory store
2. RecallQueryExpander  — expands user messages into better hindsight queries
3. MemoryPreflightPolicy — gates dangerous operations based on memory state

All three are loaded from a YAML policy file. The framework ships with
no-op defaults; users/deployers customize via ~/.hermes/memory_policy.yaml.

Design principles:
- Core code contains ZERO hardcoded deployment-specific data (no user IDs,
  no platform-specific rules, no language-specific mappings).
- Default behavior is conservative: warn-only, never block.
- Policy is loaded once per process and cached.
- All failures are non-blocking (agent continues without enhancement).
"""

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import re as _re

logger = logging.getLogger(__name__)

# ─── Data types ──────────────────────────────────────────────────────

@dataclass
class PreflightCheck:
    """Result of a single preflight check."""
    check_type: str           # e.g. "identity", "method", "safety"
    query: str                # hindsight query used
    required: bool            # whether this check is mandatory
    found: bool               # whether relevant memory was found
    status: str               # "PASS" | "WARN" | "FAIL"
    message: str = ""         # human-readable explanation
    top_memory: str = ""      # relevant memory snippet if found


@dataclass
class PreflightResult:
    """Aggregated preflight result for a high-risk task."""
    decision: str             # "allow" | "warn" | "block"
    reason: str
    task_type: str
    checks: List[PreflightCheck] = field(default_factory=list)


# ─── Abstract interfaces ─────────────────────────────────────────────

class MemoryIndexProvider(ABC):
    """Generates a compact index of the agent's memory store.

    The index is injected into the system prompt once per session so the
    model knows what categories and recent memories exist, without needing
    to search proactively.
    """

    @abstractmethod
    def build_index(self) -> str:
        """Return compact memory index text (ideally 200-300 tokens).

        Returns empty string on failure. Must never raise.
        """
        ...


class RecallQueryExpander(ABC):
    """Expands a user message into better hindsight search queries.

    The default implementation returns [original_message] only.
    Policies can add keyword→expansion mappings for their language/domain.
    """

    @abstractmethod
    def expand(self, user_message: str, max_queries: int = 8) -> List[str]:
        """Return [original, expanded1, expanded2, ...] capped at max_queries."""
        ...


class MemoryPreflightPolicy(ABC):
    """Gates dangerous operations based on memory state.

    The default implementation allows all operations (no-op).
    Policies define which tool+arg combinations are high-risk and what
    memory checks are required.
    """

    @abstractmethod
    def get_task_type(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
        """Return task type string if this tool call is high-risk, else None."""
        ...

    @abstractmethod
    def run_checks(self, task_type: str, context: Dict[str, Any]) -> PreflightResult:
        """Run preflight checks for a high-risk task.

        Returns PreflightResult with decision=allow/warn/block.
        """
        ...


# ─── Default no-op implementations ───────────────────────────────────

class NoOpIndexProvider(MemoryIndexProvider):
    """Default: no memory index injected."""
    def build_index(self) -> str:
        return ""


class PassthroughExpander(RecallQueryExpander):
    """Default: returns only the original message (no expansion)."""
    def expand(self, user_message: str, max_queries: int = 8) -> List[str]:
        if not user_message:
            return []
        return [user_message]


class NoOpPreflightPolicy(MemoryPreflightPolicy):
    """Default: all operations allowed, no checks."""
    def get_task_type(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
        return None

    def run_checks(self, task_type: str, context: Dict[str, Any]) -> PreflightResult:
        return PreflightResult(
            decision="allow",
            reason="No preflight policy configured",
            task_type=task_type or "",
        )


# ─── Script-backed implementations ──────────────────────────────────

class ScriptIndexProvider(MemoryIndexProvider):
    """Generates memory index by calling an external script.

    Looks for the script at ~/.hermes/scripts/memory_index_generator.py.
    Falls back to no-op if script is missing or fails.
    """

    def __init__(self, script_dir: Optional[str] = None, timeout: int = 5):
        self._script_dir = script_dir or os.path.join(
            os.path.expanduser("~"), ".hermes", "scripts"
        )
        self._timeout = timeout

    def build_index(self) -> str:
        try:
            import subprocess
            import sys as _sys
            script = os.path.join(self._script_dir, "memory_index_generator.py")
            if not os.path.exists(script):
                return ""
            result = subprocess.run(
                [_sys.executable, script, "--limit", "10"],
                capture_output=True, text=True, timeout=self._timeout,
            )
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                if len(output) > 800:
                    output = output[:797] + "..."
                return f"# Memory Index (auto-generated, session start)\n{output}"
        except Exception:
            pass
        return ""


class PolicyQueryExpander(RecallQueryExpander):
    """Expands queries using keyword→terms mappings from policy."""

    def __init__(self, expansions: Optional[Dict[str, List[str]]] = None,
                 max_queries: int = 8):
        self._expansions = expansions or {}
        self._max_queries = max_queries

    def expand(self, user_message: str, max_queries: int = 8) -> List[str]:
        if not user_message:
            return []
        cap = min(max_queries, self._max_queries)
        queries = [user_message]
        msg_lower = user_message.lower()
        for keyword, terms in self._expansions.items():
            if keyword.lower() in msg_lower:
                for term in terms:
                    if term.lower() not in [q.lower() for q in queries]:
                        queries.append(term)
                        if len(queries) >= cap:
                            return queries
        return queries


def _stringify_for_policy_match(value: Any) -> str:
    """Return a stable, recursive text view for policy substring matching.

    Tool arguments often contain lists/dicts (for example web_extract.urls).
    A preflight policy that only sees scalar strings silently misses those
    calls, which defeats dispatch-time enforcement.
    """
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts: List[str] = []
        for k, v in value.items():
            parts.append(str(k))
            parts.append(_stringify_for_policy_match(v))
        return " ".join(p for p in parts if p)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stringify_for_policy_match(v) for v in value)
    return str(value)


class PolicyPreflightPolicy(MemoryPreflightPolicy):
    """Preflight policy loaded from YAML config.

    Supports two categories of checks:

    1. Memory recall checks (backward compatible):
       - type: memory / memory_recall / identity / method / safety
       - Searches hindsight for the query string
       - PASS if found, FAIL if required and not found

    2. Structured argument checks (new):
       - type: field_required      — field must exist in context
       - type: field_equals        — field must equal value
       - type: field_not_equals    — field must NOT equal value
       - type: field_contains      — field must contain value
       - type: field_not_contains  — field must NOT contain value

    Config format:
      preflight_rules:
        - tool: send_message
          task_type: outgoing_message
          checks:
            - type: field_required
              field: chat_id
              required: true
              error: "chat_id is required"
            - type: field_equals
              field: method
              value: sendDocument
              required: true
              error: "must use sendDocument"
            - type: memory_recall
              query: "sendDocument usage"
              required: false
              error: "no related memory"
          block_on_failure: true
    """

    def __init__(self, rules: Optional[List[Dict]] = None,
                 hindsight_api: str = "http://localhost:9177",
                 bank_id: str = "hindsight"):
        self._rules = rules or []
        self._hindsight_api = hindsight_api
        self._bank_id = bank_id
        # Build lookup: tool_name → [rule, ...]
        self._tool_map: Dict[str, List[Dict]] = {}
        for rule in self._rules:
            tool = rule.get("tool", "")
            if tool:
                self._tool_map.setdefault(tool, []).append(rule)

    def get_task_type(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
        rules = self._tool_map.get(tool_name, [])
        for rule in rules:
            patterns = rule.get("trigger_patterns", [])
            if patterns:
                # Build searchable string from ALL tool_args keys AND values
                # so patterns can match field names or field values.
                parts = []
                for k, v in tool_args.items():
                    parts.append(str(k))
                    parts.append(_stringify_for_policy_match(v))
                arg_text = " ".join(p for p in parts if p).lower()
                if not any(p.lower() in arg_text for p in patterns):
                    continue
            return rule.get("task_type", tool_name)
        return None

    def run_checks(self, task_type: str, context: Dict[str, Any]) -> PreflightResult:
        # Find the rule for this task type
        rule = None
        for r in self._rules:
            if r.get("task_type") == task_type:
                rule = r
                break
        if not rule:
            return PreflightResult(
                decision="allow",
                reason=f"No rule for task type: {task_type}",
                task_type=task_type,
            )

        # Build enriched context: top-level fields + tool_args sub-dict
        # This allows structured checks to access both context["method"]
        # and context["tool_args"]["method"] patterns.
        enriched = dict(context)
        if "tool_args" not in enriched:
            enriched["tool_args"] = dict(context)

        checks = []
        all_passed = True
        should_block = rule.get("block_on_failure", False)

        for check_def in rule.get("checks", []):
            check = self._run_single_check(check_def, enriched)
            checks.append(check)
            if check.status == "FAIL":
                all_passed = False

        if not all_passed and should_block:
            decision = "block"
            reason = "Critical preflight checks failed"
        elif not all_passed:
            decision = "warn"
            reason = "Some recommended checks failed"
        else:
            decision = "allow"
            reason = "All checks passed"

        return PreflightResult(
            decision=decision,
            reason=reason,
            task_type=task_type,
            checks=checks,
        )

    def _run_single_check(self, check_def: Dict, context: Dict) -> PreflightCheck:
        """Dispatch a single preflight check to the appropriate handler."""
        check_type = check_def.get("type", "unknown")
        required = check_def.get("required", False)
        error_msg = check_def.get("error", "")

        unless_contains = check_def.get("unless_contains")
        if unless_contains:
            field = check_def.get("field", "")
            actual = self._resolve_field(context, field)
            actual_text = _stringify_for_policy_match(actual)
            needles = unless_contains if isinstance(unless_contains, list) else [unless_contains]
            if any(str(needle) in actual_text for needle in needles):
                return PreflightCheck(
                    check_type=check_type,
                    query=f"{field} unless_contains {unless_contains}",
                    required=required,
                    found=True,
                    status="PASS",
                    message="",
                )

        # ── Structured argument checks ──
        if check_type == "field_required":
            return self._check_field_required(check_def, context, required, error_msg)
        if check_type == "field_equals":
            return self._check_field_equals(check_def, context, required, error_msg)
        if check_type == "field_not_equals":
            return self._check_field_not_equals(check_def, context, required, error_msg)
        if check_type == "field_contains":
            return self._check_field_contains(check_def, context, required, error_msg)
        if check_type == "field_not_contains":
            return self._check_field_not_contains(check_def, context, required, error_msg)

        # ── Memory recall check (backward compatible) ──
        # Covers: memory, memory_recall, identity, method, safety, unknown
        return self._check_memory_recall(check_def, context, required, error_msg, check_type)

    def _resolve_field(self, context: Dict, field: str) -> Any:
        """Resolve a field from context. Checks top-level first, then tool_args."""
        if field in context:
            return context[field]
        tool_args = context.get("tool_args", {})
        if field in tool_args:
            return tool_args[field]
        return None

    def _check_field_required(self, check_def: Dict, context: Dict,
                               required: bool, error_msg: str) -> PreflightCheck:
        field = check_def.get("field", "")
        value = self._resolve_field(context, field)
        found = value is not None and value != ""
        status = "PASS" if found else ("FAIL" if required else "WARN")
        return PreflightCheck(
            check_type="field_required", query=field,
            required=required, found=found, status=status,
            message=error_msg if status != "PASS" else "",
        )

    def _check_field_equals(self, check_def: Dict, context: Dict,
                             required: bool, error_msg: str) -> PreflightCheck:
        field = check_def.get("field", "")
        expected = check_def.get("value", "")
        actual = self._resolve_field(context, field)
        found = actual is not None and str(actual) == str(expected)
        status = "PASS" if found else ("FAIL" if required else "WARN")
        return PreflightCheck(
            check_type="field_equals", query=f"{field}=={expected}",
            required=required, found=found, status=status,
            message=error_msg if status != "PASS" else "",
        )

    def _check_field_not_equals(self, check_def: Dict, context: Dict,
                                 required: bool, error_msg: str) -> PreflightCheck:
        field = check_def.get("field", "")
        forbidden = check_def.get("value", "")
        actual = self._resolve_field(context, field)
        # PASS if field doesn't exist OR doesn't equal forbidden value
        found = actual is not None and str(actual) == str(forbidden)
        status = "FAIL" if (found and required) else ("WARN" if found else "PASS")
        return PreflightCheck(
            check_type="field_not_equals", query=f"{field}!={forbidden}",
            required=required, found=not found, status=status,
            message=error_msg if status != "PASS" else "",
        )

    def _check_field_contains(self, check_def: Dict, context: Dict,
                               required: bool, error_msg: str) -> PreflightCheck:
        field = check_def.get("field", "")
        needle = check_def.get("value", "")
        actual = self._resolve_field(context, field)
        actual_text = _stringify_for_policy_match(actual)
        found = actual is not None and needle in actual_text
        status = "PASS" if found else ("FAIL" if required else "WARN")
        return PreflightCheck(
            check_type="field_contains", query=f"{field}~={needle}",
            required=required, found=found, status=status,
            message=error_msg if status != "PASS" else "",
        )

    def _check_field_not_contains(self, check_def: Dict, context: Dict,
                                   required: bool, error_msg: str) -> PreflightCheck:
        field = check_def.get("field", "")
        needle = check_def.get("value", "")
        actual = self._resolve_field(context, field)
        actual_text = _stringify_for_policy_match(actual)
        contains = actual is not None and needle in actual_text
        status = "FAIL" if (contains and required) else ("WARN" if contains else "PASS")
        return PreflightCheck(
            check_type="field_not_contains", query=f"{field}!~={needle}",
            required=required, found=not contains, status=status,
            message=error_msg if status != "PASS" else "",
        )

    def _check_memory_recall(self, check_def: Dict, context: Dict,
                              required: bool, error_msg: str,
                              check_type: str) -> PreflightCheck:
        """Legacy memory recall check. Searches hindsight for query."""
        query_template = check_def.get("query", "")
        query = query_template
        for k, v in context.items():
            if isinstance(v, str):
                query = query.replace(f"{{{k}}}", v)

        found = False
        top_memory = ""
        try:
            import json
            import urllib.request
            url = f"{self._hindsight_api}/v1/default/banks/{self._bank_id}/memories/recall"
            data = json.dumps({"query": query, "limit": 2}).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())
                memories = result.get("memories", result.get("results", []))
                found = len(memories) > 0
                if found:
                    top_memory = memories[0].get("text", "")[:100]
        except Exception:
            pass

        if required and not found:
            status = "FAIL"
        elif not found:
            status = "WARN"
        else:
            status = "PASS"

        return PreflightCheck(
            check_type=check_type, query=query,
            required=required, found=found, status=status,
            message=error_msg if status != "PASS" else "",
            top_memory=top_memory,
        )


# ─── Policy loader ───────────────────────────────────────────────────

_POLICY_CACHE: Dict[Optional[str], Dict] = {}  # keyed by user_id (None = global)
_POLICY_FILE_PATHS = [
    # Local private policy (user-specific, not committed)
    os.path.join(os.path.expanduser("~"), ".hermes", "memory_policy.yaml"),
]


def _find_default_policy() -> Optional[str]:
    """Find the default policy YAML bundled with the agent."""
    # Look relative to this file
    here = Path(__file__).parent
    candidate = here / "memory_policy.default.yaml"
    if candidate.exists():
        return str(candidate)
    return None


def _get_user_policy_path(user_id: Optional[str]) -> Optional[str]:
    """Get user-specific policy file path."""
    if not user_id:
        return None
    return os.path.join(
        os.path.expanduser("~"), ".hermes", "memories",
        f"user_{user_id}", "memory_policy.yaml"
    )


def _resolve_bank_id(user_context: Optional[Dict] = None) -> str:
    """Resolve hindsight bank_id with per-user isolation.

    Priority:
    1. user_context["bank_id"] if explicitly provided
    2. "hindsight-{user_id}" if user_id is available
    3. "hindsight" (default, no isolation)
    """
    if user_context:
        if user_context.get("bank_id"):
            return user_context["bank_id"]
        if user_context.get("user_id"):
            return f"hindsight-{user_context['user_id']}"
    return "hindsight"


def load_policy(force_reload: bool = False,
                user_context: Optional[Dict] = None) -> Dict[str, Any]:
    """Load and merge memory metacognition policy.

    With user_context, loads per-user policy overlay on top of global policy.
    Cache is per-user (keyed by user_id).

    Priority: user private > local private > default bundled.
    """
    cache_key = user_context.get("user_id") if user_context else None

    if cache_key in _POLICY_CACHE and not force_reload:
        return _POLICY_CACHE[cache_key]

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML unavailable; memory metacognition policy disabled")
        _POLICY_CACHE[cache_key] = {}
        return _POLICY_CACHE[cache_key]

    merged: Dict[str, Any] = {}

    # 1. Load default (bundled) policy
    default_path = _find_default_policy()
    if default_path:
        try:
            with open(default_path) as f:
                merged = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Failed to load default memory policy: %s", e)

    # 2. Overlay local private policy (skipped if HERMES_MEMORY_POLICY_DISABLE_LOCAL=1)
    if os.environ.get("HERMES_MEMORY_POLICY_DISABLE_LOCAL") == "1":
        logger.debug("Local memory policy disabled via env var")
    else:
        for path in _POLICY_FILE_PATHS:
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        local = yaml.safe_load(f) or {}
                    _deep_merge(merged, local)
                    logger.info("Loaded memory policy from %s", path)
                except Exception as e:
                    logger.warning("Failed to load memory policy from %s: %s", path, e)

        # 3. Overlay user-specific policy (if user_context provided)
        if user_context and user_context.get("user_id"):
            user_path = _get_user_policy_path(user_context["user_id"])
            if user_path and os.path.exists(user_path):
                try:
                    with open(user_path) as f:
                        user_policy = yaml.safe_load(f) or {}
                    _deep_merge(merged, user_policy)
                    logger.info("Loaded user policy from %s", user_path)
                except Exception as e:
                    logger.warning("Failed to load user policy from %s: %s", user_path, e)

    _POLICY_CACHE[cache_key] = merged
    return merged


def _deep_merge(base: Dict, overlay: Dict) -> Dict:
    """Recursively merge overlay into base (overlay wins)."""
    for k, v in overlay.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base




def get_tool_preflight_block_message(tool_name: str, tool_args: Dict[str, Any], *, user_context: Optional[Dict] = None) -> Optional[str]:
    """Return a dispatch-time Memory Preflight block message for a tool call.

    This is the single enforcement helper used by all tool-dispatch paths.
    It intentionally calls the MemoryPreflightPolicy API (get_task_type +
    run_checks) rather than similarly named strategy-routing helpers.

    Policy evaluation failures degrade open to avoid breaking unrelated tool
    execution, but they are logged as warnings.  They must not be swallowed
    silently; a swallowed AttributeError once made the entire gate a no-op.
    """
    if not isinstance(tool_args, dict):
        tool_args = {}
    try:
        policy = build_preflight_policy(user_context=user_context)
        if policy is None:
            return None
        task_type = policy.get_task_type(tool_name, tool_args)
        if not task_type:
            return None
        result = policy.run_checks(task_type, dict(tool_args))
        if result is not None and getattr(result, "decision", "allow") == "block":
            failing = [
                c.message
                for c in (getattr(result, "checks", None) or [])
                if getattr(c, "status", "") == "FAIL" and getattr(c, "message", "")
            ]
            return (
                failing[0]
                if failing
                else (getattr(result, "reason", None) or "Blocked by memory preflight policy")
            )
    except Exception as exc:
        logger.warning("memory preflight policy error for %s: %s", tool_name, exc)
    return None

def build_index_provider(user_context: Optional[Dict] = None) -> MemoryIndexProvider:
    """Build MemoryIndexProvider from policy config."""
    policy = load_policy(user_context=user_context)
    index_cfg = policy.get("memory_index", {})
    if not index_cfg.get("enabled", False):
        return NoOpIndexProvider()
    script_dir = index_cfg.get("script_dir")
    timeout = index_cfg.get("timeout", 5)
    return ScriptIndexProvider(script_dir=script_dir, timeout=timeout)


def build_query_expander(user_context: Optional[Dict] = None) -> RecallQueryExpander:
    """Build RecallQueryExpander from policy config.

    With user_context, merges global expansions with user-specific expansions.
    """
    policy = load_policy(user_context=user_context)
    expansion_cfg = policy.get("query_expansion", {})
    if not expansion_cfg.get("enabled", False):
        return PassthroughExpander()
    expansions = expansion_cfg.get("expansions", {})
    max_queries = expansion_cfg.get("max_queries", 8)
    return PolicyQueryExpander(expansions=expansions, max_queries=max_queries)


def build_preflight_policy(user_context: Optional[Dict] = None) -> MemoryPreflightPolicy:
    """Build MemoryPreflightPolicy from policy config.

    With user_context, uses per-user bank_id for memory recall checks.
    """
    policy = load_policy(user_context=user_context)
    preflight_cfg = policy.get("preflight", {})
    if not preflight_cfg.get("enabled", False):
        return NoOpPreflightPolicy()
    rules = preflight_cfg.get("rules", [])
    api = preflight_cfg.get("hindsight_api", "http://localhost:9177")
    bank = _resolve_bank_id(user_context) or preflight_cfg.get("bank_id", "hindsight")
    return PolicyPreflightPolicy(rules=rules, hindsight_api=api, bank_id=bank)


# ─── Task Routing / Strategy Recall ──────────────────────────────────

@dataclass
class StrategyHint:
    """Output from task routing preflight. Injected into agent planning."""
    task_type: str                    # e.g. "cloudflare_site_access"
    recommended_strategy: str         # e.g. "use_camoufox"
    avoid_methods: List[str]          # e.g. ["browser_navigate", "curl"]
    preferred_method: str             # e.g. "camoufox"
    reason: str                       # human-readable explanation
    confidence: str                   # "high", "medium", "low"
    recall_hits: int                  # how many memories matched


class TaskRoutingPreflight:
    """Strategy recall gate — runs BEFORE tool selection.

    Matches user_message against routing rules. If triggered, searches
    hindsight for strategy memories and returns a StrategyHint that
    should be injected into the agent's planning context.

    Default: disabled (no-op). Controlled by routing_preflight in policy.
    """

    def __init__(self, rules: Optional[List[Dict]] = None,
                 hindsight_api: str = "http://localhost:9177",
                 bank_id: str = "hindsight"):
        self._rules = rules or []
        self._hindsight_api = hindsight_api
        self._bank_id = bank_id

    def check(self, user_message: str) -> Optional[StrategyHint]:
        """Check user_message against routing rules. Returns StrategyHint or None."""
        if not user_message or not self._rules:
            return None

        msg_lower = user_message.lower()

        for rule in self._rules:
            patterns = rule.get("trigger_patterns", [])
            if not patterns:
                continue

            # Match trigger patterns against user message
            if not any(p.lower() in msg_lower for p in patterns):
                continue

            # Triggered — run recall for strategy memories
            recall_queries = rule.get("recall_queries", [])
            if not recall_queries:
                recall_queries = [user_message]

            total_hits = 0
            top_reasons = []
            for query in recall_queries[:3]:  # Cap at 3 queries
                try:
                    hits = self._recall(query)
                    total_hits += len(hits)
                    for h in hits[:2]:
                        text = h.get("text", "")[:150]
                        if text:
                            top_reasons.append(text)
                except Exception:
                    pass

            # Build confidence from hit count
            if total_hits >= 3:
                confidence = "high"
            elif total_hits >= 1:
                confidence = "medium"
            else:
                confidence = "low"

            return StrategyHint(
                task_type=rule.get("task_type", "unknown"),
                recommended_strategy=rule.get("preferred_method", ""),
                avoid_methods=rule.get("avoid_methods", []),
                preferred_method=rule.get("preferred_method", ""),
                reason=rule.get("strategy_hint", "") or "; ".join(top_reasons[:2]),
                confidence=confidence,
                recall_hits=total_hits,
            )

        return None

    def _recall(self, query: str) -> List[Dict]:
        """Search hindsight for strategy memories."""
        try:
            import json
            import urllib.request
            url = f"{self._hindsight_api}/v1/default/banks/{self._bank_id}/memories/recall"
            data = json.dumps({"query": query, "budget": "low", "max_tokens": 512}).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=8) as resp:
                result = json.loads(resp.read())
                return result.get("results", result.get("memories", []))
        except Exception:
            return []


def build_strategy_preflight(user_context: Optional[Dict] = None) -> TaskRoutingPreflight:
    """Build TaskRoutingPreflight from policy config."""
    policy = load_policy(user_context=user_context)
    routing_cfg = policy.get("routing_preflight", {})
    if not routing_cfg.get("enabled", False):
        return TaskRoutingPreflight()  # no-op (empty rules)
    rules = routing_cfg.get("rules", [])
    api = routing_cfg.get("hindsight_api",
                           policy.get("preflight", {}).get("hindsight_api", "http://localhost:9177"))
    bank = _resolve_bank_id(user_context) or routing_cfg.get("bank_id",
                           policy.get("preflight", {}).get("bank_id", "hindsight"))
    return TaskRoutingPreflight(rules=rules, hindsight_api=api, bank_id=bank)


# ─── Lesson Promotion / Policy Suggestion ────────────────────────────

LESSON_KEYWORDS = {
    "query_expansion": [
        "搜", "搜索", "recall", "search", "扩展", "expand", "关键词",
        "keyword", "相关词", "related terms",
    ],
    "task_routing": [
        "用", "用这个", "优先", "prefer", "avoid", "别用", "不要用",
        "方法", "method", "策略", "strategy", "路由", "route",
        "应该用", "should use", "camoufox", "curl", "browser",
    ],
    "preflight": [
        "检查", "check", "验证", "verify", "必须", "must", "不能",
        "block", "阻止", "拦截", "阻止", "before", "执行前",
        "参数", "parameter", "field", "字段",
    ],
}


@dataclass
class LessonSuggestion:
    """A reviewable policy suggestion derived from a lesson."""
    lesson_text: str              # original lesson
    lesson_type: str              # "query_expansion" | "task_routing" | "preflight" | "memory_recall"
    scope: str                    # "public" | "private" | "user_specific"
    suggestion: Dict[str, Any]    # structured policy patch
    confidence: str               # "high" | "medium" | "low"
    reasoning: str                # why this classification
    applied: bool = False         # whether user confirmed


def classify_lesson(lesson_text: str) -> tuple:
    """Classify a lesson into type and scope.

    Returns (lesson_type, scope, confidence, reasoning).
    """
    text_lower = lesson_text.lower()

    # Score each type by keyword matches
    scores = {}
    for ltype, keywords in LESSON_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        scores[ltype] = score

    # Determine type
    if not any(scores.values()):
        return ("memory_recall", "private", "low",
                "No policy keywords matched; treat as general memory.")

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    if best_score >= 3:
        confidence = "high"
    elif best_score >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    # Determine scope: public if no private indicators
    private_indicators = [
        "chat_id", "token", "密码", "password", "key", "secret",
        "api_key", "我的", "my ", "用户", "user_id", "telegram",
        "个人", "private",
    ]
    is_private = any(ind in text_lower for ind in private_indicators)
    scope = "private" if is_private else "public"

    reasoning = f"Matched {best_score} keywords for {best_type}. "
    reasoning += "Contains private indicators." if is_private else "No private indicators."

    return (best_type, scope, confidence, reasoning)


def suggest_policy_patch(lesson_text: str,
                         user_context: Optional[Dict] = None) -> LessonSuggestion:
    """Generate a policy suggestion from a lesson text.

    Returns a LessonSuggestion that can be reviewed before applying.
    Does NOT modify any files.
    """
    lesson_type, scope, confidence, reasoning = classify_lesson(lesson_text)

    suggestion: Dict[str, Any] = {}

    if lesson_type == "query_expansion":
        # Extract potential keywords from the lesson
        # Simple heuristic: look for quoted terms or key phrases
        import re
        quoted = re.findall(r'[""\'](.*?)[""\']|「(.*?)」|『(.*?)』', lesson_text)
        keywords = [q[0] or q[1] or q[2] for q in quoted]
        if not keywords:
            # Fallback: use significant words
            stopwords = {"的", "是", "在", "了", "和", "与", "或", "不", "要", "会",
                         "the", "a", "an", "is", "are", "was", "were", "be", "been",
                         "to", "of", "in", "for", "on", "with", "at", "by", "from"}
            words = re.findall(r'[\w\u4e00-\u9fff]+', lesson_text)
            keywords = [w for w in words if len(w) > 1 and w.lower() not in stopwords][:5]

        suggestion = {
            "section": "query_expansion",
            "action": "add_expansions",
            "keywords": keywords[:5],
            "note": "Review keywords before adding to policy.",
        }

    elif lesson_type == "task_routing":
        # Extract trigger patterns and preferred method
        import re
        urls = re.findall(r'https?://[^\s]+', lesson_text)
        domains = re.findall(r'[\w-]+\.(com|org|net|io|do|me|cn)', lesson_text)

        suggestion = {
            "section": "routing_preflight",
            "action": "add_rule",
            "trigger_patterns": urls[:3] or domains[:3] or [lesson_text[:50]],
            "preferred_method": "",
            "avoid_methods": [],
            "note": "Fill in preferred_method and avoid_methods before applying.",
        }

    elif lesson_type == "preflight":
        suggestion = {
            "section": "preflight",
            "action": "add_rule",
            "tool": "",
            "task_type": "",
            "checks": [],
            "note": "Fill in tool, task_type, and checks before applying.",
        }

    else:  # memory_recall
        suggestion = {
            "section": "memory_only",
            "action": "retain_as_memory",
            "note": "No policy change. Store as hindsight memory for recall.",
        }

    return LessonSuggestion(
        lesson_text=lesson_text,
        lesson_type=lesson_type,
        scope=scope,
        suggestion=suggestion,
        confidence=confidence,
        reasoning=reasoning,
    )


def _sanitize_lesson_text(text: str) -> str:
    """Remove private indicators from lesson text for safe preview/logging."""
    import re
    # Mask chat_id patterns
    text = re.sub(r'chat_id\s*[:=]\s*\S+', 'chat_id=[REDACTED]', text)
    # Mask token/key patterns
    text = re.sub(r'(token|key|secret|password|api_key)\s*[:=]\s*\S+', r'\1=[REDACTED]', text, flags=re.IGNORECASE)
    # Mask long numeric IDs (likely chat_id)
    text = re.sub(r'\b\d{8,}\b', '[ID]', text)
    return text


def apply_suggestion(suggestion: LessonSuggestion,
                     user_context: Optional[Dict] = None,
                     dry_run: bool = True,
                     shared: bool = False) -> Dict[str, Any]:
    """Apply a confirmed lesson suggestion to the appropriate policy file.

    dry_run=True (default): returns what WOULD be written, without writing.
    dry_run=False: writes to the appropriate policy file.
    shared=True: explicit confirmation to write to global/shared policy.
                  Required when target would be global policy.

    Safety rules:
    - scope=private without user_context → REFUSE (prevent leak to global)
    - scope=public without user_context and without shared=True → REFUSE
    - _lesson_source is sanitized before including in preview/logs
    - user_id comes from runtime metadata only, never from lesson text

    Returns dict with: status, file_path, diff_preview, errors.
    """
    if suggestion.applied:
        return {"status": "already_applied", "errors": []}

    # Determine target file
    scope = suggestion.scope
    has_user = bool(user_context and user_context.get("user_id"))

    if has_user:
        # User-specific policy (safe)
        target_path = _get_user_policy_path(user_context["user_id"])
        if not target_path:
            target_path = os.path.join(
                os.path.expanduser("~"), ".hermes", "memories",
                f"user_{user_context['user_id']}", "memory_policy.yaml"
            )
    else:
        # Global policy — require explicit shared confirmation
        if scope == "private":
            return {
                "status": "refused",
                "errors": ["Private lesson cannot be written to global policy without user_context."],
                "dry_run": dry_run,
            }
        if not shared:
            return {
                "status": "refused",
                "errors": ["Writing to shared/global policy requires explicit shared=True confirmation."],
                "dry_run": dry_run,
            }
        target_path = os.path.join(
            os.path.expanduser("~"), ".hermes", "memory_policy.yaml"
        )

    # Build the patch
    section = suggestion.suggestion.get("section", "")
    action = suggestion.suggestion.get("action", "")

    if action == "retain_as_memory":
        return {
            "status": "no_policy_change",
            "message": "Lesson stored as memory only. No policy modification needed.",
            "file_path": None,
            "dry_run": dry_run,
        }

    # Sanitize lesson text for preview
    sanitized_source = _sanitize_lesson_text(suggestion.lesson_text[:100])

    # For other actions, build a YAML patch preview
    patch_preview = {
        section: {
            "_lesson_source": sanitized_source,
            "_confidence": suggestion.confidence,
            **{k: v for k, v in suggestion.suggestion.items()
               if k not in ("section", "action", "note")},
        }
    }

    if dry_run:
        return {
            "status": "dry_run",
            "file_path": target_path,
            "would_write": patch_preview,
            "note": suggestion.suggestion.get("note", ""),
            "dry_run": True,
        }

    # Actually write (requires explicit dry_run=False)
    try:
        import yaml
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        existing = {}
        if os.path.exists(target_path):
            with open(target_path) as f:
                existing = yaml.safe_load(f) or {}

        _deep_merge(existing, patch_preview)

        with open(target_path, "w") as f:
            yaml.dump(existing, f, default_flow_style=False, allow_unicode=True)

        suggestion.applied = True
        _POLICY_CACHE.pop(user_context.get("user_id") if user_context else None, None)

        return {
            "status": "applied",
            "file_path": target_path,
            "dry_run": False,
        }
    except Exception as e:
        return {
            "status": "error",
            "errors": [str(e)],
            "dry_run": False,
        }
_CJK_STOPWORDS = frozenset({
    "的", "是", "在", "了", "和", "与", "或", "不", "要", "会", "能", "可以",
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "这", "那", "这个",
    "那个", "什么", "怎么", "为什么", "吗", "呢", "吧", "啊", "呀", "哦",
    "把", "被", "给", "从", "到", "对", "就", "都", "也", "还", "又", "再",
    "很", "太", "最", "更", "比较", "非常", "特别", "已经", "正在", "将",
    "有", "没有", "做", "弄", "搞", "说", "讲", "看", "想", "知道", "觉得",
    "请问", "帮我", "帮", "一下", "下", "下", "看看", "想", "想要",
})

_EN_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "must", "need",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
    "them", "my", "your", "his", "its", "our", "their", "mine", "yours",
    "this", "that", "these", "those", "here", "there", "what", "which",
    "who", "whom", "when", "where", "why", "how", "if", "then", "else",
    "and", "or", "but", "not", "no", "nor", "so", "yet", "for", "of",
    "in", "on", "at", "to", "from", "by", "with", "as", "into", "about",
    "up", "out", "off", "over", "under", "again", "further", "than",
    "very", "just", "also", "too", "only", "once", "more", "some", "any",
    "each", "every", "all", "both", "few", "most", "other", "such",
    "do", "did", "does", "done", "doing", "please", "thanks", "thank",
})


def _extract_entities(text: str, max_entities: int = 8) -> List[str]:
    """Extract key entities/topics from text using lightweight heuristics.

    No LLM calls — uses regex patterns to identify:
    - CJK words (2+ chars, filtered by stopword list)
    - English words (3+ chars, filtered by stopword list)
    - Quoted strings (high-value signals)
    - URLs and domain names
    - Numbers with context (e.g., "K380", "2026")
    """
    if not text:
        return []

    entities = []
    seen = set()

    # 1. Quoted strings (highest priority)
    for match in _re.findall(r'[""\'「『](.*?)[""\'」』]', text):
        clean = match.strip()
        if clean and clean not in seen and len(clean) >= 2:
            entities.append(clean)
            seen.add(clean)

    # 2. URLs and domains
    for match in _re.findall(r'https?://[^\s]+', text):
        # Extract domain as entity
        domain = _re.search(r'https?://([^/]+)', match)
        if domain:
            d = domain.group(1).replace('www.', '')
            if d not in seen:
                entities.append(d)
                seen.add(d)

    # 3. Mixed alphanumeric tokens (e.g., "K380", "iPad", "PM2", "PR #22516")
    for match in _re.findall(r'[A-Za-z]{1,5}[\d]+[\w]*|[\d]+[A-Za-z]+[\w]*', text):
        if match not in seen and len(match) >= 2:
            entities.append(match)
            seen.add(match)

    # 4. CJK words (2-4 chars for nouns, plus longer phrases)
    # For Chinese without a word segmenter, extract:
    # - 2-char sequences (most common Chinese word length: 蓝牙, 键盘, 场景)
    # - 3-char sequences (compound words: 使用场, etc.)
    # - 4-char sequences (idioms, compound nouns)
    # This gives hindsight better keyword-level matches.
    cjk_segments = _re.findall(r'[\u4e00-\u9fff]+', text)
    for seg in cjk_segments:
        # Extract 2-char windows (highest signal for search)
        if len(seg) >= 2:
            for i in range(len(seg) - 1):
                w2 = seg[i:i+2]
                if w2 not in _CJK_STOPWORDS and w2 not in seen:
                    entities.append(w2)
                    seen.add(w2)
        # Extract 3-char windows
        if len(seg) >= 3:
            for i in range(len(seg) - 2):
                w3 = seg[i:i+3]
                if w3 not in _CJK_STOPWORDS and w3 not in seen:
                    entities.append(w3)
                    seen.add(w3)
        # Extract 4-char windows
        if len(seg) >= 4:
            for i in range(len(seg) - 3):
                w4 = seg[i:i+4]
                if w4 not in _CJK_STOPWORDS and w4 not in seen:
                    entities.append(w4)
                    seen.add(w4)

    # 5. English words (3+ characters)
    for match in _re.findall(r'[A-Za-z]{3,}', text):
        lower = match.lower()
        if lower not in _EN_STOPWORDS and lower not in seen:
            entities.append(lower)
            seen.add(lower)

    return entities[:max_entities]


class ConversationRecall:
    """Conversation-level memory recall — Layer 7.

    Extracts entities from user messages and searches hindsight for each,
    catching memories that raw-message prefetch might miss.

    Example: user says "你买蓝牙键盘"
    - Entities extracted: ["蓝牙键盘", "键盘"]
    - Hindsight finds: "用户购买了某型号蓝牙键盘"
    - Injected into context for the model
    """

    def __init__(self, hindsight_api: str = "http://localhost:9177",
                 bank_id: str = "hindsight",
                 budget: str = "low",
                 max_tokens: int = 256,
                 max_entities: int = 5,
                 timeout: int = 8):
        self._hindsight_api = hindsight_api
        self._bank_id = bank_id
        self._budget = budget
        self._max_tokens = max_tokens
        self._max_entities = max_entities
        self._timeout = timeout

    def check(self, user_message: str) -> str:
        """Extract entities from user message and search hindsight.

        Returns combined memory context string, or empty if nothing found.
        """
        if not user_message or len(user_message) < 3:
            return ""

        entities = _extract_entities(user_message, self._max_entities)
        if not entities:
            return ""

        # Deduplicate and search
        seen_texts = set()
        results = []

        for entity in entities:
            try:
                hits = self._recall(entity)
                for hit in hits[:1]:  # Top 1 per entity
                    text = hit.get("text", "")[:200]
                    if text and text not in seen_texts:
                        seen_texts.add(text)
                        results.append(f"[{entity}] {text}")
            except Exception:
                pass

        if not results:
            return ""

        header = "## Conversation Recall (auto-searched by entity extraction)"
        return f"{header}\n" + "\n".join(f"- {r}" for r in results[:6])

    def _recall(self, query: str) -> List[Dict]:
        """Search hindsight for a single query."""
        import json
        import urllib.request
        url = f"{self._hindsight_api}/v1/default/banks/{self._bank_id}/memories/recall"
        data = json.dumps({
            "query": query,
            "budget": self._budget,
            "max_tokens": self._max_tokens,
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            result = json.loads(resp.read())
            return result.get("results", result.get("memories", []))


def build_conversation_recall(user_context: Optional[Dict] = None) -> ConversationRecall:
    """Build ConversationRecall from policy config."""
    policy = load_policy(user_context=user_context)
    cfg = policy.get("conversation_recall", {})
    if not cfg.get("enabled", False):
        return ConversationRecall()  # Returns empty on check() since no API configured

    api = cfg.get("hindsight_api",
                  policy.get("preflight", {}).get("hindsight_api", "http://localhost:9177"))
    bank = _resolve_bank_id(user_context) or cfg.get("bank_id",
                  policy.get("preflight", {}).get("bank_id", "hindsight"))

    return ConversationRecall(
        hindsight_api=api,
        bank_id=bank,
        budget=cfg.get("budget", "low"),
        max_tokens=cfg.get("max_tokens", 256),
        max_entities=cfg.get("max_entities", 5),
        timeout=cfg.get("timeout", 8),
    )


# ─── Memory Router ────────────────────────────────────────────────
class MemoryRouter:
    """Classifies queries and writes to route to the correct memory store."""

    _FACT_PATTERNS = [
        r'几岁|年龄|出生|住在|是什么|什么技术|什么样|考了|多少钱|什么时候|是谁|叫什么|什么人|哪里人|哪个学校',
        r'家庭|家庭情况|父母|兄弟姐妹|学校|成绩|分数|考试|mock|备考',
        r'技术栈|架构|部署|数据库|框架|服务器|环境|配置',
        r'偏好|规则|格式|账号|密码|token',
        r'who|what|when|where|how old|born|live|tech.?stack|score',
        r'family|school|score|exam|deploy|config|preference',
    ]
    _HISTORY_PATTERNS = [
        r'之前|上次|聊过|说过|讨论过|历史|记得.*说过',
        r'before|last time|previously|discussed|history',
    ]
    _RULE_PATTERNS = [
        r'怎么用|如何配置|工具|格式|规则|禁止|必须|配置',
        r'how to|config|rule|format|must|forbid|tool',
    ]

    def __init__(self):
        self._gap_log = []

    def classify_query(self, user_input: str) -> dict:
        import re as _re
        text = user_input.lower()
        entities = []
        # Extract generic entities instead of hardcoding deployment-specific
        # user/project names. Deployment-specific aliases can be handled by the
        # memory index or disclosure_rules.yaml.
        for ent in _extract_entities(user_input, max_entities=8):
            ent_l = ent.lower()
            if ent_l not in entities:
                entities.append(ent_l)
        # Check for compound intent (operation + entity) FIRST
                # Check for inventory query
        _inv_patterns = ['记得哪些', '记得什么', '有哪些记忆', '知道哪些', '记忆类别', '有哪些信息']
        if any(p in text for p in _inv_patterns):
            return {'intent': 'inventory_query', 'primary_source': 'memory_graph', 'fallback_source': 'none'}

        _compound_kws = ['注意', '规则', '应该', '需要', '怎么发', '怎么用', '发文件', '发给', '帮我发', '走什么']
        if any(w in text for w in _compound_kws) and entities:
            return {'intent': 'compound_intent', 'primary_source': 'memory_graph', 'fallback_source': 'memory_md', 'entities': entities}

        for p in self._FACT_PATTERNS:
            if _re.search(p, text):
                return {'intent': 'fact_lookup', 'primary_source': 'memory_graph', 'fallback_source': 'hindsight'}
        for p in self._HISTORY_PATTERNS:
            if _re.search(p, text):
                return {'intent': 'history_search', 'primary_source': 'hindsight', 'fallback_source': 'none'}
        for p in self._RULE_PATTERNS:
            if _re.search(p, text):
                return {'intent': 'operation_rule', 'primary_source': 'memory_md', 'fallback_source': 'hindsight'}
        # Check for compound intent (operation + entity)
        if any(w in text for w in ['注意', '规则', '应该', '需要', '怎么发', '怎么用', '发文件', '发给', '帮我发', '走什么']):
            if entities:
                return {'intent': 'compound_intent', 'primary_source': 'memory_graph', 'fallback_source': 'memory_md', 'entities': entities}
        # If entities found but no clear intent, it's unknown_fact (not ambiguous)
        if entities:
            return {'intent': 'unknown_fact', 'primary_source': 'memory_graph', 'fallback_source': 'hindsight', 'entities': entities}
        return {'intent': 'ambiguous', 'primary_source': 'memory_graph', 'fallback_source': 'hindsight'}

    def classify_write(self, content: str, context: str = '') -> dict:
        text = content.lower()
        if any(w in text for w in ['规则', '禁止', '必须', '格式', 'rule', 'must', 'forbid']):
            return {'type': 'operation_rule', 'target': 'memory_md', 'confidence': 0.8}
        if any(w in text for w in ['考了', '买了', '去了', '是', '住在', 'bought', 'went', 'lives']):
            return {'type': 'user_fact', 'target': 'memory_graph', 'confidence': 0.7}
        return {'type': 'conversation', 'target': 'hindsight', 'confidence': 0.5}

    def detect_gap(self, query: str, graph_result, hindsight_result) -> dict:
        if graph_result and graph_result.get('score', 0) >= 0.75:
            return {'status': 'found', 'source': 'memory_graph', 'confidence': graph_result['score']}
        if hindsight_result and hindsight_result.get('score', 0) >= 0.80:
            return {'status': 'found_via_hindsight', 'source': 'hindsight',
                    'confidence': hindsight_result['score'],
                    'warning': 'Historical evidence, not canonical fact'}
        import datetime
        self._gap_log.append({'query': query, 'timestamp': datetime.datetime.now().isoformat()})
        return {'status': 'not_found', 'source': None, 'confidence': 0.0, 'action': 'say_unknown'}

    def get_recent_gaps(self, limit: int = 10) -> list:
        return list(reversed(self._gap_log[-limit:]))
