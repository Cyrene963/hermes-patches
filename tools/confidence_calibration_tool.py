"""Evidence confidence calibration and abstention tool."""

from agent.confidence_calibration import calibrate_confidence
from tools.registry import registry

SCHEMA = {
    "name": "confidence_calibrate",
    "description": "Calibrate whether to answer, qualify, or abstain from a claim using directness, consistency, recency, namespace, source count, conflict, and confirmation evidence.",
    "parameters": {
        "type": "object",
        "properties": {
            "directness": {"type": "number", "minimum": 0, "maximum": 1},
            "consistency": {"type": "number", "minimum": 0, "maximum": 1},
            "recency": {"type": "number", "minimum": 0, "maximum": 1},
            "namespace_match": {"type": "number", "minimum": 0, "maximum": 1},
            "independent_sources": {"type": "integer", "minimum": 0},
            "explicit_user_confirmation": {"type": "boolean"},
            "unresolved_conflict": {"type": "boolean"},
            "sensitive_inference": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
}


def _calibrate(args, **_kwargs):
    return calibrate_confidence(args or {}).to_dict()

registry.register(name="confidence_calibrate", toolset="memory_graph", schema=SCHEMA, handler=_calibrate, emoji="gauge", description=SCHEMA["description"])
