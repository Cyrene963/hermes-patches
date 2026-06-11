"""Typed, readback-verified, quarantine-first write-earn logic for Memory OS.

A candidate must EARN an automatic write through three ordered gates (importance
score is NOT the gate — that was the broken one):
  Gate 1 TYPE     — only {explicit_correction, explicit_preference, decision} may
                    auto-apply; everything else → propose for human review.
  Gate 2 HYGIENE  — reject raw truncated copies, reply-quotes, questions, secrets,
                    too-short fragments (the documented garbage modes).
  Gate 3 READBACK — write to quarantine:// then confirm the node is retrievable as
                    top-1 for its own anchor; else it is useless as memory → propose.
Only a candidate passing all three AND not targeting shared `core` auto-applies, and
only when enable_auto=True (default False keeps the loop safe until precision is
measured). PURE/INJECTABLE: no I/O of its own; live pipeline passes real fns, tests
pass fakes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional

_SECRET_RE = re.compile(r"sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_|xox[baprs]-|AKIA[0-9A-Z]{16}", re.I)
_REPLY_RE = re.compile(r"\[Replying to:|\[回复|^\s*>|^引用")
_QUESTION_RE = re.compile(r"[?？]\s*$|^(在吗|怎么|如何|为什么|是不是|能不能|可以吗|有没有)")
_URL_RE = re.compile(r"https?://|/v1/|127\.0\.0\.1|localhost")

AUTO_KINDS = {"explicit_correction", "explicit_preference", "decision"}
ALWAYS_REVIEW_KINDS = {"project_fact", "inferred_preference", "sensitive_rule",
                       "hindsight_import", "low_confidence_fact"}


class Action(str, Enum):
    AUTO_APPLY = "auto_apply"
    QUARANTINE = "quarantine"
    PROPOSE = "propose"
    REJECT = "reject"


@dataclass
class Decision:
    action: Action
    kind: str
    risk: str
    namespace: str
    reason: str
    hygiene_flags: list[str] = field(default_factory=list)
    readback_ok: Optional[bool] = None


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).casefold()


def hygiene_flags(content: str, source_message: str = "") -> list[str]:
    """Return reasons the content is unfit for durable memory (empty = clean)."""
    flags: list[str] = []
    c = (content or "").strip()
    if len(c) < 8:
        flags.append("too_short")
    if _SECRET_RE.search(c):
        flags.append("contains_secret")
    if _REPLY_RE.search(c):
        flags.append("reply_quote")
    if _QUESTION_RE.search(c):
        flags.append("is_question")
    if _URL_RE.search(c):
        flags.append("contains_url")
    if source_message:
        n_c, n_m = _norm(c), _norm(source_message)
        # Only a TRUE truncation/slice is garbage: the source is meaningfully longer
        # than the stored content AND the content is a verbatim prefix/substring of it.
        # A short, clean instruction the user actually typed (content == source) is NOT
        # a truncated copy — it's the durable fact itself, and must pass.
        if n_c and n_m and len(n_c) >= 20 and len(n_m) >= len(n_c) + 15 \
                and (n_m.startswith(n_c[:60]) or n_c in n_m):
            flags.append("raw_truncated_copy")
    return flags


def classify_kind(candidate: Mapping[str, Any]) -> str:
    declared = str(candidate.get("memory_type") or "").strip()
    reason = str(candidate.get("reason") or "").casefold()
    content = str(candidate.get("object") or candidate.get("content") or "")
    if declared in AUTO_KINDS or declared in ALWAYS_REVIEW_KINDS:
        return declared
    if "correction" in reason or "纠正" in reason or "不对" in content[:6]:
        return "explicit_correction"
    if "preference" in reason or "偏好" in reason or "喜欢" in content[:6]:
        return "explicit_preference"
    if "decision" in reason or "决定" in reason:
        return "decision"
    if declared:
        return declared
    return "chatter"


def assess_risk(candidate: Mapping[str, Any], kind: str, namespace: str) -> str:
    if not namespace or namespace == "core":
        return "high"
    if kind in ALWAYS_REVIEW_KINDS:
        return "high"
    if kind in AUTO_KINDS:
        return "low"
    return "med"


def readback_check(
    *,
    content: str,
    anchor_query: str,
    namespace: str,
    title: str,
    search_fn: Callable[[str, str, int], list[dict]],
    write_fn: Callable[[str, str, str], Optional[str]],
    delete_fn: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """Write to a quarantine namespace, then confirm top-1 retrievability."""
    q_ns = f"quarantine:{namespace}"
    try:
        node_uuid = write_fn(q_ns, title, content)
        if not node_uuid:
            return False
        results = search_fn(anchor_query, q_ns, 5) or []
        return bool(results) and results[0].get("node_uuid") == node_uuid
    except Exception:
        return False
    finally:
        if delete_fn is not None:
            try:
                delete_fn(q_ns, title)
            except Exception:
                pass


def decide(
    candidate: Mapping[str, Any],
    *,
    namespace: str,
    source_message: str = "",
    anchor_query: str = "",
    title: str = "",
    search_fn: Optional[Callable[[str, str, int], list[dict]]] = None,
    write_fn: Optional[Callable[[str, str, str], Optional[str]]] = None,
    delete_fn: Optional[Callable[[str, str], None]] = None,
    enable_auto: bool = False,
) -> Decision:
    content = str(candidate.get("object") or candidate.get("content") or "")
    kind = classify_kind(candidate)
    risk = assess_risk(candidate, kind, namespace)

    if kind == "chatter":
        return Decision(Action.REJECT, kind, risk, namespace, "not a durable memory (chatter)")
    if kind in ALWAYS_REVIEW_KINDS or kind not in AUTO_KINDS:
        return Decision(Action.PROPOSE, kind, risk, namespace, f"kind '{kind}' always needs review")

    flags = hygiene_flags(content, source_message)
    if flags:
        action = Action.REJECT if "contains_secret" in flags or "raw_truncated_copy" in flags else Action.PROPOSE
        return Decision(action, kind, risk, namespace, f"hygiene: {', '.join(flags)}", hygiene_flags=flags)

    if risk == "high":
        return Decision(Action.PROPOSE, kind, risk, namespace, "high-risk namespace, needs review")

    if not (search_fn and write_fn):
        return Decision(Action.PROPOSE, kind, risk, namespace,
                        "readback I/O unavailable; cannot prove retrievability")
    rb = readback_check(
        content=content, anchor_query=anchor_query or content[:40], namespace=namespace,
        title=title or "earned", search_fn=search_fn, write_fn=write_fn, delete_fn=delete_fn,
    )
    if not rb:
        return Decision(Action.PROPOSE, kind, risk, namespace, "readback failed (not retrievable as top-1)",
                        readback_ok=False)

    if not enable_auto:
        return Decision(Action.PROPOSE, kind, risk, namespace,
                        "passes all gates; AUTO disabled (enable_auto=False) — opt in after measuring precision",
                        readback_ok=True)
    return Decision(Action.AUTO_APPLY, kind, risk, namespace, "passed type+hygiene+readback", readback_ok=True)
