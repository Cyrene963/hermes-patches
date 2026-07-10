from agent.proactive_need import decide_proactive_need


AUTONOMY = [{"id": "autonomy.continue_until_verified"}]


def test_standing_obligation_with_pending_todo_acts():
    result = decide_proactive_need(
        "阶段检查已通过。",
        obligations=AUTONOMY,
        active_todos=[{"id": "next", "content": "run live verification", "status": "pending"}],
        evidence_uris=["core://neutral/correction-1", "core://neutral/correction-2"],
    )
    assert result.action == "act"
    assert result.next_step == "run live verification"


def test_explicit_authorization_acts_without_magic_continue_word():
    assert decide_proactive_need("这个问题你直接修复并验证。", evidence_uris=["core://neutral/task"]).action == "act"


def test_reported_failure_only_diagnoses_without_write_authorization():
    result = decide_proactive_need("线上同步好像没跑起来。")
    assert result.action == "diagnose"
    assert "read-only" in result.reason


def test_read_only_boundary_never_mutates_even_with_standing_obligation():
    result = decide_proactive_need(
        "只做审计，不要修改任何文件。",
        obligations=AUTONOMY,
        active_todos=[{"id": "write", "status": "pending"}],
    )
    assert result.action == "diagnose"
    assert "without mutation" in result.next_step


def test_high_risk_side_effect_requires_scope_confirmation():
    assert decide_proactive_need("把这些结果发布并群发。", active_todos=[{"id": "send", "status": "pending"}]).action == "clarify"


def test_knowledge_question_is_answer_only():
    assert decide_proactive_need("什么是 PostgreSQL RLS？").action == "answer_only"


def test_emotional_reflection_does_not_trigger_external_action():
    assert decide_proactive_need("我和朋友吵架了，现在很生气。").action == "answer_only"


def test_verified_complete_without_obligation_stops():
    assert decide_proactive_need("好的", task_verified_complete=True).action == "stop"


def test_no_signal_defaults_to_answer_only():
    assert decide_proactive_need("我在想一个新的项目方向。自有想法").action == "answer_only"


def test_evidence_is_bounded_and_deduplicated():
    result = decide_proactive_need(
        "继续推进",
        obligations=AUTONOMY,
        evidence_uris=["core://neutral/a", "core://neutral/a"] + [f"core://neutral/{i}" for i in range(20)],
    )
    assert result.action == "act"
    assert len(result.evidence_uris) == 8
    assert len(set(result.evidence_uris)) == 8
