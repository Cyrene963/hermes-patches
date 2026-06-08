#!/usr/bin/env python3
"""Build Memory OS backfill review proposals from local evidence.

Read-only sources:
- ~/.hermes/state.db messages/sessions
- ~/.hermes/logs/shadow_writes/*.jsonl

Output:
- JSONL proposals for human/UI approval before any Memory Graph write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_|xox[baprs]-|AKIA[0-9A-Z]{16}|token\s*[:=]|api[_ -]?key\s*[:=]|BEGIN [A-Z ]*PRIVATE KEY)",
    re.I,
)
NOISE_RE = re.compile(
    r"(tool_calls|<available_skills>|AGENTS\.md|Traceback|```|^\s*\{.*\}\s*$|browser_|terminal\(|execute_code|apply_patch)",
    re.I | re.S,
)
WRAPPER_PREFIX_RE = re.compile(
    r'^(\[(?:System note|Note):.*?\]\s*)+',
    re.I | re.S,
)
IMPORTANT_RE = re.compile(
    r"(记住|remember|以后|以后.*(不要|必须|优先)|不要|别|禁止|必须|偏好|喜欢|讨厌|更关心|更喜欢|纠正|不是.*是|改成|换成|现在用|决定|规则|原则|教训|踩坑|发现|家庭|学校|DSE|mock|成绩|分数|项目|部署|配置|技术栈|数据库|端口|隐私|namespace|Memory Graph|Hindsight|Hermes)",
    re.I,
)
TYPE_RULES: List[Tuple[str, re.Pattern[str]]] = [
    ("explicit_correction", re.compile(r"(不是.*是|纠正|改成|换成|应该是|更正)", re.I)),
    ("explicit_preference", re.compile(r"(偏好|喜欢|讨厌|更关心|更喜欢|不要.*AI味|优先)", re.I)),
    ("rule", re.compile(r"(以后|不要|别|禁止|必须|一定要|规则|原则|格式)", re.I)),
    ("project_fact", re.compile(r"(项目|部署|配置|技术栈|数据库|端口|架构|服务器|Next\.js|PostgreSQL|SQLite)", re.I)),
    ("user_fact", re.compile(r"(家庭|学校|DSE|mock|成绩|分数|年龄|JUPAS|奖学金)", re.I)),
    ("lesson", re.compile(r"(教训|踩坑|发现|原来|避免|下次)", re.I)),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_user_text(text: str) -> str:
    text = text or ""
    previous = None
    while previous != text:
        previous = text
        text = WRAPPER_PREFIX_RE.sub("", text).strip()
        if text.startswith('[Replying to:'):
            marker = '"]'
            end = text.find(marker)
            if end != -1:
                text = text[end + len(marker):].strip()
    return text


def preview(text: str, limit: int = 900) -> Tuple[str, bool]:
    text = re.sub(r"\s+", " ", clean_user_text(text)).strip()
    secret = bool(SECRET_RE.search(text))
    if secret:
        return "[redacted: secret-like content]", True
    return text[:limit], False


def classify(text: str) -> Tuple[str, float, str]:
    for memory_type, pattern in TYPE_RULES:
        if pattern.search(text):
            if memory_type == "explicit_correction":
                return memory_type, 0.96, "review"
            if memory_type in {"explicit_preference", "rule"}:
                return memory_type, 0.92, "review"
            if memory_type in {"project_fact", "user_fact"}:
                return memory_type, 0.88, "review"
            return memory_type, 0.86, "review"
    return "unknown", 0.0, "ignore"


def target_path(memory_type: str, text: str) -> str:
    if memory_type in {"explicit_preference", "user_fact"}:
        return "用户档案/待审核"
    if memory_type == "rule":
        return "用户档案/规则偏好/待审核"
    if memory_type == "project_fact":
        return "项目/待审核"
    if memory_type == "explicit_correction":
        return "用户档案/纠正/待审核"
    if memory_type == "lesson":
        return "经验教训/待审核"
    return "待审核"


def generate_readback_queries(memory_type: str, text: str, path: str) -> List[str]:
    """Generate future-phrased queries that must recover an approved memory."""
    text = re.sub(r"\s+", " ", clean_user_text(text)).strip()
    path = str(path or "待审核").strip()
    snippets: List[str] = []
    if text:
        snippets.append(text[:80])
    if path:
        snippets.append(path.replace("/待审核", ""))

    if memory_type == "explicit_correction":
        snippets.extend([
            "用户之前纠正过我什么错误？",
            "遇到类似任务前需要避免复发的纠错是什么？",
            "what correction should I recall before repeating this mistake?",
        ])
    elif memory_type == "explicit_preference":
        snippets.extend([
            "用户长期偏好是什么？",
            "这类任务开始前应该召回哪些用户偏好？",
            "what user preference should guide this task?",
        ])
    elif memory_type == "rule":
        snippets.extend([
            "用户给过哪些必须遵守的规则？",
            "输出前有哪些硬约束和 reject gate？",
            "what rule must I follow before answering?",
        ])
    elif memory_type == "project_fact":
        snippets.extend([
            "这个项目当前状态和技术事实是什么？",
            "继续做这个项目之前应该召回哪些项目记忆？",
            "what project facts are current?",
        ])
    elif memory_type == "user_fact":
        snippets.extend([
            "关于用户的长期背景事实是什么？",
            "回答前需要召回哪些用户上下文？",
            "what stable user context matters here?",
        ])
    elif memory_type == "lesson":
        snippets.extend([
            "之前踩过什么坑，如何防复发？",
            "做类似任务前需要召回哪些经验教训？",
            "what lesson prevents this failure from recurring?",
        ])
    else:
        snippets.extend([
            "这条记忆未来应该怎样被召回？",
            "做相似任务前需要召回什么上下文？",
        ])

    queries: List[str] = []
    seen = set()
    for item in snippets:
        item = re.sub(r"\s+", " ", str(item or "")).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        queries.append(item[:160])
        if len(queries) >= 5:
            break
    return queries


def proposal_id(namespace: str, content: str, source: str) -> str:
    return hashlib.sha256(f"{namespace}|{source}|{content}".encode("utf-8", "ignore")).hexdigest()[:24]


def normalize_namespace(source: str, user_id: Optional[str]) -> str:
    user = str(user_id or "").strip()
    if user and user not in {"None", "null"}:
        if source.startswith("telegram") or user.isdigit():
            return f"telegram:{user}"
        return f"{source}:{user}"
    return ""


def iter_state_messages(db_path: Path, since_ts: Optional[float], limit: int) -> Iterable[Dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    where = "m.role='user' AND m.active=1"
    params: List[Any] = []
    if since_ts is not None:
        where += " AND m.timestamp >= ?"
        params.append(since_ts)
    sql = f"""
      SELECT m.id, m.session_id, m.content, m.timestamp, s.source, s.user_id, s.title
      FROM messages m
      JOIN sessions s ON s.id=m.session_id
      WHERE {where}
      ORDER BY m.timestamp DESC
      LIMIT ?
    """
    params.append(limit)
    for row in con.execute(sql, params):
        yield dict(row)


def build_from_state(db_path: Path, since_ts: Optional[float], limit: int, min_importance: float) -> Tuple[List[Dict[str, Any]], Counter[str]]:
    proposals: Dict[str, Dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for row in iter_state_messages(db_path, since_ts, limit):
        text = clean_user_text(str(row.get("content") or ""))
        if len(text) < 8:
            counts["skip_too_short"] += 1
            continue
        if len(text) > 4000 or NOISE_RE.search(text):
            counts["skip_noise_or_tool"] += 1
            continue
        if not IMPORTANT_RE.search(text):
            counts["skip_not_important"] += 1
            continue
        memory_type, importance, target_store = classify(text)
        if importance < min_importance:
            counts["skip_low_importance"] += 1
            continue
        namespace = normalize_namespace(str(row.get("source") or ""), row.get("user_id"))
        if not namespace:
            counts["skip_no_namespace"] += 1
            continue
        content_preview, redacted = preview(text)
        pid = proposal_id(namespace, text, f"state:{row.get('id')}")
        path = target_path(memory_type, text)
        readback_queries = generate_readback_queries(memory_type, text, path)
        proposals[pid] = {
            "proposal_id": pid,
            "status": "pending_review",
            "created_at": now_iso(),
            "namespace": namespace,
            "memory_type": memory_type,
            "importance": importance,
            "confidence": 0.70,
            "target_store": target_store,
            "target_path": path,
            "requires_review": True,
            "content_preview": content_preview,
            "evidence_preview": content_preview,
            "redacted": redacted,
            "value_sha256": hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest(),
            "source": {
                "kind": "state_db_message",
                "message_id": row.get("id"),
                "session_id": row.get("session_id"),
                "session_title": row.get("title") or "",
                "timestamp": row.get("timestamp"),
                "source": row.get("source") or "",
                "user_id": row.get("user_id") or "",
            },
            "readback_queries": readback_queries,
            "actually_written": False,
            "readback_ok": False,
        }
        counts["state_candidate"] += 1
    return list(proposals.values()), counts


def iter_shadow(log_dir: Path) -> Iterable[Tuple[Path, int, Dict[str, Any]]]:
    for path in sorted(log_dir.glob("shadow_*.jsonl")):
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_no, line in enumerate(handle, 1):
                try:
                    yield path, line_no, json.loads(line)
                except Exception:
                    continue


def build_from_shadow(log_dir: Path, min_importance: float) -> Tuple[List[Dict[str, Any]], Counter[str]]:
    proposals: Dict[str, Dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for path, line_no, entry in iter_shadow(log_dir):
        namespace = str(entry.get("namespace") or "")
        if not namespace or namespace in {"telegram:u1", "telegram:u2", "test"}:
            counts["shadow_skip_no_or_test_namespace"] += 1
            continue
        for candidate in entry.get("candidates") or []:
            try:
                importance = float(candidate.get("importance") or 0)
            except Exception:
                importance = 0.0
            if importance < min_importance:
                counts["shadow_skip_low_importance"] += 1
                continue
            raw_content = str(candidate.get("object_value") or entry.get("user_message") or "")
            content_preview, redacted = preview(raw_content)
            pid = proposal_id(namespace, raw_content, f"shadow:{path.name}:{line_no}")
            proposals[pid] = {
                "proposal_id": pid,
                "status": "pending_review",
                "created_at": now_iso(),
                "namespace": namespace,
                "memory_type": candidate.get("memory_type") or "unknown",
                "importance": importance,
                "confidence": float(candidate.get("confidence") or 0.70),
                "target_store": candidate.get("target_store") or "review",
                "target_path": candidate.get("target_path") or "待审核",
                "requires_review": True,
                "content_preview": content_preview,
                "evidence_preview": preview(str(entry.get("user_message") or ""))[0],
                "redacted": redacted,
                "value_sha256": hashlib.sha256(raw_content.encode("utf-8", "ignore")).hexdigest(),
                "source": {"kind": "shadow_log", "file": str(path), "line": line_no},
                "readback_queries": candidate.get("readback_queries") or [],
                "actually_written": bool(candidate.get("actually_written")),
                "readback_ok": bool(candidate.get("readback_ok")),
            }
            counts["shadow_candidate"] += 1
    return list(proposals.values()), counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-db", default=str(Path.home() / ".hermes" / "state.db"))
    parser.add_argument("--shadow-dir", default=str(Path.home() / ".hermes" / "logs" / "shadow_writes"))
    parser.add_argument("--output", default=str(Path.home() / ".hermes" / "logs" / "memory_review_queue" / "backfill_proposals.current.jsonl"))
    parser.add_argument("--summary", default=str(Path.home() / ".hermes" / "logs" / "memory_review_queue" / "backfill_proposals.summary.json"))
    parser.add_argument("--min-importance", type=float, default=0.85)
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument("--since-unix", type=float, default=None)
    args = parser.parse_args()

    state_props, state_counts = build_from_state(Path(args.state_db), args.since_unix, args.limit, args.min_importance)
    shadow_props, shadow_counts = build_from_shadow(Path(args.shadow_dir), args.min_importance)
    merged: Dict[str, Dict[str, Any]] = {}
    for proposal in state_props + shadow_props:
        key = f"{proposal['namespace']}|{proposal['value_sha256']}"
        if key not in merged:
            merged[key] = proposal
    proposals = sorted(merged.values(), key=lambda p: (-float(p.get("importance") or 0), p.get("namespace", ""), p.get("proposal_id", "")))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for proposal in proposals:
            handle.write(json.dumps(proposal, ensure_ascii=False) + "\n")
    summary = {
        "generated_at": now_iso(),
        "state_db": args.state_db,
        "shadow_dir": args.shadow_dir,
        "min_importance": args.min_importance,
        "limit": args.limit,
        "proposal_count": len(proposals),
        "counts": dict(state_counts + shadow_counts),
        "output": str(out),
    }
    Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
