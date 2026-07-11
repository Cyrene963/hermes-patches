"""Evidence calibration and abstention policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ConfidenceDecision:
    action: str
    confidence: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calibrate_confidence(features: Mapping[str, Any]) -> ConfidenceDecision:
    def val(name: str, default: float = 0.0) -> float:
        return max(0.0, min(1.0, float(features.get(name, default))))

    directness = val("directness")
    consistency = val("consistency")
    recency = val("recency")
    namespace_match = val("namespace_match")
    source_count = max(0, int(features.get("independent_sources", 0) or 0))
    confirmed = bool(features.get("explicit_user_confirmation", False))
    conflict = bool(features.get("unresolved_conflict", False))
    sensitive_inference = bool(features.get("sensitive_inference", False))
    reasons: list[str] = []

    if namespace_match < 1:
        return ConfidenceDecision("abstain", 0.0, ("evidence is outside the active namespace",))
    if sensitive_inference and not confirmed:
        return ConfidenceDecision("abstain", 0.0, ("sensitive claim lacks explicit user confirmation",))
    if conflict:
        return ConfidenceDecision("abstain", 0.0, ("latest evidence is unresolved or conflicting",))
    if source_count == 0:
        return ConfidenceDecision("abstain", 0.0, ("no supporting source",))

    source_strength = min(1.0, 0.45 + 0.2 * min(source_count, 3))
    score = 0.32 * directness + 0.26 * consistency + 0.18 * recency + 0.16 * source_strength
    if confirmed:
        score += 0.08
        reasons.append("explicitly confirmed by the user")
    if directness < 0.6:
        reasons.append("evidence is indirect")
    if recency < 0.5:
        reasons.append("evidence may be stale")
    if consistency < 0.7:
        reasons.append("sources are only partially consistent")
    score = round(max(0.0, min(0.99, score)), 3)

    if score >= 0.8:
        return ConfidenceDecision("answer", score, tuple(reasons or ["direct current consistent evidence"]))
    if score >= 0.55:
        return ConfidenceDecision("qualify", score, tuple(reasons or ["moderate evidence; state uncertainty"]))
    return ConfidenceDecision("abstain", score, tuple(reasons or ["evidence is too weak for a reliable claim"]))


__all__ = ["ConfidenceDecision", "calibrate_confidence"]
