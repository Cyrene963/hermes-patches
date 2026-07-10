import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "migrate_review_backlog_to_clarification.py"
    spec = importlib.util.spec_from_file_location("migrate_review", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proposal(*, role="user", source="google_ai_studio", text="user-authored evidence"):
    return {
        "proposal_id": "rp-test",
        "candidate": {
            "source": source,
            "content": text,
            "evidence_quote": text,
            "metadata": {"role": role},
        },
    }


def test_role_pure_aistudio_user_candidate_is_accepted():
    module = load_module()
    assert module._is_role_pure_user_candidate(proposal()) is True


def test_aistudio_model_candidate_is_rejected():
    module = load_module()
    assert module._is_role_pure_user_candidate(proposal(role="model")) is False


def test_mixed_user_model_transcript_is_rejected():
    module = load_module()
    mixed = "user question Model 9:07 PM Thoughts Expand to view model thoughts model answer"
    assert module._is_role_pure_user_candidate(proposal(text=mixed)) is False


def test_non_aistudio_clean_backlog_remains_compatible():
    module = load_module()
    assert module._is_role_pure_user_candidate(proposal(role="", source="state_db_message")) is True
