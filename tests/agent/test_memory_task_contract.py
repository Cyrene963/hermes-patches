from agent.memory_task_contract import (
    EvidenceItem,
    build_contract_recall_queries,
    build_task_memory_contract,
    evaluate_contract,
    plan_contract_repair,
    resolve_relationships,
    resolve_projects,
)


def _evidence(*rows):
    return [EvidenceItem(uri=uri, text=text) for uri, text in rows]


def test_unique_classmate_resolves_with_relationship_evidence():
    evidence = _evidence(
        ("core://用户档案/关系/alex", "Alex 是用户的 E 班同学，也是当前游戏项目搭档。"),
        ("core://项目/game", "用户计划与同学一起做游戏项目。"),
    )
    [binding] = resolve_relationships("我和我同学去做游戏项目，怎么分工？", evidence)
    assert binding.status == "resolved"
    assert binding.entity == "Alex"
    assert binding.evidence_uris == ["core://用户档案/关系/alex"]


def test_multiple_classmates_are_ambiguous_not_silently_bound():
    evidence = _evidence(
        ("core://用户档案/关系/alex", "Alex 是用户的同学。"),
        ("core://用户档案/关系/blair", "Blair 是用户的同学。"),
    )
    [binding] = resolve_relationships("我同学说要做项目", evidence)
    assert binding.status == "ambiguous"
    assert {item.name for item in binding.candidates} == {"Alex", "Blair"}


def test_explicit_name_wins_over_other_relation_candidates():
    evidence = _evidence(
        ("core://用户档案/关系/alex", "Alex 是用户的同学。"),
        ("core://用户档案/关系/blair", "Blair 是用户的同学。"),
    )
    [binding] = resolve_relationships("我同学 Alex 想做游戏", evidence)
    assert binding.status == "resolved"
    assert binding.entity == "Alex"


def test_unknown_relation_abstains():
    [binding] = resolve_relationships("我同学想做游戏", [])
    assert binding.status == "unresolved"
    assert binding.entity is None


def test_unique_active_project_resolves_with_evidence():
    evidence = _evidence(
        ("core://projects/atlas", "Project Atlas is the user's current active project."),
        ("core://projects/beacon", "Project Beacon was completed and archived."),
    )
    [binding] = resolve_projects("Continue that project", evidence)
    assert binding.status == "resolved"
    assert binding.entity == "Atlas"
    assert binding.evidence_uris == ["core://projects/atlas"]


def test_two_active_projects_are_ambiguous():
    evidence = _evidence(
        ("core://projects/atlas", "Project Atlas is active."),
        ("core://projects/beacon", "Project Beacon is active."),
    )
    [binding] = resolve_projects("继续那个项目", evidence)
    assert binding.status == "ambiguous"
    assert {item.name for item in binding.candidates} == {"Atlas", "Beacon"}


def test_project_reference_abstains_without_explicit_project_grammar():
    [binding] = resolve_projects(
        "Continue that project",
        _evidence(("core://notes/atlas", "Atlas is a useful product mentioned in passing.")),
    )
    assert binding.status == "unresolved"


def test_project_binding_is_carried_in_contract_prompt():
    contract = build_task_memory_contract(
        "继续那个项目",
        _evidence(("core://projects/atlas", "项目 Atlas 是当前活跃项目。")),
        namespace="tenant:a",
    )
    assert contract.bindings[0].relation == "project"
    assert "Resolved `那个项目` -> `Atlas`" in contract.to_prompt()


def test_research_preference_compiles_to_obligation():
    contract = build_task_memory_contract(
        "调研这个网站和博主",
        _evidence(("core://用户档案/preferences/research", "用户偏好多信息源交叉验证，追求信息深度和广度。")),
        namespace="tenant:a",
    )
    assert [item.id for item in contract.obligations] == ["research.multi_source"]
    assert "multiple independent sources" in contract.to_prompt()


def test_repair_plan_is_specific_and_bounded():
    verdict = {
        "passed": False,
        "obligations": [{"id": "coding.verify", "passed": False, "missing": ["passing test/runtime evidence"]}],
    }
    first = plan_contract_repair(verdict)
    second = plan_contract_repair(verdict, prior_fingerprints=[first["fingerprint"]])
    third = plan_contract_repair(verdict, prior_fingerprints=[first["fingerprint"], first["fingerprint"]])
    assert first["action"] == "repair" and first["attempt"] == 1
    assert "Run the narrowest relevant test" in first["actions"][0]
    assert second["action"] == "repair" and second["attempt"] == 2
    assert third["action"] == "block"
    assert "do not repeat" in third["message"].lower()


def test_repair_plan_maps_delivery_and_research_actions():
    verdict = {
        "passed": False,
        "obligations": [
            {"id": "delivery.real_attachment", "passed": False, "missing": ["platform delivery confirmation"]},
            {"id": "research.multi_source", "passed": False, "missing": ["multi-source/cross-check evidence"]},
        ],
    }
    plan = plan_contract_repair(verdict)
    text = "\n".join(plan["actions"])
    assert "real platform attachment" in text
    assert "two independent sources" in text


def test_coding_verification_obligation_fails_without_runtime_evidence():
    contract = build_task_memory_contract(
        "修复这个 bug",
        _evidence(("core://用户档案/preferences/verification", "用户要求先验证，必须有真实运行和 live path 证据。")),
    )
    verdict = evaluate_contract(contract, [{"tool_name": "patch", "result": {"success": True}}])
    assert verdict["passed"] is False
    assert "passing test/runtime evidence" in verdict["obligations"][0]["missing"]


def test_coding_verification_obligation_passes_with_terminal_result():
    contract = build_task_memory_contract(
        "修复这个 bug",
        _evidence(("core://用户档案/preferences/verification", "用户要求先验证，必须有真实运行测试证据。")),
    )
    verdict = evaluate_contract(contract, [{"tool_name": "terminal", "result": {"exit_code": 0, "output": "12 passed"}}])
    assert verdict["passed"] is True


def test_delivery_requires_platform_confirmation():
    contract = build_task_memory_contract(
        "把这个文件发我",
        _evidence(("core://用户档案/preferences/delivery", "Telegram 文件必须真实发送为附件并检查 message_id。")),
    )
    failed = evaluate_contract(contract, [{"tool_name": "terminal", "result": {"exit_code": 0, "output": "/tmp/a.pdf"}}])
    passed = evaluate_contract(contract, [{"tool_name": "terminal", "result": {"exit_code": 0, "output": '{"ok": true, "message_id": 42}'}}])
    assert failed["passed"] is False
    assert passed["passed"] is True


def test_contract_does_not_import_unprovided_cross_namespace_evidence():
    evidence = _evidence(("tenant-b://用户档案/private", "Blair 是用户的同学。"))
    contract = build_task_memory_contract("我同学是谁", [], namespace="tenant:a")
    assert contract.evidence_uris == []
    assert all("tenant-b" not in uri for uri in contract.evidence_uris)
    assert evidence  # caller owns namespace filtering; compiler never fetches globally


def test_repeated_autonomy_correction_promotes_durable_obligation():
    contract = build_task_memory_contract(
        "继续推进并完成这个任务",
        _evidence(
            ("core://correction/one", "用户要求不要问是否继续，自己持续推进直到完成。"),
            ("core://correction/two", "用户再次纠正：不要等回复再进行下一阶段。"),
        ),
    )
    assert "autonomy.continue_until_verified" in [item.id for item in contract.obligations]

    pending = evaluate_contract(
        contract,
        [],
        active_todos=[{"id": "next", "content": "next stage", "status": "pending"}],
    )
    done = evaluate_contract(
        contract,
        [{"tool_name": "terminal", "result": {"exit_code": 0, "output": "verified"}}],
        active_todos=[],
    )
    assert pending["passed"] is False
    assert any("active todos: next" in value for value in pending["obligations"][0]["missing"])
    assert done["passed"] is True


def test_unfinished_next_step_generates_autonomy_recall_queries():
    queries = build_contract_recall_queries("阶段检查通过，但还有下一步。")
    assert "user autonomy preference continue until verified do not ask" in queries


def test_single_authoritative_autonomy_rule_becomes_hard_obligation():
    contract = build_task_memory_contract(
        "阶段检查完成但还有下一步",
        _evidence((
            "core://neutral/authoritative-rule",
            "Authorized multi-step work should continue through remaining stages without pausing until verified.",
        )),
    )
    obligation = next(item for item in contract.obligations if item.id == "autonomy.continue_until_verified")
    assert obligation.evidence_uris == ["core://neutral/authoritative-rule"]


def test_single_autonomy_sentence_does_not_become_hard_obligation():
    contract = build_task_memory_contract(
        "继续推进",
        _evidence(("core://note", "这一次不要问是否继续。")),
    )
    assert "autonomy.continue_until_verified" not in [item.id for item in contract.obligations]


def test_cjk_entity_extractor_does_not_emit_sliding_window_noise():
    from agent.memory_metacognition import _extract_entities

    entities = _extract_entities("我和我同学去做游戏项目")
    assert not {"我和", "和我", "我同", "学去"}.intersection(entities)
