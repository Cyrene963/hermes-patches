import importlib
import json


def load_module(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_AGENT_DIR", str(tmp_path / "agent-checkout"))
    import scripts.memory_correction_daily_replay as daily_replay
    return importlib.reload(daily_replay)


def manifest():
    return {
        "schema_version": 1,
        "name": "test",
        "capabilities": [{
            "id": "correction_learning",
            "weight": 1,
            "gates": [{"id": "daily_replay_history", "status": "MISSING"}],
        }],
    }


def successful(day):
    return {"date": day, "total": 1, "passed": 1, "failed": 0, "invalid": 0}


def test_one_day_does_not_promote(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    module.HISTORY.mkdir(parents=True)
    module.SCORECARD.parent.mkdir(parents=True, exist_ok=True)
    module.SCORECARD.write_text(json.dumps(manifest()))
    module._atomic_json(module.HISTORY / "2026-07-10.json", successful("2026-07-10"))
    history = module._successful_history()
    module._promote_scorecard(history)
    data = json.loads(module.SCORECARD.read_text())
    assert data["capabilities"][0]["gates"][0]["status"] == "MISSING"


def test_two_distinct_days_promote(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    module.HISTORY.mkdir(parents=True)
    module.SCORECARD.parent.mkdir(parents=True, exist_ok=True)
    module.SCORECARD.write_text(json.dumps(manifest()))
    for day in ("2026-07-10", "2026-07-11"):
        module._atomic_json(module.HISTORY / f"{day}.json", successful(day))
    history = module._successful_history()
    module._promote_scorecard(history)
    gate = json.loads(module.SCORECARD.read_text())["capabilities"][0]["gates"][0]
    assert gate["status"] == "PASS"
    assert "2026-07-10 and 2026-07-11" in gate["evidence"]


def test_filename_date_mismatch_is_rejected(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    module.HISTORY.mkdir(parents=True)
    module._atomic_json(module.HISTORY / "2026-07-11.json", successful("2026-07-10"))
    assert module._successful_history() == []
