#!/usr/bin/env python3
"""Backfill readback queries for existing Memory OS ReviewProposal JSONL rows.

This script does not approve, reject, or write Memory Graph. It only fills empty
candidate/readback query fields so each pending proposal has future-phrased
queries available for approval-time verification.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def candidate_kind(row: Dict[str, Any]) -> str:
    c = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
    return str(c.get("kind") or row.get("memory_type") or row.get("kind") or "unknown")


def target_path(row: Dict[str, Any]) -> str:
    c = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
    cs = row.get("changeset") if isinstance(row.get("changeset"), dict) else {}
    return str(c.get("target_path") or row.get("target_path") or cs.get("target_path_uri") or "待审核")


def content_text(row: Dict[str, Any]) -> str:
    c = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
    return clean(
        c.get("content")
        or c.get("evidence_quote")
        or row.get("content_preview")
        or row.get("evidence_preview")
        or row.get("evidence_quote")
        or ""
    )


def generate_queries(kind: str, text: str, path: str) -> List[str]:
    snippets: List[str] = []
    text = clean(text)
    path = clean(path).replace("core://", "")
    if text and not text.startswith("[redacted:"):
        snippets.append(text[:80])
    if path:
        snippets.append(path.replace("/待审核", ""))

    if kind == "explicit_correction":
        snippets.extend([
            "用户之前纠正过我什么错误？",
            "遇到类似任务前需要避免复发的纠错是什么？",
            "what correction should I recall before repeating this mistake?",
        ])
    elif kind in {"explicit_preference", "creative_preference"}:
        snippets.extend([
            "用户长期偏好是什么？",
            "这类任务开始前应该召回哪些用户偏好？",
            "what user preference should guide this task?",
        ])
    elif kind in {"rule", "procedural_memory", "target_function", "correction_learning_event"}:
        snippets.extend([
            "输出前有哪些硬约束和 reject gate？",
            "做类似任务前需要召回哪些流程规则？",
            "what target function or rule should guide this task?",
        ])
    elif kind in {"project_fact", "project_identity_verification"}:
        snippets.extend([
            "这个项目当前状态和技术事实是什么？",
            "继续做这个项目之前应该召回哪些项目记忆？",
            "what project facts are current?",
        ])
    elif kind in {"user_fact", "exam_context"}:
        snippets.extend([
            "关于用户的长期背景事实是什么？",
            "回答前需要召回哪些用户上下文？",
            "what stable user context matters here?",
        ])
    elif kind == "lesson":
        snippets.extend([
            "之前踩过什么坑，如何防复发？",
            "做类似任务前需要召回哪些经验教训？",
            "what lesson prevents this failure from recurring?",
        ])
    else:
        snippets.extend([
            "这条记忆未来应该怎样被召回？",
            "做相似任务前需要召回什么上下文？",
            "what should I recall for a similar future task?",
        ])

    out: List[str] = []
    seen = set()
    for item in snippets:
        item = clean(item)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item[:160])
        if len(out) >= 5:
            break
    return out


def has_queries(row: Dict[str, Any]) -> bool:
    c = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
    rb = row.get("readback") if isinstance(row.get("readback"), dict) else {}
    return bool(c.get("readback_queries") or rb.get("queries") or row.get("readback_queries"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default=str(Path.home() / ".hermes" / "logs" / "memory_review_queue" / "review_proposals.current.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    queue = Path(args.queue)
    rows: List[Dict[str, Any]] = []
    for line in queue.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))

    changed = 0
    still_empty = 0
    for row in rows:
        if has_queries(row):
            continue
        queries = generate_queries(candidate_kind(row), content_text(row), target_path(row))
        if not queries:
            still_empty += 1
            continue
        row.setdefault("candidate", {})["readback_queries"] = queries
        rb = row.setdefault("readback", {})
        rb["queries"] = queries
        rb.setdefault("ok", False)
        rb.setdefault("reason", "not written yet")
        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        changed += 1

    backup = ""
    if changed and not args.dry_run:
        backup = str(queue.with_suffix(queue.suffix + f".bak_readback_{datetime.now().strftime('%Y%m%d_%H%M%S')}"))
        shutil.copy2(queue, backup)
        with queue.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps({
        "queue": str(queue),
        "rows": len(rows),
        "changed": changed,
        "still_empty": still_empty,
        "dry_run": args.dry_run,
        "backup": backup,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
