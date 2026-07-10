"""Privacy-safe correction ledger and executable regression artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_SCHEMA_VERSION = 1
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_|xox[baprs]-|AKIA[0-9A-Z]{16}|"
    r"token\s*[:=]|api[_ -]?key\s*[:=]|password\s*[:=])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CorrectionRegressionCase:
    schema_version: int
    case_id: str
    changeset_id: str
    created_at: str
    namespace_hash: str
    evidence_sha256: str
    behavior_class: str
    expected_memory_kind: str
    expected_target_store: str
    expected_requires_review: bool
    reject_gate: str
    future_queries: list[str]
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _digest(value: str, length: int | None = None) -> str:
    result = hashlib.sha256((value or "").encode("utf-8", "ignore")).hexdigest()
    return result[:length] if length else result


def _behavior_class(text: str, reject_gate: str) -> str:
    hay = f"{text}\n{reject_gate}".lower()
    patterns = (
        ("continuation", r"继续|中途停|等.*回复|ask.*continue|continue until"),
        ("verification", r"验证|验收|test|verify|readback"),
        ("memory_recall", r"记不住|召回|回忆|memory|外置大脑|数字替身"),
        ("privacy", r"隐私|隔离|namespace|leak|shared"),
        ("overengineering", r"有必要吗|过度|简化|over.?engineer|simplif"),
        ("tool_route", r"工具|凭据|token|login|provider|route"),
        ("factual_correction", r"不是.{0,30}是|错了|不对|correct"),
    )
    for name, pattern in patterns:
        if re.search(pattern, hay, re.IGNORECASE):
            return name
    return "workflow_correction"


def _safe_gate(value: str) -> str:
    gate = re.sub(r"\s+", " ", value or "").strip()[:500]
    if _SECRET_RE.search(gate):
        return "Apply the evidence-backed correction gate without exposing sensitive values."
    return gate


def build_correction_case(
    *,
    evidence_text: str,
    namespace: str,
    memory_kind: str,
    target_store: str,
    requires_review: bool,
    reject_gate: str,
    future_queries: Iterable[str],
) -> CorrectionRegressionCase:
    evidence_hash = _digest(evidence_text)
    namespace_hash = _digest(namespace or "private", 16)
    behavior = _behavior_class(evidence_text, reject_gate)
    stable = f"{namespace_hash}|{evidence_hash}|{behavior}|{memory_kind}"
    case_id = "corr_" + _digest(stable, 20)
    changeset_id = "chg_" + _digest("correction|" + stable, 20)
    safe_queries = []
    normalized_evidence = re.sub(r"\s+", " ", evidence_text or "").strip().lower()
    for query in future_queries:
        query = re.sub(r"\s+", " ", str(query or "")).strip()
        if not query or _SECRET_RE.search(query):
            continue
        lower_query = query.lower()
        # Classifiers often include a raw evidence excerpt as one readback query.
        # Store only generic intents; high-overlap queries are represented by the
        # evidence hash already present in the case.
        overlap = (
            lower_query in normalized_evidence
            or normalized_evidence in lower_query
            or any(
                len(fragment) >= 12 and fragment in normalized_evidence
                for fragment in re.findall(r"[\w\u4e00-\u9fff]{12,}", lower_query)
            )
        )
        if overlap:
            continue
        if query not in safe_queries:
            safe_queries.append(query[:180])
    return CorrectionRegressionCase(
        schema_version=_SCHEMA_VERSION,
        case_id=case_id,
        changeset_id=changeset_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        namespace_hash=namespace_hash,
        evidence_sha256=evidence_hash,
        behavior_class=behavior,
        expected_memory_kind=memory_kind,
        expected_target_store=target_store,
        expected_requires_review=bool(requires_review),
        reject_gate=_safe_gate(reject_gate),
        future_queries=safe_queries[:5],
    )


def record_correction_case(
    case: CorrectionRegressionCase,
    *,
    ledger_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    path = Path(ledger_path or "~/.hermes/logs/memory_correction_regressions.jsonl").expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("case_id"):
                existing_ids.add(str(row["case_id"]))
    if case.case_id in existing_ids:
        return {"recorded": False, "duplicate": True, **case.to_dict(), "ledger_path": str(path)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(case.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return {"recorded": True, "duplicate": False, **case.to_dict(), "ledger_path": str(path)}


def evaluate_correction_case(case: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    failures = []
    for expected_key, actual_key in (
        ("expected_memory_kind", "memory_kind"),
        ("expected_target_store", "target_store"),
        ("expected_requires_review", "requires_review"),
    ):
        if classification.get(actual_key) != case.get(expected_key):
            failures.append(
                f"{actual_key}: expected {case.get(expected_key)!r}, got {classification.get(actual_key)!r}"
            )
    expected_gate = str(case.get("reject_gate") or "").strip()
    actual_gate = str(classification.get("reject_gate") or "").strip()
    if expected_gate and not actual_gate:
        failures.append("reject_gate missing")
    return {
        "case_id": case.get("case_id", ""),
        "passed": not failures,
        "failures": failures,
    }


__all__ = [
    "CorrectionRegressionCase",
    "build_correction_case",
    "record_correction_case",
    "evaluate_correction_case",
]
