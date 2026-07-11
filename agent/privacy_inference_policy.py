"""Sensitive inference refusal and identity-boundary policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


_SENSITIVE = {
    "health", "mental_health", "sexuality", "religion", "politics", "finances",
    "credentials", "precise_location", "private_relationship_identity", "cross_user_fact",
}


@dataclass(frozen=True)
class PrivacyInferenceDecision:
    action: str
    confidence: float
    reason: str
    safe_response: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide_sensitive_inference(features: Mapping[str, Any]) -> PrivacyInferenceDecision:
    category = str(features.get("category") or "").strip().lower()
    explicit = bool(features.get("explicit_user_statement", False))
    confirmed = bool(features.get("confirmed_current_namespace_evidence", False))
    namespace_match = bool(features.get("namespace_match", False))
    source_role = str(features.get("source_role") or "unknown").strip().lower()
    raw_secret = bool(features.get("would_expose_raw_secret", False))
    requested = bool(features.get("user_requested_use", False))

    if raw_secret or category == "credentials":
        return PrivacyInferenceDecision("refuse", 0.99, "raw secrets or credentials must not be inferred or exposed", "I can help verify configuration safely without revealing or guessing credentials.")
    if not namespace_match or category == "cross_user_fact":
        return PrivacyInferenceDecision("refuse", 0.99, "evidence belongs to another or unknown namespace", "I cannot use another user's private information for this claim.")
    if source_role in {"assistant", "model", "external_model"} and not explicit:
        return PrivacyInferenceDecision("refuse", 0.98, "model-generated analysis is not a user fact", "I do not have a confirmed user statement supporting that inference.")
    if category in _SENSITIVE:
        if explicit and confirmed and requested:
            return PrivacyInferenceDecision("allow_bounded", 0.95, "explicit confirmed same-namespace statement requested by the user", "Use only the confirmed fact needed for the current task; do not expand it into new sensitive inferences.")
        return PrivacyInferenceDecision("refuse", 0.97, "sensitive inference lacks explicit confirmed consent", "I cannot infer that sensitive attribute from indirect behavior, text, images, or third-party analysis.")
    if confirmed and namespace_match:
        return PrivacyInferenceDecision("allow", 0.9, "non-sensitive confirmed same-namespace fact", "Use the minimum confirmed fact needed for the task.")
    return PrivacyInferenceDecision("abstain", 0.75, "claim lacks confirmed evidence", "I do not have enough confirmed evidence to state that as fact.")


__all__ = ["PrivacyInferenceDecision", "decide_sensitive_inference"]
