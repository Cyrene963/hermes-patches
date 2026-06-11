"""Identity configuration loader for Memory Graph WebUI.

Keeps the public tree free of real names: identities load from a gitignored local
file, with neutral fixtures as the built-in default.

Resolution order:
  1. $MEMORY_GRAPH_IDENTITY_CONFIG
  2. ~/.hermes/memory_identity.local.yaml
  3. neutral built-in defaults (fixtures only)

Local/example schema:
    entities:      {Alice: [Alice, alice]}
    entity_paths:  {Alice: 用户档案/Alice}
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

_DEFAULT_ENTITIES: Dict[str, List[str]] = {
    "Hermes": ["Hermes", "hermes"],
    "Memory Graph": ["Memory Graph", "memory graph"],
    "Hindsight": ["Hindsight", "hindsight"],
}
_DEFAULT_ENTITY_PATHS: Dict[str, str] = {
    "Hermes": "项目/hermes-agent",
    "Memory Graph": "项目/memory-graph",
    "Hindsight": "系统架构/Hindsight运维",
}


def _candidate_paths() -> List[Path]:
    paths = []
    env = os.environ.get("MEMORY_GRAPH_IDENTITY_CONFIG", "").strip()
    if env:
        paths.append(Path(env))
    paths.append(Path.home() / ".hermes" / "memory_identity.local.yaml")
    return paths


@lru_cache(maxsize=1)
def load_identity_config() -> Dict[str, Any]:
    entities = dict(_DEFAULT_ENTITIES)
    entity_paths = dict(_DEFAULT_ENTITY_PATHS)
    for p in _candidate_paths():
        if not p.exists():
            continue
        try:
            import yaml
            data = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if isinstance(data.get("entities"), dict):
            entities.update({str(k): list(v) for k, v in data["entities"].items()})
        if isinstance(data.get("entity_paths"), dict):
            entity_paths.update({str(k): str(v) for k, v in data["entity_paths"].items()})
        break
    return {"entities": entities, "entity_paths": entity_paths}


def get_entities() -> Dict[str, List[str]]:
    return load_identity_config()["entities"]


def get_entity_paths() -> Dict[str, str]:
    return load_identity_config()["entity_paths"]
