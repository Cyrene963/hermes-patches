from agent.memory_task_contract import (
    EvidenceItem,
    build_task_memory_contract,
    evaluate_contract,
    resolve_relationships,
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


def test_research_preference_compiles_to_obligation():
    contract = build_task_memory_contract(
        "调研这个网站和博主",
        _evidence(("core://用户档案/preferences/research", "用户偏好多信息源交叉验证，追求信息深度和广度。")),
        namespace="tenant:a",
    )
    assert [item.id for item in contract.obligations] == ["research.multi_source"]
    assert "multiple independent sources" in contract.to_prompt()


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


def test_cjk_entity_extractor_does_not_emit_sliding_window_noise():
    from agent.memory_metacognition import _extract_entities

    entities = _extract_entities("我和我同学去做游戏项目")
    assert not {"我和", "和我", "我同", "学去"}.intersection(entities)
