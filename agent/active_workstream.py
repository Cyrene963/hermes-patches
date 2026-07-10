"""Bounded, user-scoped recovery of an active workstream for bare continuation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any


_BARE_CONTINUATION_RE = re.compile(r"^\s*(继续|continue|go on|接着|继续吧)[。.!！?？]*\s*$", re.I)
_UNFINISHED_RE = re.compile(
    r"未完成|继续|下一步|pending|in[_ -]?progress|remaining|todo|blocked|还需|下一阶段|next step",
    re.I,
)
_COMPLETED_RE = re.compile(r"全部完成|已完成全部|100%|all done|fully complete", re.I)


@dataclass(frozen=True)
class ActiveWorkstream:
    status: str
    session_id: str = ""
    title: str = ""
    goal: str = ""
    latest_state: str = ""
    next_step: str = ""
    confidence: float = 0.0
    candidate_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_prompt(self) -> str:
        if self.status == "resolved":
            return (
                "[Recovered Active Workstream]\n"
                f"Title: {self.title}\n"
                f"Goal: {self.goal}\n"
                f"Latest state: {self.latest_state}\n"
                f"Next safe step: {self.next_step}\n"
                "Continue by executing the next safe step. Do not ask the user to repeat context."
            )
        if self.status == "ambiguous":
            return (
                "[Active Workstream: AMBIGUOUS]\n"
                "Several same-user unfinished workstreams are equally plausible. "
                "Do not silently select one; ask one concise disambiguation question."
            )
        return ""


def is_bare_continuation(text: str) -> bool:
    return bool(_BARE_CONTINUATION_RE.match(text or ""))


def _message_text(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return re.sub(r"\s+", " ", str(item.get("content") or item.get("text") or "")).strip()


def _candidate_from_result(row: dict[str, Any]) -> dict[str, Any] | None:
    start = list(row.get("bookend_start") or [])
    end = list(row.get("bookend_end") or [])
    messages = list(row.get("messages") or [])
    all_messages = [item for item in start + messages + end if isinstance(item, dict)]
    user_messages = [_message_text(item) for item in all_messages if item.get("role") == "user"]
    assistant_messages = [_message_text(item) for item in all_messages if item.get("role") == "assistant"]
    user_messages = [text for text in user_messages if text and not is_bare_continuation(text)]
    assistant_messages = [text for text in assistant_messages if text]
    if not user_messages or not assistant_messages:
        return None
    latest = assistant_messages[-1]
    combined = " ".join(assistant_messages[-3:])
    if _COMPLETED_RE.search(latest) and not _UNFINISHED_RE.search(latest):
        return None
    if not _UNFINISHED_RE.search(combined):
        return None
    next_step = ""
    for text in reversed(assistant_messages):
        match = re.search(
            r"(?:下一步|next step|remaining|还需|下一阶段)\s*[:：]?\s*(.{1,240})",
            text,
            re.I,
        )
        if match:
            next_step = match.group(1).strip()
            break
    if not next_step:
        next_step = latest[:240]
    return {
        "session_id": str(row.get("session_id") or ""),
        "title": str(row.get("title") or "")[:120],
        "goal": user_messages[0][:300],
        "latest_state": latest[:360],
        "next_step": next_step[:240],
        "when": str(row.get("when") or row.get("last_active") or ""),
        "match_message_id": int(row.get("match_message_id") or row.get("message_id") or 0),
    }


def resolve_active_workstream(
    user_message: str,
    *,
    user_id: str,
    current_session_id: str = "",
    source: str | None = None,
    db: Any = None,
) -> ActiveWorkstream:
    if not is_bare_continuation(user_message) or not str(user_id or "").strip():
        return ActiveWorkstream(status="unresolved")
    try:
        from tools.session_search_tool import session_search

        raw = session_search(
            query="继续 OR 下一步 OR pending OR remaining OR 未完成",
            limit=5,
            sort="newest",
            db=db,
            current_session_id=current_session_id or None,
            user_id=str(user_id),
            source=source or None,
        )
        payload = json.loads(raw)
    except Exception:
        return ActiveWorkstream(status="unresolved")
    if not payload.get("success", True):
        return ActiveWorkstream(status="unresolved")
    candidates = []
    for row in payload.get("results") or []:
        candidate = _candidate_from_result(row)
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return ActiveWorkstream(status="unresolved")
    # session_search newest ordering is authoritative. Minute-level display time
    # may tie for distinct messages, so use the user-scoped DB message id as a
    # monotonic tie-breaker. Refuse only when both recency signals are identical.
    if (
        len(candidates) > 1
        and candidates[0].get("when") == candidates[1].get("when")
        and candidates[0].get("match_message_id") == candidates[1].get("match_message_id")
    ):
        return ActiveWorkstream(status="ambiguous", candidate_count=len(candidates), confidence=0.45)
    top = candidates[0]
    return ActiveWorkstream(
        status="resolved",
        session_id=top["session_id"],
        title=top["title"],
        goal=top["goal"],
        latest_state=top["latest_state"],
        next_step=top["next_step"],
        confidence=0.86,
        candidate_count=len(candidates),
    )


__all__ = ["ActiveWorkstream", "is_bare_continuation", "resolve_active_workstream"]
