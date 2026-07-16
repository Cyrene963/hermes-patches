import importlib.util
import json
import os
import sqlite3
import time
from pathlib import Path


def _load(script: Path, home: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(home))
    spec = importlib.util.spec_from_file_location("continuation_watchdog_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path, monkeypatch, *, source="cli", active=False, nudges=0):
    home = tmp_path / ".hermes"
    repo = home / "hermes-agent-candidate-20260703p"
    bin_dir = repo / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    workdir = tmp_path / "project"
    workdir.mkdir()
    capture = tmp_path / "capture.json"
    hermes = bin_dir / "hermes"
    hermes.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        f"pathlib.Path({str(capture)!r}).write_text(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd()}}))\n",
        encoding="utf-8",
    )
    hermes.chmod(0o755)
    db = sqlite3.connect(home / "state.db")
    db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, cwd TEXT)")
    db.execute("INSERT INTO sessions VALUES (?, ?, ?)", ("s1", source, str(workdir)))
    db.commit()
    db.close()
    checkpoints = home / "runtime" / "continuations"
    checkpoints.mkdir(parents=True)
    payload = {
        "session_id": "s1",
        "status": "stalled_incomplete",
        "updated_at": time.time() - 1000,
        "nudge_count": nudges,
        "max_nudges": 3,
        "next_prompt": "continue safely",
    }
    checkpoint = checkpoints / "s1.json"
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")
    if active:
        (home / "runtime" / "active_sessions.json").write_text(
            json.dumps({"entries": [{"session_id": "s1"}]}), encoding="utf-8"
        )
    script = Path(
        os.environ.get(
            "CONTINUATION_WATCHDOG_SCRIPT",
            Path(__file__).resolve().parents[2] / "scripts" / "continuation-watchdog.py",
        )
    )
    module = _load(script, home, monkeypatch)
    return module, checkpoint, capture, workdir


def test_execute_resumes_exact_session_in_recorded_cwd(tmp_path, monkeypatch):
    module, checkpoint, capture, workdir = _fixture(tmp_path, monkeypatch)
    module.main()
    recorded = json.loads(capture.read_text(encoding="utf-8"))
    assert recorded["argv"] == ["-z", "continue safely", "--resume", "s1"]
    assert recorded["cwd"] == str(workdir)
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert state["nudge_count"] == 1


def test_active_session_is_not_resumed(tmp_path, monkeypatch):
    module, _checkpoint, capture, _workdir = _fixture(tmp_path, monkeypatch, active=True)
    module.main()
    assert not capture.exists()


def test_non_cli_session_is_not_impersonated(tmp_path, monkeypatch):
    module, _checkpoint, capture, _workdir = _fixture(tmp_path, monkeypatch, source="telegram")
    module.main()
    assert not capture.exists()


def test_circuit_breaker_stops_after_max_nudges(tmp_path, monkeypatch):
    module, _checkpoint, capture, _workdir = _fixture(tmp_path, monkeypatch, nudges=3)
    module.main()
    assert not capture.exists()


def test_observe_mode_never_executes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_CONTINUATION_WATCHDOG_MODE", "observe")
    module, _checkpoint, capture, _workdir = _fixture(tmp_path, monkeypatch)
    module.main()
    assert not capture.exists()
