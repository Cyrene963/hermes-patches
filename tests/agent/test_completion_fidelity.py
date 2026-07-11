from agent.completion_fidelity import evaluate_completion_evidence


REQS = [
    {"id": "artifact", "kind": "artifact", "path": "/tmp/neutral.out", "sha256": "abc"},
    {"id": "tests", "kind": "command", "command_id": "tests", "output_contains": "passed"},
    {"id": "api", "kind": "api", "api_id": "health", "status": 200, "body_contains": '"ready": true'},
    {"id": "todos", "kind": "no_active_todos"},
]


def valid_evidence():
    return {
        "artifacts": [{"path": "/tmp/neutral.out", "exists": True, "sha256": "abc"}],
        "commands": [{"id": "tests", "exit_code": 0, "output": "12 passed"}],
        "apis": [{"id": "health", "status": 200, "body": '{"ready": true}'}],
        "todos": [{"id": "done", "status": "completed"}],
    }


def test_all_acceptance_conditions_are_required():
    result = evaluate_completion_evidence(REQS, valid_evidence())
    assert result.complete is True
    assert result.confidence == 1


def test_missing_artifact_blocks_completion():
    evidence = valid_evidence(); evidence["artifacts"] = []
    result = evaluate_completion_evidence(REQS, evidence)
    assert result.complete is False
    assert "artifact" in result.missing


def test_wrong_hash_blocks_completion_even_when_file_exists():
    evidence = valid_evidence(); evidence["artifacts"][0]["sha256"] = "wrong"
    assert "artifact" in evaluate_completion_evidence(REQS, evidence).failed


def test_nonzero_command_blocks_completion():
    evidence = valid_evidence(); evidence["commands"][0]["exit_code"] = 1
    assert "tests" in evaluate_completion_evidence(REQS, evidence).failed


def test_http_200_without_semantic_marker_blocks_completion():
    evidence = valid_evidence(); evidence["apis"][0]["body"] = '{"status": "ok"}'
    assert "api" in evaluate_completion_evidence(REQS, evidence).failed


def test_pending_todo_blocks_completion():
    evidence = valid_evidence(); evidence["todos"].append({"id": "next", "status": "pending"})
    assert "todos" in evaluate_completion_evidence(REQS, evidence).failed


def test_unknown_requirement_kind_fails_closed():
    result = evaluate_completion_evidence([{"id": "unknown", "kind": "mystery"}], {})
    assert result.complete is False
    assert result.failed == ("unknown",)
