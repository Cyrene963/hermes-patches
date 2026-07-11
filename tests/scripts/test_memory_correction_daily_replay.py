import importlib
import json
import os
import subprocess
import sys
from pathlib import Path


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
    return {
        "date": day,
        "ledger_sha256": "a" * 64,
        "total": 1,
        "passed": 1,
        "failed": 0,
        "invalid": 0,
    }


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


def test_history_requires_valid_ledger_digest(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    module.HISTORY.mkdir(parents=True)
    item = successful("2026-07-10")
    item["ledger_sha256"] = "not-recorded"
    module._atomic_json(module.HISTORY / "2026-07-10.json", item)
    assert module._successful_history() == []


def test_daily_history_is_immutable(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    path = module.HISTORY / "2026-07-10.json"
    original = successful("2026-07-10")
    replacement = {**original, "passed": 999}
    assert module._write_history_once(path, original) is True
    assert module._write_history_once(path, replacement) is False
    assert json.loads(path.read_text()) == original


def test_ledger_digest_does_not_copy_private_content(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    private_text = "private correction text"
    module.LEDGER.parent.mkdir(parents=True)
    module.LEDGER.write_text(private_text)
    digest = module._ledger_sha256(module.LEDGER)
    assert len(digest) == 64
    assert private_text not in digest


def test_provenance_only_downgrade_preserves_prior_complete_result(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    prior = {"passed_gates": 41, "total_gates": 41}
    evaluated = {"next_gaps": [
        {"detail": "commit unavailable: deadbeef"},
        {"detail": "commit unavailable: cafebabe"},
    ]}
    assert module._should_preserve_prior_result(prior, evaluated) is True


def test_real_regression_never_preserves_prior_complete_result(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path)
    prior = {"passed_gates": 41, "total_gates": 41}
    evaluated = {"next_gaps": [{"detail": "health check failed: ConnectionError"}]}
    assert module._should_preserve_prior_result(prior, evaluated) is False


def test_script_direct_execution_resolves_repo_imports(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HERMES_HOME": str(home),
        "HERMES_AGENT_DIR": str(tmp_path / "missing-agent-checkout"),
    }
    result = subprocess.run(
        [sys.executable, str(repo / "scripts" / "memory_correction_daily_replay.py")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Memory correction regression alert" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
