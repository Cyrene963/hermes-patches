from agent.confidence_calibration import calibrate_confidence


def test_direct_confirmed_consistent_current_evidence_answers():
    result = calibrate_confidence({
        "directness": 1, "consistency": 1, "recency": 1,
        "namespace_match": 1, "independent_sources": 2,
        "explicit_user_confirmation": True,
    })
    assert result.action == "answer"
    assert result.confidence >= 0.8


def test_cross_namespace_evidence_always_abstains():
    result = calibrate_confidence({"directness": 1, "consistency": 1, "recency": 1, "namespace_match": 0, "independent_sources": 3})
    assert result.action == "abstain"
    assert result.confidence == 0


def test_sensitive_unconfirmed_inference_abstains():
    result = calibrate_confidence({"directness": 0.8, "consistency": 1, "recency": 1, "namespace_match": 1, "independent_sources": 2, "sensitive_inference": True})
    assert result.action == "abstain"


def test_unresolved_conflict_abstains_even_with_strong_sources():
    result = calibrate_confidence({"directness": 1, "consistency": 1, "recency": 1, "namespace_match": 1, "independent_sources": 3, "unresolved_conflict": True})
    assert result.action == "abstain"


def test_moderate_indirect_evidence_is_qualified_not_overconfident():
    result = calibrate_confidence({"directness": 0.6, "consistency": 0.8, "recency": 0.6, "namespace_match": 1, "independent_sources": 2})
    assert result.action == "qualify"
    assert result.confidence < 0.8


def test_stale_single_indirect_source_abstains():
    result = calibrate_confidence({"directness": 0.3, "consistency": 0.5, "recency": 0.1, "namespace_match": 1, "independent_sources": 1})
    assert result.action == "abstain"


def test_no_source_abstains():
    assert calibrate_confidence({"namespace_match": 1}).action == "abstain"
