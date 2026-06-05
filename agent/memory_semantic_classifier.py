"""Semantic memory classifier for Memory OS.

This module is intentionally generic and fail-closed. It defines a structured
classification schema for durable conversational memory candidates. A caller may
supply an LLM function for semantic classification; when no model is available,
it falls back to the conservative existing P0 guard behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Callable, Dict, List, Mapping, Optional
import json
import re

MEMORY_KINDS = {
    "user_fact", "project_fact", "target_function", "procedural_rule",
    "credential_route", "exam_context", "creative_preference",
    "correction_learning_event", "ignore", "temporary",
}

TARGET_STORES = {"memory_graph", "memory_md", "hindsight", "review", "ignore"}
PRIVACY_SCOPES = {"user_private", "project", "shared_public", "sensitive", "review"}


@dataclass
class SemanticMemoryClassification:
    memory_kind: str
    durability: str
    confidence: float
    evidence_quote: str
    target_store: str
    target_path: str
    requires_review: bool
    privacy_scope: str
    readback_queries: List[str] = field(default_factory=list)
    reject_gate: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clamp_conf(value: Any) -> float:
    try:
        f = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, f))


def _safe_excerpt(text: str, limit: int = 300) -> str:
    return (text or "").strip().replace("\x00", "")[:limit]


def _fail_closed(source_text: str, reason: str = "model classifier failed closed") -> SemanticMemoryClassification:
    """Return a non-writing review candidate when model classification is unavailable/invalid.

    When an operator explicitly enables a model-backed classifier, invalid JSON or
    tool failure must not fall back to local heuristics that might write. The safe
    state is shadow/review with no automatic Graph mutation.
    """
    return SemanticMemoryClassification(
        memory_kind="ignore",
        durability="none",
        confidence=0.0,
        evidence_quote=_safe_excerpt(source_text, 400),
        target_store="review",
        target_path="",
        requires_review=True,
        privacy_scope="review",
        readback_queries=[],
        reject_gate="",
        reason=reason,
    )


def build_model_classifier_prompt(user_message: str, assistant_message: str = "") -> str:
    """Build a generic JSON-only classifier prompt. No deployment-local names/paths."""
    return json.dumps({
        "task": "Classify whether the user's message contains a durable memory candidate. Return JSON only.",
        "schema": {
            "memory_kind": sorted(MEMORY_KINDS),
            "durability": "none|minutes|session|until_superseded|long_term",
            "confidence": "0.0-1.0",
            "evidence_quote": "short quote from user text only",
            "target_store": sorted(TARGET_STORES),
            "target_path": "generic caller-chosen path; no raw secrets",
            "requires_review": "boolean",
            "privacy_scope": sorted(PRIVACY_SCOPES),
            "readback_queries": "future phrasing queries for top-result verification",
            "reject_gate": "procedural guard if the event is a correction",
            "reason": "short explanation",
        },
        "rules": [
            "Do not store raw secrets; credential_route stores only lookup route/procedure.",
            "Inferred preferences require review.",
            "User corrections may produce procedural_rule/correction_learning_event and reject_gate.",
            "Temporary mood/state and acknowledgements should be ignore/temporary.",
            "Generate future-phrased readback_queries for retrievability.",
            "If uncertain, target_store=review and requires_review=true.",
        ],
        "user_message": _safe_excerpt(user_message, 1200),
        "assistant_message": _safe_excerpt(assistant_message, 800),
    }, ensure_ascii=False)


def _queries(subject: str, text: str, kind: str) -> List[str]:
    body = _safe_excerpt(text, 120)
    candidates = [f"{subject} {kind}", body]
    if kind == "credential_route":
        candidates.extend(["tool credential route", "凭据 工具 查找 路线"])
    elif kind == "exam_context":
        candidates.extend(["exam context subjects timetable", "考试 科目 时间表 复习"])
    elif kind in {"target_function", "creative_preference"}:
        candidates.extend(["creative target function", "写作 审美 目标函数"])
    elif kind == "correction_learning_event":
        candidates.extend(["user correction root cause prevent recurrence", "用户纠错 根因 防复发"])
    seen, out = set(), []
    for q in candidates:
        q = q.strip()
        if q and q not in seen:
            seen.add(q); out.append(q)
    return out[:5]


def _fallback_classify(user_message: str, assistant_message: str = "") -> SemanticMemoryClassification:
    """Conservative local fallback used when no model classifier is available.

    This is NOT the preferred upstream-quality detector; it is a fail-closed
    safety net so P0 user-correction/credential/exam/creative signals do not
    disappear when the model classifier is unavailable.
    """
    text = _safe_excerpt(user_message, 1200)
    lower = text.lower()

    if not text:
        return SemanticMemoryClassification("ignore", "none", 0.0, "", "ignore", "", False, "review", [], reason="empty input")

    if re.search(r"^(哈哈|嗯|好的|可以|ok|OK|行|好)$", text.strip()):
        return SemanticMemoryClassification("ignore", "none", 0.95, text, "ignore", "", False, "review", [], reason="low-information acknowledgement")

    if re.search(r"^(继续|continue|go on)$", text.strip(), re.I) or re.search(r"(刚刚|刚才|之前).{0,12}继续", text.strip()):
        return SemanticMemoryClassification(
            "active_workstream_context", "session", 0.82, text, "review", "用户档案/程序性记忆",
            True, "user_private", _queries("active_workstream_context", text, "active_workstream_context"),
            "Before answering a bare continuation, recover the active workstream and execute the next safe step instead of asking the user to repeat context.",
            "bare continuation should route through active-context recall",
        )

    if re.search(r"(这是|这个).{0,20}(我的|用户的).{0,10}(ai|AI|项目|project).{0,10}(项目|吗|么|是不是)", text):
        return SemanticMemoryClassification(
            "project_identity_verification", "long_term", 0.82, text, "review", "用户档案/程序性记忆",
            True, "user_private", _queries("project_identity_verification", text, "project_identity_verification"),
            "Before deciding whether something is the user's AI project, inspect project inventory and candidate project nodes instead of inferring from nearby context.",
            "project identity questions require explicit inventory verification",
        )

    if re.search(r"(长期记住|把这个.*记住|记住这个|remember this|save this|以后遇到同类)", text, re.I):
        return SemanticMemoryClassification(
            "explicit_memory_request", "long_term", 0.86, text, "review", "用户档案/程序性记忆",
            True, "user_private", _queries("explicit_memory_request", text, "explicit_memory_request"),
            "Explicit memory requests must be routed to the correct durable store and verified with readback before assuming they are learned.",
            "user explicitly requested durable memory/readback behavior",
        )

    if re.search(r"(claude code|claude|codex|github|token|pat|api key|凭据|not logged in|登录|auth)", lower, re.I):
        return SemanticMemoryClassification(
            "credential_route", "long_term", 0.86, text, "memory_graph", "用户档案/工具凭据查找规则",
            True, "sensitive", _queries("tool_credential_route", text, "credential_route"),
            "Never print raw secrets; search memory/session/config/secret paths before saying credentials are missing.",
            "tool/auth mention requires safe credential-route memory",
        )

    if re.search(r"(纠正|错了|错错错|不对|不是|又没|太气人|防复发|根因|通用.*解决|reject gate|数字替身|外置大脑|有必要吗|之前.*聊过|先回忆|先召回|项目目标)", text, re.I):
        return SemanticMemoryClassification(
            "correction_learning_event", "long_term", 0.88, text, "memory_graph", "用户档案/程序性记忆",
            True, "user_private", _queries("agent_memory_workflow", text, "correction_learning_event"),
            "Before replying to similar future context, recall prior correction, identify root cause, apply a reject gate, implement/test a reusable guard, then persist the lesson.",
            "user correction should become procedural memory/reject gate, not a one-off note",
        )

    # A temporary state plus an explicit durable preference is still durable.
    if re.search(r"(我|用户).{0,20}(喜欢|偏好|讨厌|不喜欢|更关心|在意)", text) or re.search(r"\b(I|we)\s+(prefer|care about|value|like|dislike)\b", text, re.I):
        return SemanticMemoryClassification(
            "user_fact", "long_term", 0.78, text, "memory_graph", "用户档案/偏好",
            False, "user_private", _queries("user_preference", text, "user_fact"),
            "", "explicit user preference",
        )

    if re.search(r"(我现在|现在).{0,8}(困|累|饿|睡)", text):
        return SemanticMemoryClassification("temporary", "minutes", 0.9, text, "ignore", "", False, "review", [], reason="temporary state")

    if re.search(r"(考试|时间表|范围|复习|mock|dse|下周|明天).{0,80}(考试|时间表|范围|复习|科目|dse|mock)", text, re.I):
        return SemanticMemoryClassification(
            "exam_context", "until_superseded", 0.84, text, "memory_graph", "用户档案/考试上下文",
            False, "user_private", _queries("exam_context", text, "exam_context"),
            "Before making study plans, recall the learner's curriculum, subjects, exam dates, and scope.",
            "exam planning context is durable for future schedules",
        )

    if re.search(r"(小说|写作|低频心跳|漫画|审美|ai味|ai 味|文学|角色|叙事|风格)", text, re.I) and re.search(r"(应该|不要|别|避免|偏好|喜欢|标准|质感|目标|感觉|不像)", text):
        return SemanticMemoryClassification(
            "creative_preference", "long_term", 0.84, text, "memory_graph", "用户档案/目标函数/创作审美",
            False, "user_private", _queries("creative_target_function", text, "creative_preference"),
            "Before creative output, recall user-specific taste and reject AI-ish/generic prose or visuals.",
            "durable creative taste / target function",
        )

    if re.search(r"(我|用户).{0,20}(喜欢|偏好|讨厌|不喜欢|更关心|在意)", text):
        return SemanticMemoryClassification(
            "user_fact", "long_term", 0.78, text, "memory_graph", "用户档案/偏好",
            False, "user_private", _queries("user_preference", text, "user_fact"),
            "", "explicit user preference",
        )

    return SemanticMemoryClassification("ignore", "none", 0.65, text, "ignore", "", False, "review", [], reason="no durable semantic memory detected")


def _validate(obj: Mapping[str, Any], source_text: str) -> SemanticMemoryClassification:
    kind = str(obj.get("memory_kind") or "ignore")
    if kind not in MEMORY_KINDS:
        kind = "ignore"
    target = str(obj.get("target_store") or ("ignore" if kind in {"ignore", "temporary"} else "review"))
    if target not in TARGET_STORES:
        target = "review"
    scope = str(obj.get("privacy_scope") or "review")
    if scope not in PRIVACY_SCOPES:
        scope = "review"
    conf = _clamp_conf(obj.get("confidence", 0.0))
    requires_review = bool(obj.get("requires_review", False)) or conf < 0.75 or scope == "sensitive"
    if kind in {"ignore", "temporary"}:
        target = "ignore"; requires_review = False
    return SemanticMemoryClassification(
        memory_kind=kind,
        durability=str(obj.get("durability") or ("none" if kind in {"ignore", "temporary"} else "long_term")),
        confidence=conf,
        evidence_quote=_safe_excerpt(str(obj.get("evidence_quote") or source_text), 400),
        target_store=target,
        target_path=_safe_excerpt(str(obj.get("target_path") or ""), 160),
        requires_review=requires_review,
        privacy_scope=scope,
        readback_queries=[_safe_excerpt(str(q), 160) for q in (obj.get("readback_queries") or []) if str(q).strip()][:5],
        reject_gate=_safe_excerpt(str(obj.get("reject_gate") or ""), 400),
        reason=_safe_excerpt(str(obj.get("reason") or ""), 400),
    )


def classify_memory_semantics(user_message: str, assistant_message: str = "", model_classifier: Optional[Callable[[str], str | Mapping[str, Any]]] = None) -> SemanticMemoryClassification:
    """Classify a conversation turn into a durable-memory schema.

    model_classifier receives a JSON-schema prompt and must return a JSON object
    or JSON text. If it fails or returns invalid data, this function fails closed
    to the conservative local fallback.
    """
    source = _safe_excerpt(user_message, 1200)
    if model_classifier is None:
        return _fallback_classify(user_message, assistant_message)
    schema_prompt = build_model_classifier_prompt(user_message, assistant_message)
    try:
        raw = model_classifier(schema_prompt)
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, Mapping):
            raise ValueError("classifier did not return object")
        return _validate(raw, source)
    except Exception as exc:
        return _fail_closed(source, f"model classifier failed closed: {exc.__class__.__name__}")


__all__ = ["SemanticMemoryClassification", "classify_memory_semantics", "build_model_classifier_prompt", "MEMORY_KINDS"]
