"""Calibrated relationship trust and investment boundary model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RelationshipBoundary:
    tier: str
    trust_score: float
    confidence: float
    investment: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide_relationship_boundary(features: Mapping[str, float | bool]) -> RelationshipBoundary:
    """Recommend a trust tier from observed behavior, not inferred personality."""
    def value(name: str) -> float:
        return max(0.0, min(1.0, float(features.get(name, 0.0))))

    positive = (
        1.3 * value("reciprocity")
        + 1.1 * value("self_reflection")
        + 1.4 * value("repair_after_conflict")
        + 1.2 * value("reliability")
        + 1.3 * value("boundary_respect")
    )
    negative = (
        1.6 * value("personal_attack")
        + 1.3 * value("stonewalling")
        + 1.1 * value("repeated_extraction")
        + 1.2 * value("boundary_violation")
    )
    score = round(positive - negative, 3)
    observations = int(features.get("independent_observations", 0) or 0)
    reasons: list[str] = []
    if value("reciprocity") >= 0.7:
        reasons.append("reciprocity is consistently observed")
    if value("repair_after_conflict") >= 0.7:
        reasons.append("conflict is followed by accountable repair")
    if value("boundary_respect") >= 0.7:
        reasons.append("stated boundaries are respected")
    if value("personal_attack") >= 0.5:
        reasons.append("conflict includes personal attack")
    if value("stonewalling") >= 0.6:
        reasons.append("conflict is handled through prolonged withdrawal")
    if value("boundary_violation") >= 0.5:
        reasons.append("stated boundaries are violated")

    severe = value("personal_attack") >= 0.8 or value("boundary_violation") >= 0.8
    if severe or score <= -1.2:
        return RelationshipBoundary("distance", score, 0.92 if observations >= 3 else 0.78, "protective minimum; no core dependence", tuple(reasons))
    if observations < 3:
        return RelationshipBoundary("observe", score, 0.7, "small reversible tests only", tuple(reasons + ["insufficient independent observations"]))
    if value("repeated_extraction") >= 0.65:
        return RelationshipBoundary(
            "observe", score, 0.86 if observations >= 3 else 0.72,
            "small reversible tests; require demonstrated reciprocity before promotion",
            tuple(reasons + ["repeated extraction caps trust promotion"]),
        )
    if score >= 4.2 and min(
        value("reciprocity"), value("self_reflection"), value("repair_after_conflict"),
        value("reliability"), value("boundary_respect"),
    ) >= 0.8:
        return RelationshipBoundary("core", score, 0.9, "gradually increase mutual reliance", tuple(reasons))
    if score >= 1.2:
        return RelationshipBoundary("limited", score, 0.84, "bounded investment; keep trust domain-specific", tuple(reasons))
    return RelationshipBoundary("observe", score, 0.8, "small reversible tests; do not promote trust yet", tuple(reasons))


__all__ = ["RelationshipBoundary", "decide_relationship_boundary"]
