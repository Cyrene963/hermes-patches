"""Structured relationship trust-boundary assessment tool."""

from __future__ import annotations

from agent.relationship_boundary import decide_relationship_boundary
from tools.registry import registry


SCHEMA = {
    "name": "relationship_boundary_assess",
    "description": (
        "Assess an observed relationship behavior vector and recommend a calibrated trust/investment tier. "
        "Use observed behavior only; unknown traits must remain 0."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            key: {"type": "number", "minimum": 0, "maximum": 1}
            for key in (
                "reciprocity", "self_reflection", "repair_after_conflict", "reliability",
                "boundary_respect", "personal_attack", "stonewalling", "repeated_extraction",
                "boundary_violation",
            )
        } | {
            "independent_observations": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": False,
    },
}


def _assess(args, **_kwargs):
    return decide_relationship_boundary(args or {}).to_dict()


registry.register(
    name="relationship_boundary_assess",
    toolset="memory_graph",
    schema=SCHEMA,
    handler=_assess,
    emoji="shield",
    description=SCHEMA["description"],
)
