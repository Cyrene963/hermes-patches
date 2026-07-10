import importlib.util
import json
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "aistudio_distill_review_proposals.py"
    spec = importlib.util.spec_from_file_location("aistudio_distill", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def raw_row(role="user"):
    return {
        "candidate_id": "raw-1",
        "role": role,
        "conversation_id": "conversation-1",
        "turn_index": 2,
        "excerpt": "I prefer durable evidence and verified readback for every memory change.",
    }


def rule(target="core://profiles/preferences/evidence-first", *, selector="id"):
    item = {
        "id": "evidence-first",
        "kind": "user_preference",
        "target": target,
        "draft": "The user prefers durable evidence and verified readback for every memory change.",
        "query": "durable evidence verified readback memory preference",
        "existing_terms": ["durable evidence", "verified readback"],
        "risk": "medium",
    }
    if selector == "id":
        item["source_candidate_id"] = "raw-1"
    elif selector == "regex":
        item["match"] = ["durable evidence", "verified readback"]
    return item


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def write_rules(path, rules):
    path.write_text(json.dumps({"namespace": "telegram:test-user", "rules": rules}), encoding="utf-8")


def test_source_candidate_id_allows_multiple_atomic_facts_from_one_turn():
    m = load_module()
    rows = [raw_row()]
    first = rule()
    second = rule("core://profiles/preferences/second")
    second["id"] = "second-fact"
    assert m.source_for_rule(first, rows) == rows[0]
    assert m.source_for_rule(second, rows) == rows[0]


def test_regex_selector_remains_backward_compatible():
    m = load_module()
    assert m.source_for_rule(rule(selector="regex"), [raw_row()]) == raw_row()


def test_rule_requires_exactly_one_source_selector(tmp_path):
    m = load_module()
    missing = rule()
    missing.pop("source_candidate_id")
    both = rule()
    both["match"] = ["durable evidence"]
    for index, invalid in enumerate([missing, both]):
        path = tmp_path / f"invalid-{index}.json"
        write_rules(path, [invalid])
        try:
            m.load_rules(path)
        except ValueError as exc:
            assert "exactly one source selector" in str(exc)
        else:
            raise AssertionError("invalid selector contract was accepted")


def test_model_turn_cannot_become_proposal(tmp_path, monkeypatch):
    m = load_module()
    input_path = tmp_path / "review.jsonl"
    output_path = tmp_path / "proposals.jsonl"
    clarify_path = tmp_path / "clarify.jsonl"
    rules_path = tmp_path / "rules.json"
    write_jsonl(input_path, [raw_row("model")])
    write_rules(rules_path, [rule()])
    monkeypatch.setattr(m, "graph_search", lambda *args: [])
    monkeypatch.setattr(m, "graph_read", lambda *args: None)
    monkeypatch.setattr(m.sys, "argv", ["distill", "--input", str(input_path), "--output", str(output_path), "--clarification", str(clarify_path), "--rules", str(rules_path)])
    assert m.main() == 2
    assert not output_path.exists()


def test_identical_canonical_content_is_reconciled_not_reproposed(tmp_path, monkeypatch):
    m = load_module()
    input_path = tmp_path / "review.jsonl"
    output_path = tmp_path / "proposals.jsonl"
    clarify_path = tmp_path / "clarify.jsonl"
    rules_path = tmp_path / "rules.json"
    r = rule()
    write_jsonl(input_path, [raw_row()])
    write_rules(rules_path, [r])
    prior = m.make_proposal(r, raw_row(), "telegram:test-user", [])
    prior["status"] = "approved"
    write_jsonl(output_path, [prior])
    monkeypatch.setattr(m, "graph_search", lambda *args: [])
    monkeypatch.setattr(m, "graph_read", lambda uri, ns: {"content": r["draft"]})
    monkeypatch.setattr(m.sys, "argv", ["distill", "--input", str(input_path), "--output", str(output_path), "--clarification", str(clarify_path), "--rules", str(rules_path), "--apply"])
    assert m.main() == 0
    rows = m.load_jsonl(output_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "approved"
    assert rows[0]["candidate"]["metadata"]["review_state"] == "already_canonical"


def test_probable_duplicate_is_not_directly_approvable(monkeypatch):
    m = load_module()
    r = rule()
    monkeypatch.setattr(m, "graph_read", lambda uri, ns: {"content": "parent"} if uri == "core://profiles/preferences" else None)
    hit = {"uri": "core://profiles/preferences/existing", "name": "evidence", "path": "profiles/preferences/evidence", "snippet": "durable evidence and verified readback"}
    proposal = m.make_proposal(r, raw_row(), "telegram:test-user", [hit])
    candidate = proposal["candidate"]
    assert candidate["metadata"]["review_state"] == "needs_dedup_review"
    assert candidate["suggested_store"] == "review"
    assert candidate["metadata"]["possible_duplicate_uris"] == ["core://profiles/preferences/existing"]


def test_missing_parent_is_not_directly_approvable(monkeypatch):
    m = load_module()
    monkeypatch.setattr(m, "graph_read", lambda *args: None)
    proposal = m.make_proposal(rule("core://missing/parent/fact"), raw_row(), "telegram:test-user", [])
    candidate = proposal["candidate"]
    assert candidate["metadata"]["review_state"] == "invalid_parent"
    assert candidate["metadata"]["parent_exists"] is False
    assert candidate["suggested_store"] == "review"
