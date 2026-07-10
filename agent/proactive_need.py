"""Evidence-bound proactive next-action policy for digital-twin behavior."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ProactiveNeedDecision:
    action: str
    confidence: float
    reason: str
    next_step: str = ""
    evidence_uris: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_READ_ONLY_RE = re.compile(
    r"(只读|只审计|不要修改|别修改|不要写|audit only|read[- ]only|do not (change|modify|write))",
    re.I,
)
_EXPLICIT_ACTION_RE = re.compile(
    r"(去修|直接修|立刻修|继续做|继续推进|授权|全权|直接执行|去做|修复它|"
    r"fix it|go ahead|continue working|proceed|you are authorized)",
    re.I,
)
_FAILURE_RE = re.compile(
    r"(坏了|报错|失败|崩溃|没跑|没生效|不工作|有问题|泄漏|"
    r"broken|error|failed|crash|not working|did not run|leak)",
    re.I,
)
_HIGH_RISK_RE = re.compile(
    r"(删除|清空|付款|购买|发布|群发|发送给|生产部署|改密码|改凭据|转账|"
    r"delete|drop database|payment|purchase|publish|broadcast|send to|production deploy|rotate credential)",
    re.I,
)
_QUESTION_ONLY_RE = re.compile(
    r"^(什么是|为什么|如何理解|解释|介绍|what is|why |explain|tell me about)",
    re.I,
)
_EMOTIONAL_RE = re.compile(
    r"(难过|生气|孤独|关系|朋友|吵架|情绪|hurt|angry|lonely|relationship|friendship)",
    re.I,
)


def decide_proactive_need(
    user_message: str,
    *,
    obligations: Iterable[Any] = (),
    active_todos: Iterable[dict[str, Any]] = (),
    evidence_uris: Iterable[str] = (),
    task_verified_complete: bool = False,
) -> ProactiveNeedDecision:
    """Choose the safest useful proactive behavior from explicit evidence."""
    text = str(user_message or "").strip()
    obligations = list(obligations)
    todos = [
        item for item in active_todos
        if str(item.get("status") or "").lower() in {"pending", "in_progress"}
    ]
    obligation_ids = {
        str(getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else ""))
        for item in obligations
    }
    standing = "autonomy.continue_until_verified" in obligation_ids
    evidence = tuple(dict.fromkeys(str(uri) for uri in evidence_uris if uri))[:8]

    if _READ_ONLY_RE.search(text):
        return ProactiveNeedDecision("diagnose", 0.98, "explicit read-only boundary", "inspect and report without mutation", evidence)
    if task_verified_complete and not standing and not todos:
        return ProactiveNeedDecision("stop", 0.97, "verified complete with no standing obligation", evidence_uris=evidence)
    if _HIGH_RISK_RE.search(text) and not _EXPLICIT_ACTION_RE.search(text):
        return ProactiveNeedDecision("clarify", 0.96, "high-risk side effect lacks explicit authorization", "confirm target and scope", evidence)
    if _QUESTION_ONLY_RE.search(text) or (_EMOTIONAL_RE.search(text) and not _EXPLICIT_ACTION_RE.search(text)):
        return ProactiveNeedDecision("answer_only", 0.94, "informational or reflective request has no action mandate", evidence_uris=evidence)
    if standing and (todos or not task_verified_complete):
        next_step = str(todos[0].get("content") or todos[0].get("id") or "execute the next verified work unit") if todos else "execute the next verified work unit"
        return ProactiveNeedDecision("act", 0.96, "standing autonomy obligation remains open", next_step, evidence)
    if _EXPLICIT_ACTION_RE.search(text):
        return ProactiveNeedDecision("act", 0.93, "explicit action authorization", "execute the safest concrete next step and verify it", evidence)
    if _FAILURE_RE.search(text):
        return ProactiveNeedDecision("diagnose", 0.88, "reported failure supports read-only diagnosis, not unbounded mutation", "inspect the failing path and gather evidence", evidence)
    return ProactiveNeedDecision("answer_only", 0.82, "no evidence-backed proactive action mandate", evidence_uris=evidence)


__all__ = ["ProactiveNeedDecision", "decide_proactive_need"]
