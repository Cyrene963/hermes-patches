#!/usr/bin/env python3
"""Build a private turn-level search index for AI Studio/Gemini history.

This index preserves speaker roles. Runtime proactive recall reads only role=user;
model turns remain evidence material and are never presented as user facts.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path


def chmod_private(path: Path) -> None:
    try:
        path.chmod(0o600)
    except FileNotFoundError:
        pass


def rebuild(turns_path: Path, db_path: Path) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(db_path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(str(tmp))
    conn.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE turns (
            id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL, conversation_name TEXT,
            turn_index INTEGER, role TEXT NOT NULL, text TEXT NOT NULL, create_time TEXT,
            modified_time TEXT, archive_path TEXT, web_view_link TEXT, model TEXT,
            thinking_like INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_turns_role ON turns(role);
        CREATE INDEX idx_turns_conversation ON turns(conversation_id, turn_index);
        CREATE VIRTUAL TABLE turns_fts USING fts5(
            conversation_name, text, content='turns', content_rowid='id', tokenize='unicode61'
        );
    """)
    inserted = user_turns = model_turns = 0
    with turns_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            role = str(row.get("role") or "unknown")
            conn.execute(
                """INSERT INTO turns
                (conversation_id,conversation_name,turn_index,role,text,create_time,modified_time,
                 archive_path,web_view_link,model,thinking_like) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (str(row.get("conversation_id") or ""), str(row.get("conversation_name") or ""),
                 int(row.get("turn_index") or 0), role, str(row.get("text") or ""),
                 str(row.get("createTime") or ""), str(row.get("modifiedTime") or ""),
                 str(row.get("archive_path") or ""), str(row.get("webViewLink") or ""),
                 str(row.get("model") or ""), 1 if row.get("thinking_like") else 0),
            )
            inserted += 1
            user_turns += role == "user"
            model_turns += role == "model"
    conn.execute("INSERT INTO turns_fts(rowid,conversation_name,text) SELECT id,conversation_name,text FROM turns")
    conn.commit(); conn.close(); tmp.replace(db_path); chmod_private(db_path)
    return {"turns": inserted, "user_turns": user_turns, "model_turns": model_turns, "db": str(db_path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=Path, required=True)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--report-dir", type=Path)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if not args.turns.exists():
        raise SystemExit(f"missing turns: {args.turns}")
    report = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **rebuild(args.turns, args.db)}
    if args.report_dir:
        args.report_dir.mkdir(parents=True, exist_ok=True)
        rp = args.report_dir / f"turn-index-report-{time.strftime('%Y%m%d_%H%M%S')}.json"
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"); chmod_private(rp)
    if not args.quiet:
        print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
