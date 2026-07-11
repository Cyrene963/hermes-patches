"""Time-conditioned self-model resolution over versioned observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class TemporalResolution:
    status: str
    value: Any = None
    confidence: float = 0.0
    effective_at: str = ""
    evidence_ids: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_temporal_observation(
    observations: Iterable[Mapping[str, Any]],
    *,
    as_of: str | datetime,
) -> TemporalResolution:
    """Resolve the latest unexpired fact at a requested historical instant."""
    target = _parse(as_of)
    eligible: list[tuple[datetime, Mapping[str, Any]]] = []
    for item in observations:
        try:
            effective = _parse(item.get("effective_at") or item.get("observed_at"))
        except Exception:
            continue
        if effective > target:
            continue
        valid_to = item.get("valid_to")
        if valid_to:
            try:
                if _parse(valid_to) <= target:
                    continue
            except Exception:
                continue
        eligible.append((effective, item))
    if not eligible:
        return TemporalResolution("unknown", reason="no observation is valid at the requested time")

    newest = max(effective for effective, _ in eligible)
    latest = [item for effective, item in eligible if effective == newest]
    values = {repr(item.get("value")): item.get("value") for item in latest}
    ids = tuple(dict.fromkeys(str(item.get("evidence_id") or "") for item in latest if item.get("evidence_id")))[:8]
    if len(values) > 1:
        return TemporalResolution(
            "ambiguous", confidence=0.0, effective_at=newest.isoformat(),
            evidence_ids=ids, reason="conflicting observations share the latest effective time",
        )

    chosen = latest[-1]
    age_days = max(0.0, (target - newest).total_seconds() / 86400.0)
    base = max(0.0, min(1.0, float(chosen.get("confidence", 0.8))))
    explicit = bool(chosen.get("explicit_correction", False))
    decay = 1.0 if explicit else max(0.55, 1.0 - age_days / 1460.0)
    return TemporalResolution(
        "resolved", value=chosen.get("value"), confidence=round(base * decay, 3),
        effective_at=newest.isoformat(), evidence_ids=ids,
        reason="latest observation valid at the requested time",
    )


__all__ = ["TemporalResolution", "resolve_temporal_observation"]
