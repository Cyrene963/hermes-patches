"""Sensitive inference and identity-boundary assessment tool."""

from agent.privacy_inference_policy import decide_sensitive_inference
from tools.registry import registry

SCHEMA = {
    "name": "privacy_inference_assess",
    "description": "Decide whether a personal claim may be used, must be bounded, should be abstained from, or must be refused under namespace, consent, source-role, and secret-exposure rules.",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "explicit_user_statement": {"type": "boolean"},
            "confirmed_current_namespace_evidence": {"type": "boolean"},
            "namespace_match": {"type": "boolean"},
            "source_role": {"type": "string"},
            "would_expose_raw_secret": {"type": "boolean"},
            "user_requested_use": {"type": "boolean"},
        },
        "required": ["category", "namespace_match"],
        "additionalProperties": False,
    },
}


def _assess(args, **_kwargs):
    return decide_sensitive_inference(args or {}).to_dict()

registry.register(name="privacy_inference_assess", toolset="memory_graph", schema=SCHEMA, handler=_assess, emoji="lock", description=SCHEMA["description"])
