import json

from agent.skill_router import (
    SkillManifest,
    build_autoload_skill_messages,
    build_semantic_rerank_payload,
    build_completion_gate_continue_message,
    completion_gate_should_continue,
    count_substantive_tool_turns,
    classify_task,
    load_skill_manifests,
    load_skill_routing_config,
    maybe_log_routing_failure,
    model_rerank_skill_candidates,
    persist_skill_route_plan,
    restore_latest_skill_route_plan,
    route_skills,
    SkillRoutingConfig,
    routing_failures_to_eval_cases,
    runtime_reroute_guidance_for_tool_result,
    skill_gate_for_tool,
)


AVAILABLE = {
    "deep-work",
    "hermes-agent",
    "memory-management",
    "hermes-memory-os",
    "universal-solutions-for-prs",
    "aegis-lite-completion-gate",
}


def test_long_horizon_hermes_fix_requires_deep_work_and_hermes_skills():
    decision = route_skills(
        "你花一晚上把 Hermes skill 选择失败彻底修好，不要问我是否继续。",
        AVAILABLE,
    )

    assert decision.classification.execution_depth == "deep_work"
    assert decision.classification.autonomy_level == "fully_autonomous_until_done"
    assert decision.classification.continuation_policy == "continue_until_verified"
    assert "deep-work" in decision.mandatory_skills
    assert "hermes-agent" in decision.mandatory_skills
    assert "deep-work" in decision.selected_skills
    assert "hermes-agent" in decision.selected_skills
    assert decision.gate_status["clarification_gate"] == "enabled"
    assert decision.gate_status["completion_gate"] == "enabled"


def test_day_long_research_and_patch_requires_deep_work():
    decision = route_skills(
        "用一天时间 deep work，调研市面类似方案，写出架构改造方案和代码 patch，不完美不准停。",
        AVAILABLE,
    )

    assert decision.classification.deep_work_required is True
    assert decision.classification.research_required is True
    assert decision.classification.duration_expectation == "long_horizon"
    assert "deep-work" in decision.mandatory_skills
    assert "long_horizon" in decision.bundle_expansion


def test_sleep_and_merge_prompt_is_long_horizon_autonomous():
    cls = classify_task("我睡觉了，你自己推进到能 merge。")

    assert cls.deep_work_required is True
    assert cls.autonomy_level == "fully_autonomous_until_done"
    assert cls.continuation_policy == "continue_until_verified"
    assert cls.test_required is True
    assert cls.verification_required is True


def test_simple_explainer_does_not_trigger_deep_work():
    decision = route_skills("简单解释一下 Hermes skills 是什么。", AVAILABLE)

    assert decision.classification.execution_depth == "quick_answer"
    assert "deep-work" not in decision.mandatory_skills
    assert "hermes-agent" in decision.mandatory_skills


def test_user_reported_missing_skill_becomes_eval_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    decision = route_skills("你刚才应该加载 deep-work skill，为什么又没用 skill？", AVAILABLE)
    maybe_log_routing_failure(decision, user_message="你刚才应该加载 deep-work skill", session_id="s1")

    assert decision.classification.routing_failure_report is True
    assert "routing_failure_report" in decision.classification.evidence
    failure_log = tmp_path / "logs" / "skill_routing" / "routing_failures.jsonl"
    assert failure_log.exists()
    record = json.loads(failure_log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["eval_candidate"] is True
    assert record["converted_to_eval_case"] is False
    assert "user_message" not in record


def test_missing_mandatory_skill_is_reported():
    decision = route_skills("你花一晚上彻底修复 Hermes Agent skills，不准停。", {"hermes-agent"})

    assert "deep-work" in decision.mandatory_skills
    assert "deep-work" in decision.missing_skills
    assert decision.gate_status["pre_execution_gate"] == "missing_mandatory"


def test_manifest_required_when_and_dependencies_are_used():
    manifests = {
        "long-runner": SkillManifest(
            name="long-runner",
            required_when=["autonomy_level == fully_autonomous_until_done"],
            dependencies=["verify-skill"],
            load_policy="optional",
        )
    }
    decision = route_skills("拿一整天彻底修，不要问我，自己决定。", {"long-runner", "verify-skill", "deep-work"}, manifests=manifests)

    assert "long-runner" in decision.mandatory_skills
    assert "verify-skill" in decision.selected_skills
    assert decision.dependency_expansion["long-runner"] == ["verify-skill"]


def test_load_skill_manifests_reads_machine_metadata(tmp_path):
    skill_dir = tmp_path / "skills" / "deep-work"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: deep-work\n"
        "description: Long horizon execution\n"
        "metadata:\n"
        "  hermes:\n"
        "    triggers: [deep work]\n"
        "    required_when:\n"
        "      - user_requested_deep_work == true\n"
        "    dependencies: [aegis-lite-completion-gate]\n"
        "    load_policy: mandatory_if_triggered\n"
        "---\n\nBody\n",
        encoding="utf-8",
    )
    manifests = load_skill_manifests({"/deep-work": {"name": "deep-work", "skill_dir": str(skill_dir)}})

    manifest = manifests["deep-work"]
    assert manifest.triggers == ["deep work"]
    assert "user_requested_deep_work == true" in manifest.required_when
    assert manifest.dependencies == ["aegis-lite-completion-gate"]
    assert manifest.load_policy == "mandatory_if_triggered"


def test_autoload_builds_skill_messages_without_model_decision(monkeypatch):
    fake_commands = {
        "/deep-work": {"name": "deep-work", "skill_dir": "/tmp/deep-work"},
        "/hermes-agent": {"name": "hermes-agent", "skill_dir": "/tmp/hermes-agent"},
    }

    import agent.skill_router as sr

    monkeypatch.setattr(sr, "_skill_command_map", lambda: fake_commands)
    monkeypatch.setattr(sr, "load_skill_manifests", lambda commands=None: {})

    def fake_build(cmd_key, user_instruction="", task_id=None, runtime_note=""):
        return f"LOADED {cmd_key} :: {runtime_note}"

    import agent.skill_commands as sc

    monkeypatch.setattr(sc, "build_skill_invocation_message", fake_build)

    messages, decision = build_autoload_skill_messages(
        "你花一晚上彻底修复 Hermes skill discovery，不要问我要不要继续。",
        task_id="t1",
    )

    assert "deep-work" in decision.mandatory_skills
    assert "hermes-agent" in decision.mandatory_skills
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert "LOADED" in messages[0]["content"]
    assert "Automatically loaded by Hermes Skill Router" in messages[0]["content"]
    assert "Completion Gate" in messages[-1]["content"]
    assert "deep-work" in decision.loaded_skills
    assert "hermes-agent" in decision.loaded_skills


def test_completion_gate_blocks_plan_only_long_horizon_final():
    decision = route_skills("我睡觉了，你自己推进到能 merge。", AVAILABLE)
    should_continue, reason = completion_gate_should_continue(
        "计划如下：我会先检查代码，然后运行测试。如果你愿意我可以继续。",
        decision,
        messages=[],
    )

    assert should_continue is True
    assert reason == "long_horizon_no_substantive_tools"
    msg = build_completion_gate_continue_message(reason, decision)
    assert msg["role"] == "user"
    assert "Do not ask whether to continue" in msg["content"]


def test_completion_gate_allows_after_substantive_tool_evidence():
    decision = route_skills("我睡觉了，你自己推进到能 merge。", AVAILABLE)
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "terminal", "arguments": "{}"}, "id": "1"}
            ],
        },
        {"role": "tool", "tool_call_id": "1", "content": "pytest passed"},
    ]
    assert count_substantive_tool_turns(messages) == 1
    should_continue, reason = completion_gate_should_continue(
        "已修复并运行 pytest，通过。",
        decision,
        messages=messages,
    )

    assert should_continue is False
    assert reason == "pass"


def test_tool_gate_blocks_missing_mandatory_loaded_skill():
    decision = route_skills("你花一晚上彻底修复 Hermes Agent skills，不准停。", AVAILABLE)
    decision.loaded_skills = ["deep-work"]

    allowed, reason = skill_gate_for_tool("terminal", decision)

    assert allowed is False
    assert "mandatory_skills_not_loaded" in reason


def test_runtime_reroute_guidance_is_added_for_failed_long_horizon_tool():
    decision = route_skills("你花一晚上把 failing tests 修到能 merge，不准停。", AVAILABLE)
    decision.loaded_skills = list(decision.mandatory_skills)

    hint = runtime_reroute_guidance_for_tool_result(
        "terminal",
        "pytest failed",
        decision,
        failed=True,
    )

    assert "Runtime Re-Route" in hint
    assert "repair the root cause" in hint
    assert "do not final" in hint


def test_model_rerank_hook_accepts_structured_classifier_output():
    manifests = {
        "deep-work": SkillManifest(name="deep-work", description="Long horizon work"),
        "hermes-agent": SkillManifest(name="hermes-agent", description="Hermes maintenance"),
    }

    def classifier(prompt):
        data = json.loads(prompt)
        assert data["task"] == "semantic_skill_rerank"
        return json.dumps({
            "selected_skills": ["deep-work", "hermes-agent"],
            "mandatory_skills": ["deep-work"],
            "rejected_skills": {},
            "confidence": 0.91,
        })

    result = model_rerank_skill_candidates(
        "please work overnight until verified",
        ["deep-work", "hermes-agent"],
        manifests,
        classifier=classifier,
    )

    assert result["fallback_used"] is False
    assert result["mandatory_skills"] == ["deep-work"]
    assert result["confidence"] == 0.91


def test_model_rerank_fails_closed_to_existing_candidates():
    result = model_rerank_skill_candidates(
        "please work overnight until verified",
        ["deep-work", "hermes-agent"],
        classifier=lambda _prompt: (_ for _ in ()).throw(RuntimeError("model down")),
    )

    assert result["fallback_used"] is True
    assert result["selected_skills"] == ["deep-work", "hermes-agent"]
    assert result["mandatory_skills"] == []


def test_routing_failures_can_be_converted_to_eval_cases(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    decision = route_skills("你刚才应该加载 deep-work skill，为什么又没用 skill？", AVAILABLE)
    maybe_log_routing_failure(decision, user_message="你刚才应该加载 deep-work skill", session_id="s1")

    out = routing_failures_to_eval_cases()
    assert out.exists()
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    case = json.loads(lines[-1])
    rendered = json.dumps(case, ensure_ascii=False)
    assert "你刚才" not in rendered
    assert "deep-work skill" not in rendered
    assert "user_message_sha256_16" in rendered
    assert "expected_skills_selected_or_loaded" in case["assertions"]


def test_semantic_rerank_payload_is_privacy_safe_by_default():
    raw = "请修复 /home/user/private/project 里面的 TOKEN_REDACTED token，联系 EMAIL_REDACTED，chat REDACTED_LONG_ID"
    payload = build_semantic_rerank_payload(
        raw,
        ["deep-work", "hermes-agent"],
        {"deep-work": SkillManifest(name="deep-work", description="Long horizon")},
        privacy_mode="sanitized",
    )
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "user_message" not in payload
    assert raw not in rendered
    assert "/home/user/private/project" not in rendered
    assert "TOKEN_REDACTED" not in rendered
    assert "EMAIL_REDACTED" not in rendered
    assert "REDACTED_LONG_ID" not in rendered
    assert "message_sha256_16" in payload


def test_route_skills_semantic_reranker_preserves_deterministic_mandatory():
    def classifier(prompt):
        data = json.loads(prompt)
        assert "user_message" not in data
        return json.dumps({
            "selected_skills": ["hermes-agent"],
            "mandatory_skills": ["hermes-agent"],
            "rejected_skills": {},
            "confidence": 0.9,
        })

    decision = route_skills(
        "你花一晚上彻底修复 Hermes skills，不准停。",
        AVAILABLE,
        routing_config=SkillRoutingConfig(semantic_reranker_enabled=True, semantic_min_confidence=0.65),
        classifier=classifier,
    )
    assert decision.source == "deterministic+semantic_reranker"
    assert "deep-work" in decision.mandatory_skills
    assert "hermes-agent" in decision.mandatory_skills
    assert "deep-work" in decision.selected_skills


def test_durable_route_plan_persistence_excludes_raw_user_text(tmp_path):
    from hermes_state import SessionDB

    db = SessionDB(tmp_path / "state.db")
    db.create_session("s1", "cli")
    user_text = "你花一晚上修复 skill router，不准停。"
    decision = route_skills(user_text, AVAILABLE)
    plan_id = persist_skill_route_plan(db, decision, session_id="s1", task_id="t1")
    assert plan_id

    row = db.get_latest_skill_route_plan("s1", task_id="t1")
    rendered = json.dumps(row, ensure_ascii=False)
    assert user_text not in rendered
    assert "user_message_sha256_16" in rendered
    restored = restore_latest_skill_route_plan(db, session_id="s1", task_id="t1")
    assert restored is not None
    assert restored.classification.deep_work_required is True
    assert "deep-work" in restored.mandatory_skills


def test_skill_routing_config_defaults_to_privacy_safe_live_reranker():
    cfg = load_skill_routing_config({})
    assert cfg.durable_state is True
    assert cfg.semantic_reranker_enabled is True
    assert cfg.semantic_allow_network is True
    assert cfg.semantic_privacy_mode == "sanitized"
