import json

from agent.active_workstream import is_bare_continuation, resolve_active_workstream


class FakeDB:
    def __init__(self, results):
        self.results = results
        self.seen_user_id = None

    def search_messages(self, **kwargs):
        self.seen_user_id = kwargs.get("user_id")
        return self.results

    def get_anchored_view(self, session_id, message_id, window=5, bookend=3):
        row = next(item for item in self.results if item["session_id"] == session_id)
        return {
            "messages": row["messages"],
            "bookend_start": row["messages"],
            "bookend_end": row["messages"],
            "messages_before": 0,
            "messages_after": 0,
        }

    def get_messages_around(self, session_id, message_id, before=5, after=5):
        row = next(item for item in self.results if item["session_id"] == session_id)
        return row["messages"]

    def get_session(self, session_id):
        row = next(item for item in self.results if item["session_id"] == session_id)
        return {
            "id": session_id,
            "title": row.get("title", ""),
            "started_at": row.get("started_at", 0),
            "ended_at": row.get("ended_at"),
            "source": row.get("source", "telegram"),
        }

    def get_messages(self, session_id, limit=None):
        row = next(item for item in self.results if item["session_id"] == session_id)
        return row["messages"]


def row(session_id="s1", when=20, user="Build the memory system", state="Still pending. Next step: run live verification."):
    return {
        "session_id": session_id,
        "title": "Memory work",
        "timestamp": when,
        "started_at": when,
        "source": "telegram",
        "message_id": when,
        "role": "assistant",
        "content": state,
        "messages": [
            {"id": when - 1, "role": "user", "content": user, "timestamp": when - 1},
            {"id": when, "role": "assistant", "content": state, "timestamp": when},
        ],
    }


def test_only_bare_continuation_triggers():
    assert is_bare_continuation("继续")
    assert is_bare_continuation("continue!")
    assert not is_bare_continuation("继续写小说")
    assert resolve_active_workstream("继续", user_id="").status == "unresolved"


def test_resolves_newest_unfinished_same_user_candidate():
    db = FakeDB([row()])
    result = resolve_active_workstream(
        "继续",
        user_id="user-a",
        current_session_id="current",
        source="telegram",
        db=db,
    )
    assert db.seen_user_id == "user-a"
    assert result.status == "resolved"
    assert result.session_id == "s1"
    assert "live verification" in result.next_step
    prompt = result.to_prompt()
    assert "executing the next safe step" in prompt
    assert len(prompt) <= 1200


def test_completed_candidate_is_rejected():
    db = FakeDB([row(state="All done. Fully complete.")])
    assert resolve_active_workstream("继续", user_id="user-a", db=db).status == "unresolved"


def test_equal_recency_candidates_are_ambiguous():
    db = FakeDB([row("s1", 20), row("s2", 20, user="Other goal")])
    result = resolve_active_workstream("继续", user_id="user-a", db=db)
    assert result.status == "ambiguous"
    assert result.candidate_count == 2
    assert "AMBIGUOUS" in result.to_prompt()
