"""Structured project proposal assessment tool."""

from __future__ import annotations

from agent.project_decision import decide_project_proposal
from tools.registry import registry


PROJECT_DECISION_SCHEMA = {
    "name": "project_decision_assess",
    "description": (
        "Assess an explicitly extracted project feature vector against a generic, "
        "configurable decision model. Unknown features must remain 0; do not invent evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            key: {"type": "number", "minimum": 0, "maximum": 1}
            for key in (
                "pain_frequency", "solo_start", "dogfood", "external_system_data",
                "distribution", "cold_start_dependency", "institution_dependency",
                "ai_wrapper_only", "core_asset_placeholder", "implementation_scope",
            )
        } | {
            "measurable_experiment": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
}


def _assess(args, **_kwargs):
    return decide_project_proposal(args or {}).to_dict()


registry.register(
    name="project_decision_assess",
    toolset="memory_graph",
    schema=PROJECT_DECISION_SCHEMA,
    handler=_assess,
    emoji="target",
    description=PROJECT_DECISION_SCHEMA["description"],
)


__all__ = ["PROJECT_DECISION_SCHEMA", "_assess"]
