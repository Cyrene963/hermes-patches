import importlib.util
import json
from pathlib import Path

from agent.memory_task_contract import EvidenceItem, build_task_memory_contract


PLUGIN_PATH = Path.home() / ".hermes" / "plugins" / "memory-graph" / "__init__.py"


def _plugin():
    spec = importlib.util.spec_from_file_location("memory_graph_contract_plugin_test", PLUGIN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_owner_maps_to_configured_private_namespace_but_other_user_does_not(monkeypatch):
    plugin = _plugin()
    monkeypatch.setattr(plugin, "_default_terminal_user", lambda: "owner-1")
    assert plugin._resolve_namespace(user_id="owner-1", chat_id="owner-1", platform="cli", chat_type="dm") == "telegram:owner-1"
    assert plugin._resolve_namespace(user_id="other-2", chat_id="other-2", platform="cli", chat_type="dm") == "cli:other-2"
    assert plugin._resolve_namespace(user_id="owner-1", chat_id="group-9", platform="cli", chat_type="group") == "cli:group:group-9"


def test_contract_evidence_merge_keeps_both_lanes_and_deduplicates():
    plugin = _plugin()
    contract_lane = [{"uri": "core://neutral/contract", "content": "contract"}]
    recall_lane = [
        {"uri": "core://neutral/contract", "content": "duplicate"},
        {"uri": "core://neutral/authoritative", "content": "authoritative"},
    ]
    merged = plugin._merge_contract_evidence(contract_lane, recall_lane)
    assert [item["uri"] for item in merged] == [
        "core://neutral/contract",
        "core://neutral/authoritative",
    ]


def test_post_llm_plugin_does_not_bypass_full_write_pipeline():
    plugin = _plugin()
    plugin._db_ready = False
    assert plugin._post_llm_call(
        user_message="remember this neutral preference",
        assistant_response="assistant text must not be persisted by this hook",
        platform="cli",
        user_id="neutral-user",
        chat_id="neutral-user",
    ) is None
    assert plugin._db_ready is False


def test_post_tool_and_post_llm_emit_behavioral_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    plugin = _plugin()
    contract = build_task_memory_contract(
        "修复这个 bug",
        [EvidenceItem("core://用户档案/preferences/verification", "用户要求先验证，必须有真实运行测试证据。")],
        namespace="tenant:a",
    )
    with plugin._contract_lock:
        plugin._turn_contracts["s1"] = contract
        plugin._turn_tool_events["s1"] = []

    plugin._post_tool_call(
        session_id="s1",
        tool_name="terminal",
        result={"exit_code": 0, "output": "10 passed"},
    )
    assert plugin._transform_contract_output(response_text="done", session_id="s1") is None
    plugin._post_llm_contract_verdict(session_id="s1", assistant_response="done")

    log_path = tmp_path / ".hermes" / "logs" / "memory_contracts" / "contracts.jsonl"
    row = json.loads(log_path.read_text().splitlines()[-1])
    assert row["verdict"]["passed"] is True
    assert row["verdict"]["tools_seen"] == ["terminal"]
    assert "s1" not in plugin._turn_contracts


def test_tool_result_summary_does_not_persist_arbitrary_payload():
    plugin = _plugin()
    summary = plugin._safe_tool_result_summary({
        "success": True,
        "output": "x" * 1000,
        "private_blob": "must-not-be-copied",
    })
    assert summary["success"] is True
    assert len(summary["output"]) == 500
    assert "private_blob" not in summary


def test_unmet_contract_transforms_completion_claim():
    plugin = _plugin()
    contract = build_task_memory_contract(
        "修复这个 bug",
        [EvidenceItem("core://用户档案/preferences/verification", "用户要求先验证，必须有真实运行测试证据。")],
        namespace="tenant:a",
    )
    with plugin._contract_lock:
        plugin._turn_contracts["s2"] = contract
        plugin._turn_tool_events["s2"] = []

    transformed = plugin._transform_contract_output(response_text="已经全部修复。", session_id="s2")
    assert "NOT VERIFIED" in transformed
    assert "coding.verify" in transformed
    directive = plugin._pre_verify_contract(session_id="s2", attempt=0, final_response="已经全部修复。")
    assert directive["action"] == "continue"
    assert "bounded repair plan (attempt 1/2)" in directive["message"]
    assert "Run the narrowest relevant test" in directive["message"]
    second = plugin._pre_verify_contract(session_id="s2", attempt=1, final_response="已经全部修复。")
    assert "attempt 2/2" in second["message"]
    exhausted = plugin._pre_verify_contract(session_id="s2", attempt=2, final_response="已经全部修复。")
    assert "repair is exhausted" in exhausted["message"]
    assert "Do not repeat" in exhausted["message"]
    plugin._post_llm_contract_verdict(session_id="s2", assistant_response=transformed)
    assert "s2" not in plugin._turn_repair_fingerprints
