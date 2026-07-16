"""Bounded same-turn continuation for explicitly persistent user goals."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable


_PERSISTENT_GOAL_RE = re.compile(
    r"(?:推进|做到|完成|修到|跑到|达到).{0,20}(?:100\s*%|百分之百|全部|彻底|完成)"
    r"|(?:不要|别|不许).{0,12}(?:停|中途停|只汇报)"
    r"|(?:until|through to).{0,30}(?:complete|done|100\s*%)"
    r"|(?:finish|complete).{0,20}(?:the job|everything|all|100\s*%)",
    re.I | re.S,
)
_UNFINISHED_RE = re.compile(
    r"未完成|尚未完成|还没完成|仍未|还需|剩余|下一步|下一阶段|继续推进"
    r"|pending|in[_ -]?progress|remaining|next step|not (?:yet )?(?:done|complete)"
    r"|\b(?:[1-9]|[1-8]\d|9\d)\s*%\b",
    re.I,
)
_WAITING_RE = re.compile(
    r"等待用户|需要你(?:提供|选择|确认|决定)|请(?:提供|选择|确认)|无法继续.*(?:缺少|需要)"
    r"|waiting (?:for|on) (?:the )?user|need (?:your|user) (?:input|approval|decision)"
    r"|rate.?limit|限流|额度限制|等待.{0,20}(?:进程|任务|构建|部署|审核|响应)",
    re.I | re.S,
)
_TERMINAL_BLOCK_RE = re.compile(
    r"不可实现|无法实现|终止性阻塞|terminal blocker|unachievable",
    re.I,
)


def progress_fingerprint(
    messages: Iterable[dict[str, Any]], changed_paths: Iterable[str]
) -> tuple[int, tuple[str, ...]]:
    """Return a cheap evidence fingerprint for no-progress loop detection."""
    tool_results = sum(
        1 for message in messages if isinstance(message, dict) and message.get("role") == "tool"
    )
    return tool_results, tuple(sorted({str(path) for path in changed_paths if path}))


def build_progress_completion_nudge(
    *,
    user_message: str,
    final_response: str,
    active_todos: Iterable[dict[str, Any]] = (),
    attempts: int = 0,
    max_attempts: int = 3,
    current_fingerprint: tuple[int, tuple[str, ...]] | None = None,
    previous_fingerprint: tuple[int, tuple[str, ...]] | None = None,
) -> str | None:
    """Continue an explicit finish-to-100% goal when the candidate answer stops early."""
    if attempts >= max(0, max_attempts) or not _PERSISTENT_GOAL_RE.search(user_message or ""):
        return None

    response = str(final_response or "").strip()
    if not response or _WAITING_RE.search(response) or _TERMINAL_BLOCK_RE.search(response):
        return None

    todo_items = [item for item in active_todos if isinstance(item, dict)]
    has_active_todos = any(
        str(item.get("status") or "").lower() in {"pending", "in_progress"}
        for item in todo_items
    )
    if not has_active_todos and not _UNFINISHED_RE.search(response):
        return None

    if attempts > 0 and current_fingerprint == previous_fingerprint:
        return None

    return (
        "[System: The user explicitly required this work to continue until it is fully "
        "complete. Your candidate response reports progress but leaves actionable work "
        "unfinished. Do not send another progress-only final answer. Execute the next "
        "concrete step now using tools. Stop only when the acceptance criteria are "
        "verified, user input or an external wait is genuinely required, a terminal "
        "blocker is evidenced, or the bounded continuation guard refuses another loop.]"
    )


def persistent_goal_requested(user_message: str) -> bool:
    return bool(_PERSISTENT_GOAL_RE.search(user_message or ""))


def completion_checkpoint_status(
    *, user_message: str, final_response: str,
    active_todos: Iterable[dict[str, Any]] = (),
) -> str:
    if not persistent_goal_requested(user_message):
        return "irrelevant"
    response = str(final_response or "")
    if _WAITING_RE.search(response):
        return "waiting"
    if _TERMINAL_BLOCK_RE.search(response):
        return "terminal_blocked"
    active = any(
        isinstance(item, dict)
        and str(item.get("status") or "").lower() in {"pending", "in_progress"}
        for item in active_todos
    )
    return "stalled_incomplete" if active or _UNFINISHED_RE.search(response) else "completed"


def update_completion_checkpoint(
    *, session_id: str, user_message: str, final_response: str,
    active_todos: Iterable[dict[str, Any]] = (), attempts: int = 0,
    fingerprint: tuple[int, tuple[str, ...]] | None = None,
) -> str:
    """Persist the explicit state contract consumed by the zero-model watchdog."""
    status = completion_checkpoint_status(
        user_message=user_message,
        final_response=final_response,
        active_todos=active_todos,
    )
    if status == "irrelevant" or not session_id:
        return status
    try:
        from hermes_constants import get_hermes_home
        root = Path(get_hermes_home()) / "runtime" / "continuations"
    except Exception:
        root = Path.home() / ".hermes" / "runtime" / "continuations"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    path = root / f"{session_id}.json"
    if status == "completed":
        path.unlink(missing_ok=True)
        return status
    payload = {
        "schema_version": 1,
        "session_id": session_id,
        "status": status,
        "updated_at": time.time(),
        "nudge_count": max(0, int(attempts)),
        "max_nudges": 3,
        "fingerprint": list(fingerprint or (0, ())),
        "next_prompt": (
            "[Automatic continuation] Resume the existing goal from its latest verified "
            "state. Execute the next concrete step now. Do not stop at a progress report; "
            "continue until verified complete, genuinely waiting, or terminally blocked."
        ),
    }
    fd, tmp_name = tempfile.mkstemp(prefix=f".{session_id}.", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return status


def touch_running_checkpoint(*, session_id: str, user_message: str) -> bool:
    """Create or refresh a running marker for an explicit persistent goal."""
    if not session_id or not persistent_goal_requested(user_message):
        return False
    try:
        from hermes_constants import get_hermes_home
        root = Path(get_hermes_home()) / "runtime" / "continuations"
    except Exception:
        root = Path.home() / ".hermes" / "runtime" / "continuations"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / f"{session_id}.json"
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    payload.update({
        "schema_version": 1,
        "session_id": session_id,
        "status": "running",
        "updated_at": time.time(),
        "nudge_count": max(0, int(payload.get("nudge_count") or 0)),
        "max_nudges": 3,
        "next_prompt": (
            "[Automatic continuation] Resume the existing goal from its latest verified "
            "state. Execute the next concrete step now. Do not stop at a progress report; "
            "continue until verified complete, genuinely waiting, or terminally blocked."
        ),
    })
    fd, tmp_name = tempfile.mkstemp(prefix=f".{session_id}.", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return True


__all__ = [
    "build_progress_completion_nudge", "completion_checkpoint_status",
    "persistent_goal_requested", "progress_fingerprint", "touch_running_checkpoint",
    "update_completion_checkpoint",
]