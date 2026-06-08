"""
Canonical data model for structured long-term memory facts.

CanonicalFact is the fundamental unit of knowledge in the memory graph.
Every fact carries provenance (source, evidence IDs), lifecycle metadata,
and a review state so that the system can reason about staleness, conflicts,
and confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CanonicalFact:
    """Structured long-term memory fact.

    A CanonicalFact represents a single, well-defined piece of knowledge
    about a subject.  Facts are versioned via ``status`` and ``supersedes``
    so that the graph can track how knowledge evolves over time.

    Attributes:
        subject:       The entity this fact is about, e.g. "alice", "project_x".
        subject_type:  Category of the subject, e.g. "person", "project",
                       "rule", "decision".
        predicate:     The relationship or attribute, e.g. "age",
                       "tech_stack", "exam_score".
        object:        Structured value of the fact (dict to allow nested data).
        status:        Lifecycle status — one of "current", "candidate",
                       "superseded", "conflicted", "deprecated".
        confidence:    Confidence score between 0.0 and 1.0.
        source_type:   How the fact was acquired — "user_direct",
                       "agent_inferred", "evidence_import", "manual".
        evidence_ids:  List of evidence store IDs that support this fact.
        namespace:     Tenant namespace this fact belongs to.
        valid_from:    ISO-8601 timestamp when the fact became valid.
        valid_to:      ISO-8601 timestamp when the fact expired (None if still valid).
        supersedes:    List of fact IDs that this fact replaces.
        review_state:  Review status — "approved", "pending", "rejected".
        lifecycle:     Expected change frequency — "permanent",
                       "slow_changing", "time_bound", "ephemeral".
    """

    subject: str
    subject_type: str
    predicate: str
    object: Dict
    status: str = "candidate"
    confidence: float = 0.5
    source_type: str = "agent_inferred"
    evidence_ids: List[str] = field(default_factory=list)
    namespace: str = ""
    valid_from: str = ""
    valid_to: Optional[str] = None
    supersedes: List[str] = field(default_factory=list)
    review_state: str = "pending"
    lifecycle: str = "slow_changing"
