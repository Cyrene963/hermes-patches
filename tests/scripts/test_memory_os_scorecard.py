import json

from scripts.memory_os_scorecard import evaluate_scorecard


def write_scorecard(tmp_path, capabilities):
    path = tmp_path / "scorecard.json"
    path.write_text(json.dumps({"schema_version": 1, "capabilities": capabilities}))
    return path


def test_skip_and_missing_score_zero(tmp_path):
    path = write_scorecard(tmp_path, [{
        "id": "recall",
        "weight": 10,
        "gates": [
            {"id": "pass", "status": "PASS", "evidence": "synthetic"},
            {"id": "skip", "status": "SKIP"},
            {"id": "missing", "status": "MISSING"},
        ],
    }])
    report = evaluate_scorecard(path)
    assert report["score"] == 33.33
    assert report["release_passed"] is False
    assert report["passed_gates"] == 1


def test_missing_evidence_file_invalidates_declared_pass(tmp_path):
    path = write_scorecard(tmp_path, [{
        "id": "write",
        "weight": 5,
        "gates": [{
            "id": "artifact",
            "status": "PASS",
            "evidence_file": str(tmp_path / "missing.json"),
        }],
    }])
    report = evaluate_scorecard(path)
    assert report["score"] == 0
    assert report["capabilities"][0]["gates"][0]["status"] == "MISSING"


def test_json_requirement_is_verified(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"fail": 1}))
    path = write_scorecard(tmp_path, [{
        "id": "semantic",
        "weight": 5,
        "gates": [{
            "id": "eval",
            "status": "PASS",
            "json": str(evidence),
            "json_require": {"fail": 0},
        }],
    }])
    report = evaluate_scorecard(path)
    assert report["score"] == 0
    assert report["capabilities"][0]["gates"][0]["status"] == "FAIL"


def test_next_gaps_sorted_by_capability_weight(tmp_path):
    path = write_scorecard(tmp_path, [
        {"id": "small", "weight": 2, "gates": [{"id": "x", "status": "MISSING"}]},
        {"id": "large", "weight": 12, "gates": [{"id": "y", "status": "MISSING"}]},
    ])
    report = evaluate_scorecard(path)
    assert report["next_gaps"][0]["capability"] == "large"
