"""Strict completion-evidence assessment tool."""

from __future__ import annotations

from agent.completion_fidelity import evaluate_completion_evidence
from tools.registry import registry


SCHEMA = {
    "name": "completion_evidence_assess",
    "description": "Evaluate declared acceptance requirements against real artifact, command, API, and TODO evidence. Missing or semantic mismatches fail closed.",
    "parameters": {
        "type": "object",
        "properties": {
            "requirements": {"type": "array", "items": {"type": "object"}},
            "evidence": {"type": "object"},
        },
        "required": ["requirements", "evidence"],
        "additionalProperties": False,
    },
}


def _assess(args, **_kwargs):
    return evaluate_completion_evidence(args.get("requirements") or [], args.get("evidence") or {}).to_dict()


registry.register(
    name="completion_evidence_assess",
    toolset="memory_graph",
    schema=SCHEMA,
    handler=_assess,
    emoji="check",
    description=SCHEMA["description"],
)
