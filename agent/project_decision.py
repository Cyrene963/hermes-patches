"""Evidence-grounded project proposal decision model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ProjectDecision:
    decision: str
    score: float
    confidence: float
    reasons: tuple[str, ...]
    required_next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFAULT_WEIGHTS = {
    "pain_frequency": 1.4,
    "solo_start": 1.0,
    "dogfood": 1.0,
    "external_system_data": 1.3,
    "distribution": 0.8,
    "cold_start_dependency": -1.5,
    "institution_dependency": -1.4,
    "ai_wrapper_only": -1.6,
    "core_asset_placeholder": -1.8,
    "implementation_scope": -0.5,
}


def decide_project_proposal(
    features: Mapping[str, float | bool],
    *,
    weights: Mapping[str, float] | None = None,
) -> ProjectDecision:
    """Score explicit proposal features and return a calibrated decision."""
    policy = {**_DEFAULT_WEIGHTS, **dict(weights or {})}
    normalized = {key: max(0.0, min(1.0, float(features.get(key, 0.0)))) for key in policy}
    score = sum(policy[key] * normalized[key] for key in policy)
    reasons: list[str] = []

    for key, label in (
        ("cold_start_dependency", "depends on a cold-start network"),
        ("institution_dependency", "depends on institution endorsement"),
        ("ai_wrapper_only", "offers little value beyond direct AI chat"),
        ("core_asset_placeholder", "leaves a core product asset as a placeholder"),
    ):
        if normalized[key] >= 0.7:
            reasons.append(label)
    for key, label in (
        ("pain_frequency", "addresses a frequent concrete pain"),
        ("dogfood", "supports real first-party dogfood"),
        ("external_system_data", "has system/data value beyond prompting"),
        ("distribution", "has a plausible distribution path"),
    ):
        if normalized[key] >= 0.7:
            reasons.append(label)

    experiment = bool(features.get("measurable_experiment", False))
    large_scope = normalized["implementation_scope"] >= 0.75
    if normalized["core_asset_placeholder"] >= 0.85:
        return ProjectDecision(
            "reject", round(score, 3), 0.94, tuple(reasons),
            "replace the core placeholder with a real inspectable asset before evaluation",
        )
    hard_dependency = any(normalized[key] >= 0.85 for key in (
        "cold_start_dependency", "institution_dependency", "ai_wrapper_only"
    ))
    if hard_dependency and score < 1.2:
        return ProjectDecision("reject", round(score, 3), 0.92, tuple(reasons), "remove the hard dependency or choose another proposal")
    if large_scope and not experiment:
        return ProjectDecision("experiment", round(score, 3), 0.88, tuple(reasons), "define a minimum comparison experiment with continue/stop thresholds")
    if score >= 3.0:
        return ProjectDecision("accept", round(score, 3), 0.9, tuple(reasons), "build the smallest real dogfood slice")
    if score >= 1.2:
        return ProjectDecision("pilot", round(score, 3), 0.82, tuple(reasons), "run a bounded pilot before expanding scope")
    return ProjectDecision("reject", round(score, 3), 0.84, tuple(reasons), "select a higher-frequency, lower-dependency problem")


__all__ = ["ProjectDecision", "decide_project_proposal"]
