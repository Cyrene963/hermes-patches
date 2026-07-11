"""Cross-domain decision consistency tool."""

from agent.cross_domain_consistency import evaluate_cross_domain_consistency
from tools.registry import registry

SCHEMA = {
    "name": "cross_domain_consistency_assess",
    "description": "Check whether academic, project, and personal decisions consistently apply reversible testing, real evidence, bounded investment, explicit criteria, and feedback review.",
    "parameters": {
        "type": "object",
        "properties": {
            "domains": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}},
        },
        "required": ["domains"],
        "additionalProperties": False,
    },
}


def _assess(args, **_kwargs):
    return evaluate_cross_domain_consistency(args.get("domains") or {}).to_dict()

registry.register(name="cross_domain_consistency_assess", toolset="memory_graph", schema=SCHEMA, handler=_assess, emoji="balance", description=SCHEMA["description"])
