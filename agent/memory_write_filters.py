"""Quality gates for Memory Write Pipeline candidates.

These filters reject obvious low-quality or runtime-generated memory candidates
without discarding high-value user-authored facts such as corrections, exam
context, creative target functions, or durable workflow lessons.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional, Tuple


@dataclass(frozen=True)
class MemoryQualityDecision:
    accepted: bool
    reason: str = ""
    requires_review: bool = False


LOW_INFORMATION_SUBJECTS = {
    "",
    "user",
    "operation",
    "[SILENT]",
}

SYSTEM_EVENT_SUBJECTS = {
    "system_event",
    "tool_result",
    "assistant_response",
}

WRAPPER_MARKERS = (
    "[IMPORTANT: The user has invoked the",
    "The full skill content is loaded below",
    "<available_skills>",
    "metadata:\n  hermes:",
    "Context wrapper only:",
    "Do not treat this wrapper as a confirmed project fact",
)

LOG_OR_JSON_SHAPES = (
    r"^\s*\{\s*\"(?:id|status|error|reason|score|timestamp)\"",
    r"^\s*\[[A-Z_ -]{3,}\]\s*$",
    r"^\s*(?:INFO|WARN|WARNING|ERROR|DEBUG)[:\s]",
)

CONVERSATIONAL_FRAGMENT_STARTS = (
    r"^\s*(?:对|是的|好的|可以|不是|ok|okay|yes|sure)[，。,!.\s]+$",
    r"^\s*(?:你说得对|我觉得|I think|you are right)\b",
)

META_MEMORY_ASSESSMENT_PATTERNS = (
    r"(?:是不是|是否|也就是说).{0,24}(?:99%|数字替身|外置大脑)",
    r"(?:单论|当前|现在).{0,24}(?:记忆系统|补丁项目).{0,24}(?:99%|数字替身|外置大脑)",
    r"(?:距离|达到|已经是).{0,24}(?:99%|数字替身|外置大脑).{0,8}[？?]",
)

DURABLE_SUBJECTS = {
    "agent_memory_workflow",
    "tool_credential_route",
    "exam_context",
    "creative_target_function",
    "target_function",
    "active_workstream_context",
    "project_identity_verification",
    "explicit_memory_request",
    "procedural_rule",
}

DURABLE_MEMORY_TYPES = {
    "user_fact",
    "project_fact",
    "preference",
    "rule",
    "decision",
    "lesson",
    "target_function",
    "procedural_memory",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _has_wrapper_marker(text: str) -> bool:
    return any(marker in (text or "") for marker in WRAPPER_MARKERS)


def _is_log_or_json_fragment(text: str) -> bool:
    return any(re.search(pattern, text or "", re.I) for pattern in LOG_OR_JSON_SHAPES)


def _is_conversational_fragment(subject: str, content: str) -> bool:
    combined = _clean(f"{subject} {content}")
    return any(re.search(pattern, combined, re.I) for pattern in CONVERSATIONAL_FRAGMENT_STARTS)


def _is_meta_memory_assessment_question(text: str) -> bool:
    cleaned = _clean(text)
    if not cleaned:
        return False
    return any(re.search(pattern, cleaned, re.I) for pattern in META_MEMORY_ASSESSMENT_PATTERNS)


def evaluate_memory_candidate_quality(
    *,
    subject: str,
    predicate: str,
    object_value: str,
    memory_type: str,
    source_type: str,
    evidence_quote: str = "",
    importance: float = 0.0,
    confidence: float = 0.0,
) -> MemoryQualityDecision:
    """Return a conservative accept/review/reject decision for a candidate.

    This is not a semantic classifier. It only blocks obvious garbage created by
    wrappers, logs, empty/generic fragments, or system events. Durable user
    signals are allowed through to the existing review/auto-write gates.
    """
    subject_clean = _clean(subject)
    object_clean = _clean(object_value)
    evidence_clean = _clean(evidence_quote)
    combined = f"{subject}\n{predicate}\n{object_value}\n{evidence_quote}"

    if _has_wrapper_marker(combined):
        return MemoryQualityDecision(False, "system_or_context_wrapper_fragment")

    if source_type == "system_event" or subject_clean in SYSTEM_EVENT_SUBJECTS:
        return MemoryQualityDecision(False, "system_event_candidate")

    if _is_log_or_json_fragment(object_clean) or _is_log_or_json_fragment(evidence_clean):
        return MemoryQualityDecision(False, "log_or_json_fragment")

    if _is_conversational_fragment(subject_clean, object_clean):
        return MemoryQualityDecision(False, "low_information_conversational_fragment")

    if _is_meta_memory_assessment_question(object_clean) or _is_meta_memory_assessment_question(evidence_clean):
        return MemoryQualityDecision(False, "meta_memory_assessment_question_not_a_durable_fact")

    if subject_clean in LOW_INFORMATION_SUBJECTS:
        durable = (
            memory_type in DURABLE_MEMORY_TYPES
            and object_clean
            and len(object_clean) >= 20
            and source_type in {"user_direct", "user_correction"}
            and max(float(importance or 0.0), float(confidence or 0.0)) >= 0.75
        )
        if not durable:
            return MemoryQualityDecision(False, "generic_subject_without_durable_content")
        return MemoryQualityDecision(True, "generic_subject_requires_review", requires_review=True)

    if not object_clean or len(object_clean) < 12:
        short_but_durable = (
            source_type == "user_correction"
            and memory_type in DURABLE_MEMORY_TYPES
            and subject_clean
            and max(float(importance or 0.0), float(confidence or 0.0)) >= 0.75
        )
        if subject_clean not in DURABLE_SUBJECTS and not short_but_durable:
            return MemoryQualityDecision(False, "content_too_short")

    if subject_clean in DURABLE_SUBJECTS:
        return MemoryQualityDecision(True, "durable_subject_allowed")

    return MemoryQualityDecision(True, "accepted")


__all__ = ["MemoryQualityDecision", "evaluate_memory_candidate_quality"]
