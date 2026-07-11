"""Strict completion evidence evaluator for real task artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CompletionVerdict:
    complete: bool
    confidence: float
    passed: tuple[str, ...]
    missing: tuple[str, ...]
    failed: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_completion_evidence(
    requirements: Iterable[Mapping[str, Any]],
    evidence: Mapping[str, Any],
) -> CompletionVerdict:
    """Require every declared acceptance condition to have matching evidence."""
    passed: list[str] = []
    missing: list[str] = []
    failed: list[str] = []
    artifacts = {str(item.get("path")): item for item in evidence.get("artifacts", []) if item.get("path")}
    commands = {str(item.get("id")): item for item in evidence.get("commands", []) if item.get("id")}
    apis = {str(item.get("id")): item for item in evidence.get("apis", []) if item.get("id")}
    todos = list(evidence.get("todos", []))

    for req in requirements:
        rid = str(req.get("id") or "unnamed")
        kind = str(req.get("kind") or "")
        if kind == "artifact":
            item = artifacts.get(str(req.get("path") or ""))
            if item is None:
                missing.append(rid); continue
            if not item.get("exists", False):
                failed.append(rid); continue
            expected_hash = str(req.get("sha256") or "")
            if expected_hash and str(item.get("sha256") or "") != expected_hash:
                failed.append(rid); continue
            passed.append(rid)
        elif kind == "command":
            item = commands.get(str(req.get("command_id") or rid))
            if item is None:
                missing.append(rid); continue
            if int(item.get("exit_code", 1)) != 0:
                failed.append(rid); continue
            marker = str(req.get("output_contains") or "")
            if marker and marker not in str(item.get("output") or ""):
                failed.append(rid); continue
            passed.append(rid)
        elif kind == "api":
            item = apis.get(str(req.get("api_id") or rid))
            if item is None:
                missing.append(rid); continue
            if int(item.get("status", 0)) != int(req.get("status", 200)):
                failed.append(rid); continue
            marker = str(req.get("body_contains") or "")
            if marker and marker not in str(item.get("body") or ""):
                failed.append(rid); continue
            passed.append(rid)
        elif kind == "no_active_todos":
            active = [item for item in todos if str(item.get("status") or "").lower() in {"pending", "in_progress"}]
            (failed if active else passed).append(rid)
        else:
            failed.append(rid)

    total = len(passed) + len(missing) + len(failed)
    complete = total > 0 and not missing and not failed
    confidence = 1.0 if complete else (round(len(passed) / total, 3) if total else 0.0)
    return CompletionVerdict(complete, confidence, tuple(passed), tuple(missing), tuple(failed))


__all__ = ["CompletionVerdict", "evaluate_completion_evidence"]
