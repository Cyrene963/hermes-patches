import importlib.util
import json
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "aistudio_memory_watchdog.py"
    spec = importlib.util.spec_from_file_location("aistudio_watchdog", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_artifacts(base):
    for name in [
        "manifest.jsonl", "aistudio_memory.sqlite3", "turns.jsonl",
        "aistudio_turns.sqlite3", "review_queue.jsonl", "distillation_rules.json",
    ]:
        (base / name).write_text(f"{name}\n", encoding="utf-8")


def test_artifacts_ready_requires_every_nonempty_file(tmp_path, monkeypatch):
    m = load_module()
    monkeypatch.setattr(m, "BASE", tmp_path)
    create_artifacts(tmp_path)
    assert m.artifacts_ready() is True
    (tmp_path / "turns.jsonl").write_text("", encoding="utf-8")
    assert m.artifacts_ready() is False


def test_input_fingerprint_changes_with_manifest_review_or_rules(tmp_path, monkeypatch):
    m = load_module()
    monkeypatch.setattr(m, "BASE", tmp_path)
    create_artifacts(tmp_path)
    before = m.input_fingerprint()
    (tmp_path / "distillation_rules.json").write_text('{"rules":[1]}', encoding="utf-8")
    assert m.input_fingerprint() != before


def test_prune_reports_keeps_bounded_files_per_type(tmp_path, monkeypatch):
    m = load_module()
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(m, "REPORTS", reports)
    for index in range(5):
        (reports / f"drive-sync-{index}.json").write_text(json.dumps({"i": index}), encoding="utf-8")
        (reports / f"parse-report-{index}.json").write_text(json.dumps({"i": index}), encoding="utf-8")
    assert m.prune_reports(keep_per_pattern=2) == 6
    assert len(list(reports.glob("drive-sync-*.json"))) == 2
    assert len(list(reports.glob("parse-report-*.json"))) == 2


def test_main_fails_closed_without_explicit_base_or_private_symlink(tmp_path, monkeypatch, capsys):
    m = load_module()
    monkeypatch.setattr(m, "_base_env", "")
    monkeypatch.setattr(m, "BASE", tmp_path / "missing")
    assert m.main() == 2
    assert "required" in capsys.readouterr().err
