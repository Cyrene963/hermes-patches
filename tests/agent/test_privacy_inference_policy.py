from agent.privacy_inference_policy import decide_sensitive_inference


def test_indirect_mental_health_inference_is_refused():
    result = decide_sensitive_inference({"category": "mental_health", "namespace_match": True, "source_role": "user"})
    assert result.action == "refuse"


def test_external_model_analysis_is_not_promoted_to_user_fact():
    result = decide_sensitive_inference({"category": "politics", "namespace_match": True, "source_role": "external_model"})
    assert result.action == "refuse"
    assert "not a user fact" in result.reason


def test_cross_user_private_fact_is_refused():
    result = decide_sensitive_inference({"category": "cross_user_fact", "namespace_match": False, "explicit_user_statement": True})
    assert result.action == "refuse"


def test_credentials_are_never_guessed_or_exposed():
    result = decide_sensitive_inference({"category": "credentials", "namespace_match": True, "explicit_user_statement": True, "confirmed_current_namespace_evidence": True, "user_requested_use": True})
    assert result.action == "refuse"


def test_explicit_confirmed_requested_sensitive_fact_is_bounded():
    result = decide_sensitive_inference({
        "category": "finances", "namespace_match": True, "source_role": "user",
        "explicit_user_statement": True, "confirmed_current_namespace_evidence": True,
        "user_requested_use": True,
    })
    assert result.action == "allow_bounded"
    assert "do not expand" in result.safe_response


def test_confirmed_non_sensitive_fact_is_allowed():
    result = decide_sensitive_inference({"category": "writing_preference", "namespace_match": True, "confirmed_current_namespace_evidence": True})
    assert result.action == "allow"


def test_unconfirmed_non_sensitive_claim_abstains():
    assert decide_sensitive_inference({"category": "hobby", "namespace_match": True}).action == "abstain"


def test_raw_secret_exposure_is_refused_regardless_of_category():
    assert decide_sensitive_inference({"category": "configuration", "namespace_match": True, "would_expose_raw_secret": True}).action == "refuse"
