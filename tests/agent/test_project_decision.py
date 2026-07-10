from agent.project_decision import decide_project_proposal


def test_frequent_solo_dogfood_system_project_is_accepted():
    result = decide_project_proposal({
        "pain_frequency": 1,
        "solo_start": 1,
        "dogfood": 1,
        "external_system_data": 1,
        "distribution": 0.8,
        "implementation_scope": 0.4,
        "measurable_experiment": True,
    })
    assert result.decision == "accept"


def test_direct_ai_wrapper_without_system_value_is_rejected():
    result = decide_project_proposal({
        "pain_frequency": 0.2,
        "solo_start": 0.8,
        "ai_wrapper_only": 1,
        "external_system_data": 0,
        "distribution": 0.1,
    })
    assert result.decision == "reject"
    assert any("direct AI chat" in reason for reason in result.reasons)


def test_institution_and_cold_start_dependency_is_rejected():
    result = decide_project_proposal({
        "pain_frequency": 0.5,
        "cold_start_dependency": 1,
        "institution_dependency": 1,
        "implementation_scope": 0.6,
    })
    assert result.decision == "reject"


def test_core_product_placeholder_blocks_pilot():
    result = decide_project_proposal({
        "pain_frequency": 0.8,
        "solo_start": 0.9,
        "dogfood": 0.8,
        "external_system_data": 0.4,
        "distribution": 0.5,
        "core_asset_placeholder": 1,
        "implementation_scope": 0.5,
        "measurable_experiment": True,
    })
    assert result.decision == "reject"
    assert any("placeholder" in reason for reason in result.reasons)


def test_large_unvalidated_project_requires_experiment():
    result = decide_project_proposal({
        "pain_frequency": 1,
        "solo_start": 0.6,
        "dogfood": 0.8,
        "external_system_data": 1,
        "distribution": 0.5,
        "implementation_scope": 1,
        "measurable_experiment": False,
    })
    assert result.decision == "experiment"
    assert "continue/stop thresholds" in result.required_next_step


def test_mid_score_proposal_gets_pilot_not_false_acceptance():
    result = decide_project_proposal({
        "pain_frequency": 0.7,
        "solo_start": 0.8,
        "dogfood": 0.4,
        "external_system_data": 0.4,
        "distribution": 0.2,
        "implementation_scope": 0.5,
        "measurable_experiment": True,
    })
    assert result.decision == "pilot"


def test_custom_weights_are_supported_without_private_hardcoding():
    base = {"pain_frequency": 1, "external_system_data": 1, "implementation_scope": 0.2}
    default = decide_project_proposal(base)
    custom = decide_project_proposal(base, weights={"pain_frequency": 0, "external_system_data": 0})
    assert default.score > custom.score
