"""
Disclosure Router — Proactive memory injection via trigger conditions.

Inspired by Nocturne Memory's Disclosure Routing mechanism
(https://github.com/Dataojitori/nocturne_memory). Original concept
by NeuronActivation, MIT License.

Problem solved: Agent "doesn't remember what it remembers." Standard
hindsight recall requires the agent to actively think "I should search."
Disclosure routing removes that dependency — the system proactively
matches incoming messages against stored trigger conditions and injects
relevant memories before the agent even starts thinking.

Architecture:
    User message → DisclosureRouter.check() → pattern match against rules
                 → hindsight_recall for matched rules → inject as system msg

The router uses keyword/phrase matching (fast, no LLM cost) against a
YAML config of disclosure rules. Each rule maps a trigger pattern to a
hindsight query. When patterns match, the query runs and results are
injected into context automatically.

Config: ~/.hermes/disclosure_rules.yaml
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default disclosure rules embedded as fallback.
# Keep these generic: deployment-specific triggers belong in
# ~/.hermes/disclosure_rules.yaml, not in an open-source patch.
_DEFAULT_RULES = [
    {
        "name": "agent-development",
        "patterns": ["agent", "gateway", "patch", "update", "配置", "补丁", "更新"],
        "query": "agent gateway patch update configuration",
        "priority": 8,
    },
    {
        "name": "file-delivery",
        "patterns": ["send file", "file delivery", "发文件", "sendDocument"],
        "query": "file delivery messaging platform attachment",
        "priority": 7,
    },
    {
        "name": "scheduled-tasks",
        "patterns": ["cron", "scheduled", "定时任务", "任务调度"],
        "query": "scheduled task cron job delivery",
        "priority": 6,
    },
    {
        "name": "vision-image",
        "patterns": ["image", "screenshot", "vision", "看图", "图片", "截图"],
        "query": "vision image analysis screenshot",
        "priority": 5,
    },
    {
        "name": "memory-system",
        "patterns": ["memory", "hindsight", "metacognition", "记忆", "元认知"],
        "query": "memory hindsight metacognition recall retain",
        "priority": 9,
    },
]


@dataclass
class DisclosureRule:
    """A single disclosure trigger rule."""
    name: str
    patterns: List[str]
    query: str
    priority: int = 5
    # Compiled regex patterns (built from patterns list)
    _regex: List[re.Pattern] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._regex = [
            re.compile(re.escape(p), re.IGNORECASE) for p in self.patterns
        ]

    def matches(self, text: str) -> bool:
        """Check if any pattern matches the given text."""
        return any(r.search(text) for r in self._regex)


class DisclosureRouter:
    """
    Proactive memory injection via trigger conditions.

    Matches incoming user messages against stored disclosure patterns.
    When a pattern matches, runs the associated hindsight query and
    returns the results for injection into the conversation context.

    Usage in run_agent.py (per-turn):
        router = DisclosureRouter(hindsight_client, bank_id)
        block = router.check(user_message)
        if block:
            messages.append({"role": "system", "content": block})
    """

    def __init__(
        self,
        client: Any = None,
        bank_id: str = "hindsight",
        budget: str = "low",
        max_tokens: int = 1500,
        max_rules_matched: int = 3,
        config_path: Optional[str] = None,
    ):
        self.client = client
        self.bank_id = bank_id
        self.budget = budget
        self.max_tokens = max_tokens
        self.max_rules_matched = max_rules_matched
        self.rules: List[DisclosureRule] = []
        self._load_rules(config_path)

    def _load_rules(self, config_path: Optional[str] = None):
        """Load disclosure rules from YAML config or use defaults."""
        path = Path(config_path) if config_path else Path.home() / ".hermes" / "disclosure_rules.yaml"

        if path.exists():
            try:
                import yaml
                with open(path) as f:
                    data = yaml.safe_load(f)
                if data:
                    for r in data.get("rules", []):
                        self.rules.append(DisclosureRule(
                            name=r.get("name", "unnamed"),
                            patterns=r.get("patterns", []),
                            query=r.get("query", ""),
                            priority=r.get("priority", 5),
                    ))
                    self.BLOCKED_COMBINATIONS = list(data.get("tool_blocks", []))
                    if self.rules:
                        logger.info("DisclosureRouter: loaded %d rules from %s", len(self.rules), path)
                        return
            except Exception as e:
                logger.warning("DisclosureRouter: failed to load %s: %s", path, e)

        # Fallback to defaults
        for r in _DEFAULT_RULES:
            self.rules.append(DisclosureRule(
                name=r["name"],
                patterns=r["patterns"],
                query=r["query"],
                priority=r["priority"],
            ))
        logger.info("DisclosureRouter: loaded %d default rules", len(self.rules))

    def match(self, user_message: str) -> List[DisclosureRule]:
        """Find all rules whose patterns match the user message."""
        if not user_message:
            return []
        matched = [r for r in self.rules if r.matches(user_message)]
        # Sort by priority descending, cap at max
        matched.sort(key=lambda r: r.priority, reverse=True)
        return matched[:self.max_rules_matched]

    def check(self, user_message: str) -> str:
        """
        Main entry point. Match message against disclosure rules,
        recall relevant memories, return formatted context block.

        Implements progressive disclosure: only top-N memories by
        decay score are injected, not all matches. This prevents
        information overload (32k memories → top 5-10).

        Returns empty string if no rules match or no memories found.
        """
        matched = self.match(user_message)
        if not matched:
            return ""

        if not self.client:
            logger.debug("DisclosureRouter: no hindsight client, skipping recall")
            return ""

        all_memories = []
        for rule in matched:
            try:
                results = self._recall(rule.query)
                if results:
                    all_memories.append((rule.name, results))
            except Exception as e:
                logger.debug("DisclosureRouter: recall failed for '%s': %s", rule.name, e)

        if not all_memories:
            return ""

        # Progressive disclosure: load decay scores and rank memories
        decay_scores = self._load_decay_scores()
        ranked = []
        for name, memories in all_memories:
            for m in memories:
                # Score each memory by decay weight (higher = more important)
                score = decay_scores.get(self._memory_hash(m), 0.5)
                ranked.append((score, name, m))

        # Sort by decay score descending, take top-N
        ranked.sort(key=lambda x: x[0], reverse=True)
        top_n = ranked[:8]  # Inject at most 8 memories

        # Format the disclosure block
        lines = ["## Disclosure Routing (proactively recalled, ranked by importance)"]
        lines.append("These memories were auto-injected based on trigger conditions.")
        lines.append("Only top results shown (progressive disclosure).\n")
        for score, name, m in top_n:
            lines.append(f"### Trigger: {name} (importance: {score:.2f})")
            lines.append(f"- {m[:500]}")
            lines.append("")

        return "\n".join(lines)

    def _recall(self, query: str) -> List[str]:
        """Call hindsight recall API synchronously."""
        import json
        import urllib.request

        # Try the hindsight HTTP API
        api_url = "http://127.0.0.1:9177/v1/default/banks/{}/memories/recall".format(self.bank_id)
        payload = json.dumps({
            "query": query,
            "budget": self.budget,
            "max_tokens": self.max_tokens,
        }).encode()

        try:
            req = urllib.request.Request(
                api_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
                results = data.get("results", [])
                return [r.get("text", "") for r in results if r.get("text")]
        except Exception as e:
            logger.debug("DisclosureRouter: HTTP recall failed: %s", e)
            return []

    def _load_decay_scores(self) -> Dict[str, float]:
        """Load memory decay scores from the decay engine's state file.

        Returns a dict mapping memory content hash → decay score [0, 1].
        Higher score = more important (recently recalled, frequently used).
        """
        import json as _json
        state_path = Path.home() / ".hermes" / "memory_decay_state.json"
        if not state_path.exists():
            return {}
        try:
            state = _json.loads(state_path.read_text())
            scores = {}
            for mem_id, data in state.get("memories", {}).items():
                score = data.get("decay_score", 0.5)
                content_hash = data.get("content_hash", "")
                if content_hash:
                    scores[content_hash] = score
            return scores
        except Exception:
            return {}

    @staticmethod
    def _memory_hash(content: str) -> str:
        """Hash memory content for decay score lookup."""
        import hashlib
        return hashlib.md5(content.encode("utf-8")).hexdigest()[:12]

    # =========================================================================
    # Tool-call Interceptor — block known failure patterns
    # =========================================================================

    # Optional deployment-specific tool-call blocks loaded from config.
    # Example ~/.hermes/disclosure_rules.yaml:
    # tool_blocks:
    #   - tool: browser_navigate
    #     url_pattern: "example\.com"
    #     reason: "This site requires a special browser profile."
    #     alternative: "Use the configured browser profile or an official API."
    BLOCKED_COMBINATIONS = []

    def check_tool_call(self, tool_name: str, tool_args: dict) -> Optional[str]:
        """
        Check a tool call against known failure patterns.

        Returns a blocking message if the tool call matches a known failure
        pattern, or None if the call is safe to proceed.

        Usage in run_agent.py (before tool execution):
            block_msg = router.check_tool_call(tool_name, tool_args)
            if block_msg:
                # Return error to agent, don't execute the tool
                return {"error": block_msg}
        """
        import json as _json

        args_str = _json.dumps(tool_args or {}, ensure_ascii=False).lower()

        for rule in self.BLOCKED_COMBINATIONS:
            if tool_name != rule["tool"]:
                continue
            if re.search(rule.get("url_pattern", ""), args_str, re.IGNORECASE):
                msg = (
                    f"🚫 BLOCKED by Disclosure Router: {rule['reason']}\n"
                    f"Alternative: {rule['alternative']}\n"
                    f"This pattern has failed before. Use the alternative instead."
                )
                logger.info("DisclosureRouter: blocked %s (%s)", tool_name, rule["reason"][:50])
                return msg

        return None
