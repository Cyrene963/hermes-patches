from agent.cross_domain_consistency import evaluate_cross_domain_consistency


CORE = ["reversible_test", "real_evidence", "bounded_investment", "explicit_criteria", "review_and_adjust"]


def test_academic_project_personal_decisions_share_evidence_principles():
    result = evaluate_cross_domain_consistency({"academic": CORE, "project": CORE, "personal": CORE})
    assert result.status == "consistent"
    assert result.score == 1


def test_single_domain_is_unknown_not_false_consistency():
    assert evaluate_cross_domain_consistency({"project": CORE}).status == "unknown"


def test_any_explicit_contradiction_makes_result_inconsistent():
    result = evaluate_cross_domain_consistency({
        "academic": CORE,
        "project": ["real_evidence", "irreversible_commitment", "undefined_success"],
        "personal": CORE,
    })
    assert result.status == "inconsistent"
    assert len(result.contradictions) == 2


def test_partial_shared_principles_are_qualified():
    result = evaluate_cross_domain_consistency({
        "academic": ["real_evidence", "review_and_adjust"],
        "project": ["real_evidence", "explicit_criteria"],
        "personal": ["real_evidence", "bounded_investment"],
    })
    assert result.status == "qualify"


def test_domain_without_tags_is_not_counted_as_evidence():
    result = evaluate_cross_domain_consistency({"academic": CORE, "project": CORE, "personal": []})
    assert result.status == "consistent"
