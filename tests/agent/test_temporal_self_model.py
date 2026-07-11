from agent.temporal_self_model import resolve_temporal_observation


OBSERVATIONS = [
    {"value": "alpha", "effective_at": "2025-01-01T00:00:00Z", "confidence": 0.8, "evidence_id": "neutral-a"},
    {"value": "beta", "effective_at": "2025-06-01T00:00:00Z", "confidence": 0.95, "explicit_correction": True, "evidence_id": "neutral-b"},
]


def test_historical_query_does_not_leak_future_correction():
    result = resolve_temporal_observation(OBSERVATIONS, as_of="2025-03-01T00:00:00Z")
    assert result.status == "resolved"
    assert result.value == "alpha"


def test_current_query_uses_latest_correction():
    result = resolve_temporal_observation(OBSERVATIONS, as_of="2025-07-01T00:00:00Z")
    assert result.value == "beta"
    assert result.confidence == 0.95


def test_expired_observation_is_not_returned():
    result = resolve_temporal_observation([
        {"value": "temporary", "effective_at": "2025-01-01", "valid_to": "2025-02-01"},
    ], as_of="2025-03-01")
    assert result.status == "unknown"


def test_same_time_conflicting_values_fail_closed():
    result = resolve_temporal_observation([
        {"value": "left", "effective_at": "2025-01-01", "evidence_id": "a"},
        {"value": "right", "effective_at": "2025-01-01", "evidence_id": "b"},
    ], as_of="2025-02-01")
    assert result.status == "ambiguous"
    assert result.value is None


def test_malformed_or_future_only_observations_return_unknown():
    result = resolve_temporal_observation([
        {"value": "bad", "effective_at": "not-a-date"},
        {"value": "future", "effective_at": "2030-01-01"},
    ], as_of="2025-01-01")
    assert result.status == "unknown"


def test_non_correction_confidence_decays_but_not_below_floor():
    result = resolve_temporal_observation([
        {"value": "stable", "effective_at": "2020-01-01", "confidence": 0.8},
    ], as_of="2030-01-01")
    assert result.status == "resolved"
    assert result.confidence == 0.44
