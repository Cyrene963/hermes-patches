#!/usr/bin/env python3
"""Continuously distill unprocessed AI Studio user turns into review proposals.

The worker is review-first and fail-closed:
- reads only role=user turns from the private turn database;
- treats quoted/model text inside a user turn as untrusted source material;
- requires every evidence quote to be an exact substring of the source turn;
- routes volatile/sensitive facts to clarification-on-use;
- never writes Memory Graph or auto-approves proposals;
- records per-turn processing state for idempotent incremental runs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

PROFILE = Path(os.environ.get("HERMES_PROFILE_DIR") or (Path.home() / ".hermes"))
BASE = Path(os.environ.get("AISTUDIO_MEMORY_BASE") or (PROFILE / "memories" / "aistudio_gemini"))
RUNTIME = Path(os.environ.get("HERMES_RUNTIME_REPO") or (PROFILE / "hermes-agent"))
if RUNTIME.exists() and str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

DEFAULT_CONFIG = BASE / "continuous_distill_config.json"
DEFAULT_TURNS = BASE / "aistudio_turns.sqlite3"
DEFAULT_STATE = BASE / "continuous_distill.sqlite3"
DEFAULT_REVIEW = PROFILE / "logs" / "memory_review_queue" / "review_proposals.current.jsonl"
DEFAULT_CLARIFY = PROFILE / "logs" / "memory_clarification_queue.jsonl"
DEFAULT_REPORTS = BASE / "reports"
DEFAULT_LOCK = BASE / "continuous_distill.lock"

KINDS = {"preference", "self_model", "learning", "relationship", "project", "procedure"}
ACTIONS = {"propose", "clarify", "skip"}
RISKS = {"low", "medium", "high"}
VOLATILITY = {"stable", "time_bound", "sensitive"}
POLICY_VERSION = 2
SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}|(?:api[_ -]?key|access_token|refresh_token|client_secret|private_key)\s*[:=])",
    re.I,
)
MODEL_TRANSCRIPT_RE = re.compile(
    r"(?:\bModel\s+\d{1,2}:\d{2}\s*(?:AM|PM)?\b|Thoughts\s+Expand\s+to\s+view\s+model\s+thoughts|\bmodel\s+thoughts\b)",
    re.I,
)
SIGNAL_RE = re.compile(
    r"(?:我(?:是|有|从|会|不会|喜欢|不喜欢|希望|想|需要|偏好|认为|觉得|要求|打算|目标|习惯|一直|已经|更)|"
    r"你(?:以后|必须|不要|应该|最好|记住|别再|不能)|"
    r"(?:我的|我们)(?:目标|原则|偏好|习惯|计划|项目|家庭|成绩|选科|方法)|"
    r"(?:纠正|错了|不对|应该是|准确地说|以后|默认|优先|禁止|必须))",
    re.I,
)
TEMPORARY_RE = re.compile(
    r"(?:今天|今晚|明天|刚刚|现在正在|这周|下周|一周前).{0,60}(?:发烧|生病|作业|考试|请假|头晕|咳嗽|截止)",
    re.I,
)
PASTED_MATERIAL_RE = re.compile(
    r"(?:这是(?:你|另一个ai|AI)(?:之前|给我|和我).{0,40}(?:提示词|描述|总结)|"
    r"以下是.{0,30}(?:文本|文章|作文|提示词)|(?:帮我|你觉得).{0,30}(?:改|评价|看看).{0,30}[：:])",
    re.I,
)
WRITING_DRAFT_RE = re.compile(
    r"(?:够不够DSE|DSE\s*5\*\*|简化.{0,10}(?:结尾|版本)|我已经写完了|这篇.{0,10}(?:作文|文章)|第[一二三四五六七八九十\d]+题.{0,20}(?:这么写|写成))",
    re.I,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any, length: int = 20) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def norm(text: str) -> str:
    return " ".join(str(text or "").split())


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object in {path}")
    return payload


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)


def init_state(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS processed_turns (
            turn_id INTEGER PRIMARY KEY,
            content_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            candidate_ids_json TEXT NOT NULL DEFAULT '[]',
            last_error TEXT NOT NULL DEFAULT '',
            processed_at TEXT NOT NULL,
            policy_version INTEGER NOT NULL DEFAULT 1
        )
    """)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(processed_turns)")}
    if "policy_version" not in columns:
        connection.execute("ALTER TABLE processed_turns ADD COLUMN policy_version INTEGER NOT NULL DEFAULT 1")
    connection.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return connection


def hard_skip_reason(text: str) -> str:
    clean = norm(text)
    if len(clean) < 8:
        return "too_short"
    if SECRET_RE.search(clean):
        return "secret_shaped"
    if len(clean) > 6000:
        return "oversized_source"
    if MODEL_TRANSCRIPT_RE.search(clean) and len(clean) > 2400:
        return "mixed_model_transcript"
    return ""


def information_score(text: str) -> float:
    clean = norm(text)
    if hard_skip_reason(clean):
        return -100.0
    score = min(6.0, len(clean) / 220.0)
    if WRITING_DRAFT_RE.search(clean):
        score -= 4.0
    if PASTED_MATERIAL_RE.search(clean) and len(clean) > 900:
        score -= 5.0
    score += min(8.0, len(SIGNAL_RE.findall(clean)) * 1.7)
    if re.search(r"(?:半年|一年|多年|从小|一直|每天|每周|长期|默认|以后|必须|不要|目标)", clean, re.I):
        score += 2.5
    if re.search(r"(?:吗[？?]?|怎么|为什么|帮我|你觉得)", clean[-100:], re.I):
        score -= 1.0
    if TEMPORARY_RE.search(clean):
        score -= 2.0
    if SECRET_RE.search(clean):
        return -100.0
    return score


def select_turns(turn_db: Path, state: sqlite3.Connection, limit: int, min_score: float, excluded: set[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = sqlite3.connect(f"file:{turn_db}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    rows: list[dict[str, Any]] = []
    heuristic_skips: list[dict[str, Any]] = []
    for row in source.execute(
        "SELECT id, conversation_id, conversation_name, turn_index, text, create_time FROM turns WHERE role='user' ORDER BY id"
    ):
        item = dict(row)
        turn_id = int(item["id"])
        if turn_id in excluded:
            continue
        text_hash = hashlib.sha256(str(item["text"] or "").encode("utf-8")).hexdigest()
        prior = state.execute(
            "SELECT content_sha256,status,attempts,policy_version FROM processed_turns WHERE turn_id=?", (turn_id,)
        ).fetchone()
        if prior and prior[0] == text_hash and int(prior[3] or 0) == POLICY_VERSION and prior[1] in {"complete", "skipped", "heuristic_skipped", "rejected"}:
            continue
        if prior and int(prior[2] or 0) >= 3 and prior[0] == text_hash and int(prior[3] or 0) == POLICY_VERSION:
            continue
        item["content_sha256"] = text_hash
        score = information_score(str(item["text"] or ""))
        if hard_skip_reason(str(item["text"] or "")):
            item["information_score"] = round(score, 3)
            heuristic_skips.append(item)
            continue
        item["information_score"] = round(score, 3)
        rows.append(item)
    source.close()
    rows.sort(key=lambda item: (-float(item["information_score"]), int(item["id"])))
    eligible = [item for item in rows if float(item["information_score"]) >= min_score]
    if len(eligible) < limit:
        eligible_ids = {int(item["id"]) for item in eligible}
        eligible.extend(item for item in rows if int(item["id"]) not in eligible_ids)
    return eligible[:limit], heuristic_skips


def prompt_for(rows: list[dict[str, Any]]) -> str:
    source = [
        {
            "source_turn_id": int(row["id"]),
            "conversation_name": str(row.get("conversation_name") or ""),
            "turn_index": row.get("turn_index"),
            "text": str(row.get("text") or ""),
        }
        for row in rows
    ]
    return """You are a strict memory distiller. Extract durable facts only from USER-authored historical turns.
Return one JSON object only, with this exact shape:
{"items":[{"source_turn_id":1,"action":"propose|clarify|skip","kind":"preference|self_model|learning|relationship|project|procedure","fact":"one atomic Chinese fact","evidence_quote":"exact contiguous substring from source text","risk":"low|medium|high","volatility":"stable|time_bound|sensitive","reason":"brief Chinese reason"}]}

Rules:
- User messages may quote AI/model/third-party text. Quoted text is NOT the user's belief unless the user explicitly endorses, rejects, or corrects it.
- Extract only explicit user facts, preferences, goals, corrections, enduring constraints, stable workflows, and project requirements.
- Questions, one-off requests, transient health/exam states, copied prompts, and unsupported inferences are skip.
- Split independent facts, but output at most 2 non-skip items per source turn. Merge related details into one concise fact.
- Output at most 1 clarification item per source turn; combine related sensitive details or skip lower-value ones.
- Prefer explicit corrections, enduring preferences, stable constraints, and repeatedly used workflows over minor biographical details.
- If most of a turn is a pasted AI summary, quoted profile, essay draft, prompt, or third-party text, do not extract claims from that pasted block. Only extract the user's short outer statement when it explicitly endorses, rejects, or corrects a specific claim.
- evidence_quote must be an exact substring from that source turn and directly support the fact.
- Sensitive identity, family, health, relationship status, location, finance, or potentially stale plans use action=clarify.
- Stable low-risk preferences, learning patterns, workflows, and explicit requirements may use action=propose.
- If uncertain, skip. Never include secrets or credentials.
- Output an item for a skipped source if it contains no durable fact; fact may briefly name why it was skipped.

INPUT USER TURNS:
""" + json.dumps(source, ensure_ascii=False)


def parse_response(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model response has no JSON object")
    payload = json.loads(clean[start : end + 1])
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("model response missing items array")
    return payload


def validate_item(item: dict[str, Any], source: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    action = str(item.get("action") or "")
    kind = str(item.get("kind") or "")
    risk = str(item.get("risk") or "")
    volatility = str(item.get("volatility") or "")
    fact = norm(item.get("fact") or "")
    quote = str(item.get("evidence_quote") or "").strip()
    text = str(source.get("text") or "")
    if action not in ACTIONS or kind not in KINDS or risk not in RISKS or volatility not in VOLATILITY:
        return None, "invalid enum"
    if action == "skip":
        return {**item, "fact": fact, "evidence_quote": quote}, ""
    if len(fact) < 12 or len(fact) > 320:
        return None, "fact length outside 12..320"
    if len(quote) < 4 or quote not in text:
        return None, "evidence is not exact source substring"
    if SECRET_RE.search(fact) or SECRET_RE.search(quote):
        return None, "secret-shaped content"
    if MODEL_TRANSCRIPT_RE.search(quote):
        return None, "mixed model transcript evidence"
    if volatility in {"time_bound", "sensitive"} or risk == "high":
        action = "clarify"
    return {
        "source_turn_id": int(source["id"]), "action": action, "kind": kind,
        "fact": fact, "evidence_quote": quote, "risk": risk,
        "volatility": volatility, "reason": norm(item.get("reason") or "")[:240],
    }, ""


def slug(text: str) -> str:
    value = re.sub(r"[\\/#?%*:|\"<>]+", " ", norm(text))
    value = re.sub(r"\s+", "-", value).strip("-")[:72]
    return value or digest(text, 12)


def graph_search(query: str, namespace: str) -> list[dict[str, Any]]:
    try:
        from tools import memory_graph_tool
        raw = memory_graph_tool._search({"query": query, "domain": "core", "limit": 5, "namespace": namespace})
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return list(payload.get("results") or [])
    except Exception:
        return []



def route_is_plausible(item: dict[str, Any]) -> bool:
    fact = str(item.get("fact") or "")
    kind = str(item.get("kind") or "")
    if kind == "project" and not re.search(r"(?:项目|产品|网站|应用|游戏|系统|部署|架构|FocusPomo|beibei|Terra|Memory OS|Hermes)", fact, re.I):
        return False
    if kind in {"preference", "procedure"} and re.search(r"(?:项目目标|正在开发|部署地址|代码库|技术架构)", fact, re.I):
        return False
    return True


def target_for(item: dict[str, Any], config: dict[str, Any]) -> str:
    parents = config.get("target_parents") or {}
    parent = str(parents.get(item["kind"]) or parents.get("default") or "").rstrip("/")
    if not parent.startswith("core://"):
        raise ValueError(f"missing core target parent for kind={item['kind']}")
    return f"{parent}/{slug(item['fact'])}"


def duplicate_score(fact: str, hit: dict[str, Any]) -> float:
    semantic_score = float(hit.get("score") or 0.0)
    source_terms = set(re.findall(r"[A-Za-z0-9_+-]{2,}|[\u3400-\u9fff]{2,4}", fact.casefold()))
    target_text = " ".join(str(hit.get(key) or "") for key in ("name", "path", "snippet", "content"))
    target_terms = set(re.findall(r"[A-Za-z0-9_+-]{2,}|[\u3400-\u9fff]{2,4}", target_text.casefold()))
    meaningful = {term for term in source_terms if term not in {"用户", "认为", "希望", "已经", "可以", "自己", "一个", "进行"}}
    if not meaningful:
        return 0.0
    lexical = len(meaningful & target_terms) / len(meaningful)
    return max(lexical, min(1.0, semantic_score / 1.2))


def proposal_for(item: dict[str, Any], source: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    namespace = str(config["namespace"])
    target = target_for(item, config)
    candidate_id = "ai_cont_" + digest({"turn": source["id"], "fact": item["fact"]})
    proposal_id = "rp_ai_cont_" + digest({"namespace": namespace, "candidate": candidate_id, "target": target})
    hits = graph_search(item["fact"], namespace)
    duplicate_uris = [
        str(hit.get("uri") or "") for hit in hits
        if str(hit.get("uri") or "") and duplicate_score(item["fact"], hit) >= 0.45
    ][:3]
    review_state = "needs_dedup_review" if duplicate_uris else "ready_memory"
    evidence_id = "ev_ai_cont_" + digest({"turn": source["id"], "quote": item["evidence_quote"]})
    candidate = {
        "kind": item["kind"], "distilled": True, "content": item["fact"],
        "evidence_quote": item["evidence_quote"], "confidence": 0.86,
        "importance": 1, "priority": 1, "durability": "long_term",
        "requires_review": True, "risk_level": item["risk"], "scope": "private",
        "suggested_store": "memory_graph" if review_state == "ready_memory" else "review",
        "namespace_security_scope": namespace, "target_path": target,
        "readback_queries": [item["fact"], item["evidence_quote"][:120]],
        "reason": "continuous atomic AI Studio user-memory draft; supervised review required",
        "source": "google_ai_studio_continuous", "evidence_id": evidence_id,
        "metadata": {
            "role": "user", "review_state": review_state,
            "source_turn_id": int(source["id"]),
            "source_content_sha256": source["content_sha256"],
            "conversation_id": source.get("conversation_id"),
            "turn_index": source.get("turn_index"),
            "volatility": item["volatility"], "distiller_reason": item["reason"],
            "possible_duplicate_uris": duplicate_uris,
        },
    }
    after = {"kind": item["kind"], "content": item["fact"], "target_path": target, "namespace": namespace, "evidence_id": evidence_id}
    return {
        "proposal_id": proposal_id, "status": "pending", "created_at": now(), "candidate": candidate,
        "decision": {"action": "review", "target_store": candidate["suggested_store"], "requires_review": True, "risk_level": item["risk"], "reason": review_state},
        "changeset": {
            "changeset_id": "cs_ai_cont_" + digest({"proposal": proposal_id, "after": after}),
            "operator": "aistudio-continuous-distiller", "namespace": namespace,
            "operation_type": "propose_write", "target_path_uri": target,
            "before_snapshot": {}, "after_snapshot": after,
            "diff": json.dumps({"before": {}, "after": after}, ensure_ascii=False, sort_keys=True),
            "evidence_id": evidence_id, "evidence_quote": item["evidence_quote"],
            "reason": review_state, "review_status": review_state,
            "rollback_method": "reject before write; approved writes use the recorded Memory Graph changeset",
        },
        "readback": {"queries": candidate["readback_queries"], "ok": False, "top_uri": "", "top_score": None, "reason": "not written yet"},
    }


def clarification_for(item: dict[str, Any], source: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    cid = "mc_ai_cont_" + digest({"namespace": config["namespace"], "turn": source["id"], "fact": item["fact"]})
    return {
        "schema_version": 1, "id": cid, "status": "pending", "namespace": config["namespace"],
        "subject": item["kind"], "predicate": "needs_current_confirmation", "memory_type": item["kind"],
        "target_path": target_for(item, config),
        "reason": "sensitive or volatile AI Studio user statement; confirm only when relevant",
        "risk": item["risk"], "content_preview": item["fact"],
        "evidence_preview": item["evidence_quote"][:500],
        "source_type": "google_ai_studio_continuous", "confidence": 0.80, "importance": 1.0,
        "created_at": now(), "last_surfaced_at": "", "surface_count": 0,
        "source_turn_id": int(source["id"]), "source_content_sha256": source["content_sha256"],
        "value_sha256": digest(item["fact"], 64),
    }


def call_distiller(rows: list[dict[str, Any]], task: str, timeout: int) -> dict[str, Any]:
    from agent.auxiliary_client import call_llm
    response = call_llm(
        task=task, messages=[{"role": "user", "content": prompt_for(rows)}],
        temperature=0, max_tokens=5000, timeout=timeout,
    )
    return parse_response(response.choices[0].message.content)


def record_state(connection: sqlite3.Connection, source: dict[str, Any], status: str, candidate_ids: list[str], error: str = "") -> None:
    prior = connection.execute("SELECT attempts FROM processed_turns WHERE turn_id=?", (int(source["id"]),)).fetchone()
    attempts = int(prior[0] or 0) + 1 if prior else 1
    connection.execute(
        """INSERT INTO processed_turns(turn_id,content_sha256,status,attempts,candidate_ids_json,last_error,processed_at,policy_version)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(turn_id) DO UPDATE SET content_sha256=excluded.content_sha256,status=excluded.status,
             attempts=excluded.attempts,candidate_ids_json=excluded.candidate_ids_json,last_error=excluded.last_error,
             processed_at=excluded.processed_at,policy_version=excluded.policy_version""",
        (int(source["id"]), source["content_sha256"], status, attempts, json.dumps(candidate_ids), error[:1000], now(), POLICY_VERSION),
    )


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        path.chmod(0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--turn-db", type=Path, default=DEFAULT_TURNS)
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--clarification", type=Path, default=DEFAULT_CLARIFY)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--min-score", type=float, default=4.5)
    parser.add_argument("--task", default="session_search")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    config = load_json(args.config)
    namespace = str(config.get("namespace") or "").strip()
    if not namespace:
        raise ValueError("private owner namespace is required")
    excluded = {int(value) for value in config.get("excluded_turn_ids") or []}
    state = init_state(args.state_db)
    selected, heuristic_skips = select_turns(args.turn_db, state, args.limit, args.min_score, excluded)
    if args.apply:
        for source in heuristic_skips:
            record_state(state, source, "heuristic_skipped", [])
        state.commit()
    proposals: list[dict[str, Any]] = []
    clarifications: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    source_results: dict[int, list[str]] = {int(row["id"]): [] for row in selected}
    source_non_skip: dict[int, int] = {int(row["id"]): 0 for row in selected}
    source_clarifications: dict[int, int] = {int(row["id"]): 0 for row in selected}
    errors: list[dict[str, Any]] = []

    batches = [selected[offset : offset + max(1, args.batch_size)] for offset in range(0, len(selected), max(1, args.batch_size))]
    batch_results: list[tuple[list[dict[str, Any]], dict[str, Any] | None, Exception | None]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.concurrency, len(batches) or 1))) as pool:
        futures = {pool.submit(call_distiller, batch, args.task, args.timeout): batch for batch in batches}
        for future in as_completed(futures):
            batch = futures[future]
            try:
                batch_results.append((batch, future.result(), None))
            except Exception as exc:
                batch_results.append((batch, None, exc))

    batch_results.sort(key=lambda result: min(int(row["id"]) for row in result[0]) if result[0] else -1)
    for batch, payload, batch_error in batch_results:
        by_id = {int(row["id"]): row for row in batch}
        try:
            if batch_error is not None:
                raise batch_error
            assert payload is not None
            for raw_item in payload["items"]:
                try:
                    source_id = int(raw_item.get("source_turn_id"))
                except Exception:
                    rejected.append({"reason": "invalid source_turn_id"})
                    continue
                source = by_id.get(source_id)
                if not source:
                    rejected.append({"source_turn_id": source_id, "reason": "source not in current batch"})
                    continue
                item, error = validate_item(raw_item, source)
                if not item:
                    rejected.append({"source_turn_id": source_id, "reason": error})
                    continue
                if item["action"] == "skip":
                    continue
                if not route_is_plausible(item):
                    rejected.append({"source_turn_id": source_id, "reason": "implausible kind/route classification"})
                    continue
                if source_non_skip[source_id] >= 2:
                    rejected.append({"source_turn_id": source_id, "reason": "per-turn candidate cap exceeded"})
                    continue
                if item["action"] == "clarify" and source_clarifications[source_id] >= 1:
                    rejected.append({"source_turn_id": source_id, "reason": "per-turn clarification cap exceeded"})
                    continue
                source_non_skip[source_id] += 1
                if item["action"] == "clarify":
                    source_clarifications[source_id] += 1
                if item["action"] == "clarify":
                    obj = clarification_for(item, source, config)
                else:
                    obj = proposal_for(item, source, config)
                obj_id = str(obj.get("id") or obj.get("proposal_id"))
                source_results[source_id].append(obj_id)
                if item["action"] == "clarify":
                    clarifications.append(obj)
                else:
                    proposals.append(obj)
        except Exception as exc:
            message = repr(exc)
            errors.append({"turn_ids": [int(row["id"]) for row in batch], "error": message})
            if args.apply:
                for source in batch:
                    record_state(state, source, "failed", [], message)
                state.commit()
            continue
        for source in batch:
            source_id = int(source["id"])
            status = "complete" if source_non_skip[source_id] else "skipped"
            if args.apply:
                record_state(state, source, status, source_results[source_id])
        if args.apply:
            state.commit()

    if args.apply:
        selected_ids = {int(row["id"]) for row in selected}
        old_review = load_jsonl(args.review)
        old_review = [
            row for row in old_review
            if not (
                row.get("status", "pending") == "pending"
                and (row.get("candidate") or {}).get("source") == "google_ai_studio_continuous"
                and int((row.get("candidate") or {}).get("metadata", {}).get("source_turn_id") or -1) in selected_ids
            )
        ]
        by_proposal = {str(row.get("proposal_id") or ""): row for row in old_review}
        for proposal in proposals:
            by_proposal.setdefault(proposal["proposal_id"], proposal)
        atomic_jsonl(args.review, list(by_proposal.values()))
        old_clarify = load_jsonl(args.clarification)
        old_clarify = [
            row for row in old_clarify
            if not (
                row.get("status", "pending") == "pending"
                and row.get("source_type") == "google_ai_studio_continuous"
                and int(row.get("source_turn_id") or -1) in selected_ids
            )
        ]
        by_clarification = {str(row.get("id") or ""): row for row in old_clarify}
        for clarification in clarifications:
            by_clarification.setdefault(clarification["id"], clarification)
        atomic_jsonl(args.clarification, list(by_clarification.values()))

    total_user = sqlite3.connect(f"file:{args.turn_db}?mode=ro", uri=True).execute("SELECT count(*) FROM turns WHERE role='user'").fetchone()[0]
    processed = state.execute(
        "SELECT count(*) FROM processed_turns WHERE policy_version=? AND status IN ('complete','skipped','heuristic_skipped','rejected')",
        (POLICY_VERSION,),
    ).fetchone()[0]
    benchmark_excluded = len(excluded)
    accounted = min(total_user, processed + benchmark_excluded)
    report = {
        "generated_at": now(), "apply": args.apply, "policy_version": POLICY_VERSION,
        "selected_turns": len(selected), "heuristic_skipped_this_run": len(heuristic_skips),
        "proposal_count": len(proposals), "clarification_count": len(clarifications),
        "rejected_item_count": len(rejected), "batch_errors": errors,
        "processed_user_turns": processed, "total_user_turns": total_user,
        "processing_coverage_rate": round(processed / total_user, 6) if total_user else 1.0,
        "benchmark_excluded_user_turns": benchmark_excluded,
        "accounted_user_turns": accounted,
        "accounted_coverage_rate": round(accounted / total_user, 6) if total_user else 1.0,
        "selected_turn_ids": [int(row["id"]) for row in selected],
        "proposal_ids": [row["proposal_id"] for row in proposals],
        "clarification_ids": [row["id"] for row in clarifications],
        "private_candidates": {
            "proposals": [
                {
                    "proposal_id": row["proposal_id"],
                    "source_turn_id": row["candidate"]["metadata"]["source_turn_id"],
                    "kind": row["candidate"]["kind"],
                    "fact": row["candidate"]["content"],
                    "evidence_quote": row["candidate"]["evidence_quote"],
                    "review_state": row["candidate"]["metadata"]["review_state"],
                    "duplicate_uris": row["candidate"]["metadata"]["possible_duplicate_uris"],
                }
                for row in proposals
            ],
            "clarifications": [
                {
                    "id": row["id"], "source_turn_id": row["source_turn_id"],
                    "kind": row["memory_type"], "fact": row["content_preview"],
                    "evidence_quote": row["evidence_preview"], "risk": row["risk"],
                }
                for row in clarifications
            ],
            "rejected": rejected,
        },
        "memory_graph_writes": 0, "auto_approvals": 0,
    }
    args.reports.mkdir(parents=True, exist_ok=True)
    report_path = args.reports / f"continuous-distill-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.chmod(0o600)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(report_path)
    state.close()
    return 0 if not errors else 1


def main() -> int:
    with exclusive_lock(DEFAULT_LOCK):
        return run_main()


if __name__ == "__main__":
    raise SystemExit(main())
