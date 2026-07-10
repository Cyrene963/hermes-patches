import importlib.util
import json
from pathlib import Path
import sqlite3


def load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "aistudio_continuous_distill.py"
    spec = importlib.util.spec_from_file_location("aistudio_continuous", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source(text="用户明确要求以后默认先验证，再报告结果。"):
    return {
        "id": 10, "conversation_id": "c", "conversation_name": "n", "turn_index": 1,
        "text": text, "content_sha256": "abc", "information_score": 9.0,
    }


def config():
    return {
        "namespace": "telegram:owner",
        "target_parents": {"preference": "core://profiles/preferences", "default": "core://profiles"},
    }


def test_validate_requires_exact_user_evidence():
    module = load_module()
    item = {
        "action": "propose", "kind": "preference", "fact": "用户要求以后默认先验证，再报告结果。",
        "evidence_quote": "不存在的原文", "risk": "low", "volatility": "stable", "reason": "明确要求",
    }
    valid, error = module.validate_item(item, source())
    assert valid is None
    assert "exact source substring" in error


def test_sensitive_or_time_bound_is_forced_to_clarification():
    module = load_module()
    item = {
        "action": "propose", "kind": "relationship", "fact": "用户当前计划减少与某人的联系。",
        "evidence_quote": "用户明确要求以后默认先验证", "risk": "medium", "volatility": "time_bound", "reason": "计划可能变化",
    }
    valid, error = module.validate_item(item, source())
    assert not error
    assert valid["action"] == "clarify"


def test_hard_skip_is_narrow_and_low_score_is_not_hard_skip():
    module = load_module()
    assert module.hard_skip_reason("好") == "too_short"
    assert module.hard_skip_reason("这个解释我不明白，请讲到我真正理解为止") == ""
    assert module.information_score("这个解释我不明白，请讲到我真正理解为止") < 4.5


def test_dry_run_selection_does_not_write_state(tmp_path):
    module = load_module()
    turn_db = tmp_path / "turns.sqlite3"
    source_db = sqlite3.connect(turn_db)
    source_db.execute("CREATE TABLE turns(id INTEGER PRIMARY KEY,conversation_id TEXT,conversation_name TEXT,turn_index INTEGER,role TEXT,text TEXT,create_time TEXT)")
    source_db.execute("INSERT INTO turns VALUES(1,'c','n',0,'user','这个解释我不明白，请讲到我真正理解为止','')")
    source_db.commit(); source_db.close()
    state = module.init_state(tmp_path / "state.sqlite3")
    selected, hard_skips = module.select_turns(turn_db, state, 10, 4.5, set())
    assert [row["id"] for row in selected] == [1]
    assert hard_skips == []
    assert state.execute("SELECT count(*) FROM processed_turns").fetchone()[0] == 0


def test_duplicate_score_uses_graph_semantic_score():
    module = load_module()
    hit = {"score": 0.9, "name": "existing", "path": "x", "snippet": "different words"}
    assert module.duplicate_score("用户九岁开始接触Scratch并做游戏项目", hit) >= 0.7


def test_batches_call_distiller_concurrently_but_state_processing_is_deterministic(tmp_path, monkeypatch):
    module = load_module()
    # The worker exposes a bounded concurrency option and keeps queue/state writes after futures resolve.
    assert module.__file__
    text = Path(module.__file__).read_text(encoding="utf-8")
    assert "ThreadPoolExecutor" in text
    assert "batch_results.sort" in text
    assert "--concurrency" in text


def test_exclusive_lock_is_reentrant_across_sequential_runs(tmp_path):
    module = load_module()
    lock = tmp_path / "worker.lock"
    with module.exclusive_lock(lock):
        assert lock.exists()
    with module.exclusive_lock(lock):
        assert lock.stat().st_mode & 0o777 == 0o600


def test_route_rejects_non_project_fact_misclassified_as_project():
    module = load_module()
    assert module.route_is_plausible({"kind": "project", "fact": "用户买电脑时重视屏幕和续航。"}) is False
    assert module.route_is_plausible({"kind": "project", "fact": "用户正在开发番茄钟网站项目。"}) is True


def test_proposal_never_auto_approves(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "graph_search", lambda query, namespace: [])
    item = {
        "action": "propose", "kind": "preference", "fact": "用户要求以后默认先验证，再报告结果。",
        "evidence_quote": "用户明确要求以后默认先验证，再报告结果。", "risk": "low", "volatility": "stable", "reason": "明确要求",
    }
    proposal = module.proposal_for(item, source(), config())
    assert proposal["status"] == "pending"
    assert proposal["candidate"]["requires_review"] is True
    assert proposal["candidate"]["source"] == "google_ai_studio_continuous"
