"""Cross-domain decision consistency checker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CrossDomainVerdict:
    status: str
    score: float
    shared_principles: tuple[str, ...]
    contradictions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_POSITIVE = {"reversible_test", "real_evidence", "bounded_investment", "explicit_criteria", "review_and_adjust"}
_NEGATIVE_PAIRS = {
    "reversible_test": "irreversible_commitment",
    "real_evidence": "claim_without_evidence",
    "bounded_investment": "unbounded_investment",
    "explicit_criteria": "undefined_success",
    "review_and_adjust": "ignore_feedback",
}


def evaluate_cross_domain_consistency(domains: Mapping[str, list[str] | tuple[str, ...]]) -> CrossDomainVerdict:
    """Check whether decisions across domains implement the same evidence principles."""
    clean = {str(domain): {str(tag) for tag in tags} for domain, tags in domains.items() if tags}
    if len(clean) < 2:
        return CrossDomainVerdict("unknown", 0.0, (), ("fewer than two domains have evidence",))
    shared = set.intersection(*(tags & _POSITIVE for tags in clean.values()))
    contradictions: list[str] = []
    for domain, tags in clean.items():
        for positive, negative in _NEGATIVE_PAIRS.items():
            if negative in tags:
                contradictions.append(f"{domain}:{negative}")
    coverage = sum(len(tags & _POSITIVE) / len(_POSITIVE) for tags in clean.values()) / len(clean)
    shared_ratio = len(shared) / len(_POSITIVE)
    score = round(0.65 * coverage + 0.35 * shared_ratio, 3)
    if contradictions:
        return CrossDomainVerdict("inconsistent", score, tuple(sorted(shared)), tuple(sorted(contradictions)))
    if score >= 0.75 and len(shared) >= 3:
        return CrossDomainVerdict("consistent", score, tuple(sorted(shared)), ())
    return CrossDomainVerdict("qualify", score, tuple(sorted(shared)), ())


__all__ = ["CrossDomainVerdict", "evaluate_cross_domain_consistency"]
