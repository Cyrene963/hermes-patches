from agent.relationship_boundary import decide_relationship_boundary


def test_consistent_reciprocal_reliable_boundary_respecting_relationship_can_be_core():
    result = decide_relationship_boundary({
        "reciprocity": 1,
        "self_reflection": 0.8,
        "repair_after_conflict": 0.8,
        "reliability": 0.9,
        "boundary_respect": 1,
        "independent_observations": 8,
    })
    assert result.tier == "core"


def test_low_reciprocity_attack_and_stonewalling_requires_distance():
    result = decide_relationship_boundary({
        "reciprocity": 0.1,
        "self_reflection": 0.1,
        "repair_after_conflict": 0,
        "reliability": 0.3,
        "boundary_respect": 0.2,
        "personal_attack": 0.9,
        "stonewalling": 0.9,
        "independent_observations": 6,
    })
    assert result.tier == "distance"
    assert "no core dependence" in result.investment


def test_insufficient_observations_stay_observe_even_when_initial_signal_is_good():
    result = decide_relationship_boundary({
        "reciprocity": 1,
        "reliability": 1,
        "boundary_respect": 1,
        "independent_observations": 1,
    })
    assert result.tier == "observe"
    assert "reversible" in result.investment


def test_mixed_but_positive_relationship_stays_limited():
    result = decide_relationship_boundary({
        "reciprocity": 0.7,
        "self_reflection": 0.5,
        "repair_after_conflict": 0.5,
        "reliability": 0.7,
        "boundary_respect": 0.8,
        "stonewalling": 0.3,
        "independent_observations": 5,
    })
    assert result.tier == "limited"
    assert "domain-specific" in result.investment


def test_severe_boundary_violation_cannot_be_offset_by_other_positive_traits():
    result = decide_relationship_boundary({
        "reciprocity": 1,
        "self_reflection": 1,
        "repair_after_conflict": 1,
        "reliability": 1,
        "boundary_respect": 0.1,
        "boundary_violation": 1,
        "independent_observations": 10,
    })
    assert result.tier == "distance"


def test_unknown_traits_default_to_zero_not_invented_positive_evidence():
    result = decide_relationship_boundary({"independent_observations": 10})
    assert result.tier == "observe"
    assert result.trust_score == 0
