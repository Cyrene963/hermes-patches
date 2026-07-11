"""Time-conditioned self-model resolution tool."""

from __future__ import annotations

from agent.temporal_self_model import resolve_temporal_observation
from tools.registry import registry


SCHEMA = {
    "name": "temporal_self_resolve",
    "description": "Resolve which versioned observation was valid at a requested time; future facts never leak into historical answers.",
    "parameters": {
        "type": "object",
        "properties": {
            "as_of": {"type": "string", "description": "ISO-8601 timestamp"},
            "observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {},
                        "effective_at": {"type": "string"},
                        "observed_at": {"type": "string"},
                        "valid_to": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "explicit_correction": {"type": "boolean"},
                        "evidence_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "required": ["as_of", "observations"],
        "additionalProperties": False,
    },
}


def _resolve(args, **_kwargs):
    return resolve_temporal_observation(args.get("observations") or [], as_of=args.get("as_of")).to_dict()


registry.register(
    name="temporal_self_resolve",
    toolset="memory_graph",
    schema=SCHEMA,
    handler=_resolve,
    emoji="clock",
    description=SCHEMA["description"],
)
