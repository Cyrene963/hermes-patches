from agent.memory_write_pipeline import MemoryWritePipeline
from agent.memory_semantic_classifier import classify_memory_semantics

CASES = [
    ("novel", "低频心跳小说不要有 AI 味，要有普通生活细节的重量和漫画质感。", "creative_target_function"),
    ("correction", "错错错，你应该把用户纠错抽象成 reject gate 和防复发机制。", "agent_memory_workflow"),
    ("exam", "我下周 DSE 考试了，这是时间表和考试范围，帮我安排复习。", "exam_context"),
    ("claude", "用 Claude 审一下 diff；not logged in 时先查已有配置和凭据路径。", "tool_credential_route"),
    ("github", "我之前给过 GitHub token；要用 PAT 时先查记忆和 secret 路径。", "tool_credential_route"),
    ("continue", "继续", None),
    ("necessary", "有必要吗？这个过度设计，简化成通用机制。", "agent_memory_workflow"),
    ("history", "之前我们聊过我的项目目标，先回忆再答。", "agent_memory_workflow"),
]

def test_user_journey_write_candidates_and_readback_queries():
    pipe = MemoryWritePipeline(config={"mode":"shadow", "semantic_classifier":{"model_enabled":False}})
    for name, text, expected_subject in CASES:
        ref = pipe.reflect_and_extract(text, "")
        candidates = ref["candidates"]
        if expected_subject is None:
            continue
        assert any(c.subject == expected_subject for c in candidates), name
        c = next(c for c in candidates if c.subject == expected_subject)
        cls = pipe.classify_write(c, namespace="telegram:u1")
        wr = pipe.write_and_verify(c, cls)
        assert wr["written"] is False, name
        assert wr["readback_queries"], name
        assert cls.get("namespace") == "telegram:u1", name

def test_model_fail_closed_user_journey_invalid_json():
    def bad(_prompt):
        return "not json"
    r = classify_memory_semantics("I prefer a durable rule", model_classifier=bad).to_dict()
    assert r["target_store"] == "review"
    assert r["requires_review"] is True
