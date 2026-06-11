"""LLM-backed fact classifier — the precision gate that lets auto-write be ON by default.

The keyword heuristic (auto_store_heuristic) + rule distiller top out at ~10%
write precision, because deciding "is this a durable user fact vs chit-chat /
a question / the assistant's own words" is a semantic judgment, not a keyword
match. This module asks a cheap LLM that question and returns a clean atomic fact.

Used as a GATE: a candidate may auto-write only if classify_fact() says durable
with confidence >= threshold. Fail-closed: any error, missing LLM, or low
confidence → durable=False → the candidate falls back to review, never an
unverified write. This is what makes "on by default, gets smarter with use" safe.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_KINDS = {"correction", "preference", "decision", "profile", "project", "none"}
# Kinds eligible for automatic write (high-value, user-originated, durable).
AUTO_KINDS = {"correction", "preference", "decision", "profile"}

_SYSTEM = (
    "You are a strict memory gatekeeper for a personal AI assistant. Given the USER's "
    "message, decide whether it states a DURABLE fact worth storing in long-term memory: "
    "a stable preference, a correction of a prior fact, a decision/rule the user set, or "
    "biographical/project info about the user. NOT durable: questions, chit-chat, "
    "acknowledgements, one-off task requests, emotional venting, the assistant's own "
    "analysis being quoted back, or meta-discussion about the AI/memory system itself. "
    "If durable, extract ONE atomic fact as a concise standalone third-person-usable "
    "statement (no preamble like '记住'/'remember'). Respond with ONLY a JSON object: "
    '{"durable": true|false, "kind": "correction|preference|decision|profile|project|none", '
    '"fact": "<atomic fact or empty>", "confidence": 0.0-1.0}. No prose, no code fence.'
)

_JSON_RE = re.compile(r"\{.*\}", re.S)


@dataclass
class FactVerdict:
    durable: bool
    kind: str
    fact: str
    confidence: float
    source: str = "llm"  # or "unavailable"


# Circuit breaker: when the LLM endpoint is down, stop paying the per-candidate
# timeout on every turn. After N consecutive failures, fast-fail for a cooldown.
_CB = {"fails": 0, "open_until": 0.0}
_CB_THRESHOLD = 2
_CB_COOLDOWN_S = 120.0


def _cb_open() -> bool:
    import time
    return _CB["fails"] >= _CB_THRESHOLD and time.monotonic() < _CB["open_until"]


def _cb_record(ok: bool) -> None:
    import time
    if ok:
        _CB["fails"] = 0
        _CB["open_until"] = 0.0
    else:
        _CB["fails"] += 1
        _CB["open_until"] = time.monotonic() + _CB_COOLDOWN_S


def _parse(content: str) -> Optional[dict]:
    if not content:
        return None
    m = _JSON_RE.search(content.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def classifier_enabled() -> bool:
    """On by default; a deployment can disable via env or memory_write_config.yaml."""
    env = os.environ.get("HERMES_MEMORY_LLM_CLASSIFIER", "").strip().lower()
    if env in {"0", "false", "off", "no"}:
        return False
    if env in {"1", "true", "on", "yes"}:
        return True
    try:
        import yaml
        from pathlib import Path
        cfg = yaml.safe_load((Path.home() / ".hermes" / "memory_write_config.yaml").read_text()) or {}
        val = (cfg.get("memory_write") or {}).get("llm_classifier")
        if isinstance(val, bool):
            return val
    except Exception:
        pass
    return True  # default ON — that's the point: out-of-box, gets smarter with use


def classify_fact(user_message: str, *, task: str = "title_generation",
                  min_confidence: float = 0.7, timeout: float = 8.0) -> FactVerdict:
    """Return a FactVerdict. Fail-closed to durable=False on any problem.

    A circuit breaker fast-fails while the LLM endpoint is known-down, so a
    dead endpoint doesn't add a per-candidate timeout to every turn."""
    text = (user_message or "").strip()
    if len(text) < 4:
        return FactVerdict(False, "none", "", 0.0, source="too_short")
    if _cb_open():
        return FactVerdict(False, "none", "", 0.0, source="unavailable")
    try:
        from agent.auxiliary_client import call_llm
        resp = call_llm(
            task=task,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": text[:2000]}],
            max_tokens=200,
            temperature=0.0,
            timeout=timeout,
        )
        content = (resp.choices[0].message.content or "")
        _cb_record(True)
    except Exception as exc:  # no LLM / network / config → fail-closed
        _cb_record(False)
        logger.debug("memory fact classifier unavailable (fail-closed): %s", exc)
        return FactVerdict(False, "none", "", 0.0, source="unavailable")

    data = _parse(content)
    if not isinstance(data, dict):
        return FactVerdict(False, "none", "", 0.0, source="unparseable")
    durable = bool(data.get("durable"))
    kind = str(data.get("kind") or "none").strip().lower()
    if kind not in _KINDS:
        kind = "none"
    fact = str(data.get("fact") or "").strip()
    try:
        conf = float(data.get("confidence") or 0.0)
    except Exception:
        conf = 0.0
    # Gate: durable + eligible kind + clean fact + confidence threshold.
    ok = durable and kind in AUTO_KINDS and len(fact) >= 4 and conf >= min_confidence
    return FactVerdict(ok, kind, fact if ok else "", conf, source="llm")
