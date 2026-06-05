from agent.memory_semantic_classifier import classify_memory_semantics


def kind(text):
    return classify_memory_semantics(text).to_dict()


def test_novel_writing_preference():
    r = kind('我跟你聊了一堆对小说应该怎么写的看法，低频心跳不要有 AI 味，要保留漫画质感写实。')
    assert r['memory_kind'] in {'creative_preference', 'target_function'}
    assert r['target_store'] == 'memory_graph'
    assert r['privacy_scope'] == 'user_private'
    assert r['readback_queries']


def test_user_correction_prevention_loop():
    r = kind('错错错，我纠正你错误的时候，你应该立即全面调查根因，抽象通用解决方案和 reject gate，防复发。')
    assert r['memory_kind'] == 'correction_learning_event'
    assert r['requires_review'] is True
    assert 'reject' in r['reject_gate'].lower() or '根因' in r['reject_gate']


def test_exam_context():
    r = kind('我下周就要 DSE 考试了，这是我的时间表和考试范围，帮我安排复习。')
    assert r['memory_kind'] == 'exam_context'
    assert r['target_path'].endswith('考试上下文')
    assert any('考试' in q or 'exam' in q for q in r['readback_queries'])


def test_claude_code_route():
    r = kind('以后用 Claude Code 审 diff 的时候，不要看到 not logged in 就放弃，先查配置和凭据路径。')
    assert r['memory_kind'] == 'credential_route'
    assert r['privacy_scope'] == 'sensitive'
    assert r['requires_review'] is True
    assert 'raw secrets' in r['reject_gate'] or 'secrets' in r['reject_gate']


def test_github_token_route():
    r = kind('我之前给过 GitHub token，你要用 PAT 的时候先回忆和查 secret 路径，不要直接说我没给过。')
    assert r['memory_kind'] == 'credential_route'
    assert r['target_store'] == 'memory_graph'
    assert r['requires_review'] is True


def test_ack_ignored():
    r = kind('哈哈可以')
    assert r['memory_kind'] == 'ignore'
    assert r['target_store'] == 'ignore'


def test_temporary_ignored():
    r = kind('我现在困')
    assert r['memory_kind'] == 'temporary'
    assert r['target_store'] == 'ignore'


def test_mixed_temporary_plus_preference():
    r = kind('我现在困，但以后写报告我更关心真实数据和来源，不要编造。')
    assert r['memory_kind'] in {'user_fact', 'correction_learning_event'}
    assert r['target_store'] in {'memory_graph', 'review'}


def test_correction_old_memory():
    r = kind('不是中国历史，是 DSE Economics；以后安排复习前先召回我的真实科目。')
    assert r['memory_kind'] == 'correction_learning_event'
    assert r['readback_queries']


def test_necessary_as_overengineering_correction():
    r = kind('有必要吗？你这个做法过度设计，应该简化成通用机制。')
    assert r['memory_kind'] == 'correction_learning_event'
    assert r['requires_review'] is True


def test_short_continuation_routes_to_active_workstream_review():
    r = kind('继续')
    assert r['memory_kind'] == 'active_workstream_context'
    assert r['target_store'] == 'review'
    assert r['requires_review'] is True
    assert any('continue' in q.lower() or '继续' in q for q in r['readback_queries'])


def test_project_identity_question_requires_inventory_verification():
    r = kind('这是我的 AI 项目吗？')
    assert r['memory_kind'] == 'project_identity_verification'
    assert r['target_store'] == 'review'
    assert r['requires_review'] is True
    assert any('project' in q.lower() or '项目' in q for q in r['readback_queries'])


def test_explicit_memory_request_requires_readback_review():
    r = kind('把这个长期记住：以后遇到同类问题要先做 readback 验证。')
    assert r['memory_kind'] == 'explicit_memory_request'
    assert r['target_store'] == 'review'
    assert r['requires_review'] is True
    assert any('readback' in q.lower() or '长期记住' in q for q in r['readback_queries'])


def test_creative_preference_accepts_bie_negative_marker():
    r = kind('继续写低频心跳，别有 AI 味。')
    assert r['memory_kind'] == 'creative_preference'
    assert r['target_store'] == 'memory_graph'
    assert r['requires_review'] is False


def test_model_json_path_validates_and_fail_closed():
    def model(_prompt):
        return '{"memory_kind":"user_fact","durability":"long_term","confidence":0.92,"evidence_quote":"Prefer concise","target_store":"memory_graph","target_path":"用户档案/偏好","requires_review":false,"privacy_scope":"user_private","readback_queries":["user concise preference"],"reject_gate":"","reason":"explicit preference"}'
    r = classify_memory_semantics('I prefer concise answers', model_classifier=model).to_dict()
    assert r['memory_kind'] == 'user_fact'
    assert r['confidence'] == 0.92

    def bad(_prompt):
        raise RuntimeError('model down')
    r2 = classify_memory_semantics('哈哈可以', model_classifier=bad).to_dict()
    assert r2['memory_kind'] == 'ignore'
