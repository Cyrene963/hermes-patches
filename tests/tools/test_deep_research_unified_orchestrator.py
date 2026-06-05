"""Focused tests for the unified deep-research orchestrator lanes.

These tests exercise the generic lane-composition policy without performing live
network calls. The orchestrator itself lives in the Hermes profile scripts
surface because it is installed by the patch overlay.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _load_orchestrator():
    script = Path(
        os.environ.get(
            "HERMES_DEEP_RESEARCH_ORCHESTRATOR",
            str(Path.home() / ".hermes" / "scripts" / "hermes_deep_research_orchestrator.py"),
        )
    )
    spec = importlib.util.spec_from_file_location("hermes_deep_research_orchestrator", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unified_auto_runs_classic_complement_for_standard_budget(monkeypatch, tmp_path):
    mod = _load_orchestrator()
    calls = []

    def fake_code_plan(query, timeout, output_root=None):
        calls.append(("code", query, timeout, output_root))
        return {
            "ok": True,
            "overall_status": "Verified working",
            "source_count": 3,
            "source_health": {"with_content": 2, "with_error": 0, "primary_like": 1},
            "run_dir": str(tmp_path / "code"),
        }

    def fake_classic(query, budget, timeout):
        calls.append(("classic", query, budget, timeout))
        return {"ok": True, "budget": budget, "items": [{"url": "https://example.org/source"}]}

    monkeypatch.setattr(mod, "run_search_as_code", fake_code_plan)
    monkeypatch.setattr(mod, "smart_search_deep", fake_classic)

    smart, code_plan, classic = mod.build_unified_retrieval_state(
        "portable research architecture", "standard", "auto", 45, str(tmp_path)
    )

    assert smart["ok"] is True
    assert smart["mode"] == "unified_auto"
    assert code_plan["ok"] is True
    assert classic["ok"] is True
    assert [c[0] for c in calls] == ["code", "classic"]
    assert smart["lanes"]["search_as_code"]["health"]["with_content"] == 2
    assert smart["lanes"]["classic_smart_search"]["status"] == "Verified working"


def test_unified_auto_skips_classic_for_healthy_quick_budget(monkeypatch, tmp_path):
    mod = _load_orchestrator()

    monkeypatch.setattr(
        mod,
        "run_search_as_code",
        lambda query, timeout, output_root=None: {
            "ok": True,
            "overall_status": "Verified working",
            "source_count": 4,
            "source_health": {"with_content": 2, "with_error": 0, "primary_like": 1},
        },
    )

    def unexpected_classic(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("classic lane should not run for healthy quick-budget code-plan")

    monkeypatch.setattr(mod, "smart_search_deep", unexpected_classic)

    smart, _code_plan, classic = mod.build_unified_retrieval_state(
        "small lookup", "quick", "auto", 45, str(tmp_path)
    )

    assert smart["ok"] is True
    assert smart["mode"] == "unified_auto"
    assert classic["skipped"] is True
    assert smart["lanes"]["classic_smart_search"]["status"] == "skipped"


def test_unified_auto_uses_classic_when_code_plan_is_shallow(monkeypatch, tmp_path):
    mod = _load_orchestrator()

    monkeypatch.setattr(
        mod,
        "run_search_as_code",
        lambda query, timeout, output_root=None: {
            "ok": True,
            "overall_status": "Verified working",
            "source_count": 1,
            "source_health": {"with_content": 0, "with_error": 0, "primary_like": 0},
        },
    )
    monkeypatch.setattr(
        mod,
        "smart_search_deep",
        lambda query, budget, timeout: {"ok": True, "budget": budget, "mode": "classic"},
    )

    smart, _code_plan, classic = mod.build_unified_retrieval_state(
        "needs backup", "quick", "auto", 45, str(tmp_path)
    )

    assert smart["ok"] is True
    assert classic["ok"] is True
    assert smart["lanes"]["search_as_code"]["health"]["with_content"] == 0
    assert smart["lanes"]["classic_smart_search"]["ok"] is True


def test_unified_auto_runs_classic_when_code_plan_has_errors(monkeypatch, tmp_path):
    mod = _load_orchestrator()
    calls = []

    monkeypatch.setattr(
        mod,
        "run_search_as_code",
        lambda query, timeout, output_root=None: {
            "ok": True,
            "overall_status": "Verified working",
            "source_count": 4,
            "source_health": {"with_content": 3, "with_error": 1, "primary_like": 0},
        },
    )

    def fake_classic(query, budget, timeout):
        calls.append((query, budget, timeout))
        return {"ok": True, "budget": budget, "mode": "classic_complement"}

    monkeypatch.setattr(mod, "smart_search_deep", fake_classic)

    smart, _code_plan, classic = mod.build_unified_retrieval_state(
        "provider-error should get complement", "quick", "auto", 45, str(tmp_path)
    )

    assert smart["ok"] is True
    assert classic["ok"] is True
    assert calls == [("provider-error should get complement", "quick", 45)]
    assert smart["lanes"]["search_as_code"]["health"]["with_error"] == 1
    assert smart["lanes"]["classic_smart_search"]["status"] == "Verified working"


def test_code_plan_mode_fails_closed_without_classic(monkeypatch, tmp_path):
    mod = _load_orchestrator()

    monkeypatch.setattr(
        mod,
        "run_search_as_code",
        lambda query, timeout, output_root=None: {
            "ok": False,
            "overall_status": "Degraded",
            "error_type": "fixture_failure",
            "error": "synthetic failure",
        },
    )

    def unexpected_classic(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("explicit code_plan mode must not silently fall back")

    monkeypatch.setattr(mod, "smart_search_deep", unexpected_classic)

    smart, code_plan, classic = mod.build_unified_retrieval_state(
        "fail closed", "standard", "code_plan", 45, str(tmp_path)
    )

    assert smart["ok"] is False
    assert smart["mode"] == "code_plan"
    assert smart["error_type"] == "fixture_failure"
    assert code_plan["ok"] is False
    assert classic["skipped"] is True
