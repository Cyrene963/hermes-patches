"""Skill routing and enforcement helpers for Hermes Agent.

This module is intentionally dependency-light: it runs before the first model
token of a turn, so it cannot depend on the model deciding to call
``skill_view`` by itself.  The router produces an auditable route decision and
can synthesize skill-invocation messages that load mandatory skills before the
user's actual request reaches the model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import os
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)


@dataclass
class TaskClassification:
    task_domain: str = "other"
    execution_depth: str = "standard_task"
    autonomy_level: str = "proceed_until_blocked"
    duration_expectation: str = "minutes"
    continuation_policy: str = "stop_after_answer"
    completion_contract: str = "answer_only"
    risk_class: str = "low"
    planning_required: bool = False
    research_required: bool = False
    coding_required: bool = False
    test_required: bool = False
    verification_required: bool = False
    memory_required: bool = False
    deep_work_required: bool = False
    progress_required: bool = False
    deployment_required: bool = False
    review_required: bool = False
    hermes_agent_task: bool = False
    memory_task: bool = False
    patch_or_pr_task: bool = False
    coding_task: bool = False
    research_task: bool = False
    routing_failure_report: bool = False
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)


@dataclass
class SkillManifest:
    name: str
    description: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    negative_triggers: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    required_when: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    priority: int = 0
    load_policy: str = "optional"
    examples_positive: list[str] = field(default_factory=list)
    examples_negative: list[str] = field(default_factory=list)
    verification_hooks: list[str] = field(default_factory=list)
    command_key: str | None = None
    skill_dir: str | None = None


@dataclass
class SkillRouteDecision:
    classification: TaskClassification
    candidate_skills: list[str] = field(default_factory=list)
    mandatory_skills: list[str] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    rejected_skills: dict[str, str] = field(default_factory=dict)
    missing_skills: list[str] = field(default_factory=list)
    loaded_skills: list[str] = field(default_factory=list)
    dependency_expansion: dict[str, list[str]] = field(default_factory=dict)
    bundle_expansion: dict[str, list[str]] = field(default_factory=dict)
    gate_status: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    schema_version: int = 1
    route_id: str | None = None
    user_message_sha256_16: str | None = None
    source: str = "deterministic"
    reranker: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def sanitize_for_storage(self) -> dict[str, Any]:
        data = self.to_dict()
        # Durable route plans must never include raw user text or tool output.
        data.pop("raw_user_message", None)
        data["schema_version"] = self.schema_version
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SkillRouteDecision":
        raw_cls = data.get("classification") if isinstance(data, Mapping) else {}
        classification = TaskClassification(**{
            k: v for k, v in dict(raw_cls or {}).items()
            if k in TaskClassification.__dataclass_fields__
        })
        kwargs = {
            k: v for k, v in dict(data or {}).items()
            if k in cls.__dataclass_fields__ and k != "classification"
        }
        return cls(classification=classification, **kwargs)


@dataclass
class SkillRoutingConfig:
    enabled: bool = True
    durable_state: bool = True
    semantic_reranker_enabled: bool = True
    semantic_privacy_mode: str = "sanitized"
    semantic_min_confidence: float = 0.65
    semantic_max_candidates: int = 12
    semantic_timeout_seconds: float = 3.0
    semantic_allow_network: bool = True
    semantic_include_examples: bool = False
    semantic_provider: str = ""
    semantic_model: str = ""
    semantic_base_url: str = ""
    semantic_api_key: str = ""


def _message_digest(user_message: str) -> str:
    return hashlib.sha256((user_message or "").encode("utf-8", "ignore")).hexdigest()[:16]


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def load_skill_routing_config(config: Mapping[str, Any] | None = None) -> SkillRoutingConfig:
    if config is None:
        try:
            from hermes_cli.config import load_config
            config = load_config() or {}
        except Exception:
            config = {}
    sr = dict((config or {}).get("skill_routing") or {}) if isinstance(config, Mapping) else {}
    sem = dict(sr.get("semantic_reranker") or {})
    return SkillRoutingConfig(
        enabled=_coerce_bool(sr.get("enabled"), True),
        durable_state=_coerce_bool(sr.get("durable_state"), True),
        semantic_reranker_enabled=_coerce_bool(sem.get("enabled"), True),
        semantic_privacy_mode=str(sem.get("privacy_mode") or "sanitized"),
        semantic_min_confidence=float(sem.get("min_confidence") or 0.65),
        semantic_max_candidates=int(sem.get("max_candidates") or 12),
        semantic_timeout_seconds=float(sem.get("timeout_seconds") or 3.0),
        semantic_allow_network=_coerce_bool(sem.get("allow_network"), True),
        semantic_include_examples=_coerce_bool(sem.get("include_examples"), False),
        semantic_provider=str(sem.get("provider") or ""),
        semantic_model=str(sem.get("model") or ""),
        semantic_base_url=str(sem.get("base_url") or ""),
        semantic_api_key=str(sem.get("api_key") or ""),
    )


_SECRETISH_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{16,}|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{16,})")
_PATH_RE = re.compile(r"(/(?:root|home|Users|tmp|var|etc)/[^\s,'\"]{1,160})")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s,'\"]+")
_LONG_NUMBER_RE = re.compile(r"\b\d{8,}\b")


def redact_for_reranker(text: str) -> str:
    value = str(text or "")
    value = _SECRETISH_RE.sub("[REDACTED_SECRET]", value)
    value = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = _URL_RE.sub("[REDACTED_URL]", value)
    value = _PATH_RE.sub("[REDACTED_PATH]", value)
    value = _LONG_NUMBER_RE.sub("[REDACTED_ID]", value)
    return value[:240]


def build_semantic_rerank_payload(
    user_message: str,
    candidates: Sequence[str],
    manifests: Mapping[str, SkillManifest] | None = None,
    *,
    classification: TaskClassification | None = None,
    privacy_mode: str = "sanitized",
    include_examples: bool = False,
) -> dict[str, Any]:
    base = list(dict.fromkeys(candidates or []))
    cls = classification or classify_task(user_message)
    terms = sorted(redact_for_reranker(t) for t in _query_terms(user_message) if len(t) >= 2)[:40]
    manifest_payload = []
    for name in base:
        m = (manifests or {}).get(name) or (manifests or {}).get(name.lower().replace("_", "-"))
        item = {
            "name": name,
            "description": redact_for_reranker(getattr(m, "description", "") if m else ""),
            "tags": [redact_for_reranker(x) for x in (getattr(m, "tags", []) if m else [])[:20]],
            "triggers": [redact_for_reranker(x) for x in (getattr(m, "triggers", []) if m else [])[:20]],
            "task_types": [redact_for_reranker(x) for x in (getattr(m, "task_types", []) if m else [])[:20]],
            "load_policy": getattr(m, "load_policy", "optional") if m else "optional",
            "priority": getattr(m, "priority", 0) if m else 0,
        }
        if include_examples:
            item["examples_positive"] = [redact_for_reranker(x) for x in (getattr(m, "examples_positive", []) if m else [])[:3]]
        manifest_payload.append(item)
    payload = {
        "task": "semantic_skill_rerank",
        "privacy_mode": privacy_mode,
        "message_sha256_16": _message_digest(user_message),
        "classification": asdict(cls),
        "query_features": {"terms": terms, "evidence": list(cls.evidence)},
        "candidates": manifest_payload,
        "required_output": ["selected_skills", "mandatory_skills", "rejected_skills", "confidence"],
        "rules": [
            "Never drop deterministic mandatory skills; only select from candidates.",
            "Return strict JSON only.",
        ],
    }
    if privacy_mode == "raw_opt_in":
        payload["redacted_excerpt"] = redact_for_reranker(user_message)
    return payload


def live_semantic_rerank_classifier(prompt: str, *, routing_config: SkillRoutingConfig | None = None) -> str:
    cfg = routing_config or load_skill_routing_config()
    if not cfg.semantic_allow_network:
        raise RuntimeError("semantic_reranker_network_disabled")
    from agent.auxiliary_client import call_llm
    resp = call_llm(
        task="skill_routing",
        provider=cfg.semantic_provider or None,
        model=cfg.semantic_model or None,
        base_url=cfg.semantic_base_url or None,
        api_key=cfg.semantic_api_key or None,
        messages=[
            {"role": "system", "content": "You are a privacy-preserving skill routing judge. Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=600,
        timeout=cfg.semantic_timeout_seconds,
    )
    return str(resp.choices[0].message.content or "")


_LONG_HORIZON_PATTERNS = [
    r"deep[-\s]?work|深度工作",
    r"花\s*(一|1)?\s*(晚上|晚|夜|整晚|一天|1天|一周|1周|week|day|night)",
    r"一整天|整晚|通宵|overnight|all\s+night|all\s+day",
    r"不准停|不要停|直到完成|不完美不准停|自己推进|一直推进",
    r"不要问.*(继续|要不要)|别问.*(继续|要不要)",
    r"能查就查|能改就改|能测就测|端到端|彻底修复|production[-\s]?ready|能\s*merge|直接做",
    r"继续$|去修复|去干|你到底在干嘛",
]
_HERMES_PATTERNS = [r"hermes\s*agent|Hermes\s*Agent|Hermes|技能|skill|skills|gateway|toolsets?|工具集|插件|plugin|patch[-\s]?chain|补丁|四端同步"]
_MEMORY_PATTERNS = [r"memory\s*graph|hindsight|memory\s*os|记忆|Memory\s*OS|外置大脑|数字替身|召回|写入管道"]
_PR_PATTERNS = [r"\bPR\b|pull\s+request|upstream|官方仓库|开源|提交|merge|补丁仓库|patch[-\s]?repo"]
_CODING_PATTERNS = [r"repo|代码|修复|bug|测试|test|pytest|build|实现|改代码|patch|failing\s+tests|能跑的都跑"]
_RESEARCH_PATTERNS = [r"调研|research|竞品|市面|类似方案|资料|source|citation|引用"]
_ROUTING_FAILURE_PATTERNS = [
    r"没(有)?用.*skill|没(有)?加载.*skill|应该加载|不知道.*skill|skills?.*用(不)?上",
    r"又偷懒|又停了|没继续|要不要继续|实际使用.*垃圾|测试.*通过.*实际|无济于事",
]
_SIMPLE_EXPLAIN_PATTERNS = [r"^(简单|简要|briefly|quickly|一句话|解释一下|说下|介绍一下)"]

_DEFAULT_BUNDLES: dict[str, list[str]] = {
    "long_horizon": ["deep-work", "aegis-lite-completion-gate", "memory-management"],
    "coding_fix": ["deep-work", "universal-solutions-for-prs"],
    "hermes_maintenance": ["hermes-agent", "hermes-memory-os", "memory-management", "universal-solutions-for-prs"],
    "research": ["deep-work"],
}

_QUERY_EXPANSIONS = {
    "彻底修复": ["deep-work", "long horizon", "verification", "completion gate"],
    "不准停": ["deep-work", "completion gate", "autonomous"],
    "继续": ["deep-work", "autonomous", "proceed until verified"],
    "skill": ["skills", "skill routing", "skill discovery"],
    "技能": ["skill", "skills", "skill routing"],
    "测试": ["verification", "tests", "regression"],
}


def _matches_any(text: str, patterns: Sequence[str]) -> list[str]:
    hits: list[str] = []
    for pat in patterns:
        try:
            if re.search(pat, text, re.IGNORECASE):
                hits.append(pat)
        except re.error:
            continue
    return hits


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [value]
        if "," in value and "\n" not in value:
            parts = value.split(",")
        return [str(p).strip() for p in parts if str(p).strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def classify_task(user_message: str) -> TaskClassification:
    text = user_message or ""
    cls = TaskClassification()

    long_hits = _matches_any(text, _LONG_HORIZON_PATTERNS)
    hermes_hits = _matches_any(text, _HERMES_PATTERNS)
    memory_hits = _matches_any(text, _MEMORY_PATTERNS)
    pr_hits = _matches_any(text, _PR_PATTERNS)
    coding_hits = _matches_any(text, _CODING_PATTERNS)
    research_hits = _matches_any(text, _RESEARCH_PATTERNS)
    failure_hits = _matches_any(text, _ROUTING_FAILURE_PATTERNS)
    simple_hits = _matches_any(text.strip(), _SIMPLE_EXPLAIN_PATTERNS)

    if hermes_hits:
        cls.hermes_agent_task = True
        cls.task_domain = "hermes_config"
        cls.evidence.append("hermes_agent_terms")
    if memory_hits:
        cls.memory_task = True
        cls.memory_required = True
        if cls.task_domain == "other":
            cls.task_domain = "memory"
        cls.evidence.append("memory_terms")
    if pr_hits:
        cls.patch_or_pr_task = True
        cls.review_required = True
        cls.verification_required = True
        # Merge/upstream/PR work has an implicit regression-test contract even
        # when the user says it tersely (e.g. "做到能 merge").
        cls.test_required = True
        cls.evidence.append("patch_or_pr_terms")
    if coding_hits:
        cls.coding_task = True
        cls.coding_required = True
        cls.test_required = True
        cls.verification_required = True
        if cls.task_domain == "other":
            cls.task_domain = "coding"
        cls.evidence.append("coding_terms")
    if research_hits:
        cls.research_task = True
        cls.research_required = True
        if cls.task_domain == "other":
            cls.task_domain = "research"
        cls.evidence.append("research_terms")
    if failure_hits:
        cls.routing_failure_report = True
        cls.evidence.append("routing_failure_report")

    if long_hits:
        cls.deep_work_required = True
        cls.planning_required = True
        cls.progress_required = True
        cls.verification_required = True
        cls.execution_depth = "deep_work"
        cls.autonomy_level = "fully_autonomous_until_done"
        cls.duration_expectation = "long_horizon"
        cls.continuation_policy = "continue_until_verified"
        cls.completion_contract = "modify_code_and_verify" if (cls.hermes_agent_task or cls.coding_task) else "verify"
        cls.risk_class = "medium"
        cls.confidence = 0.95
        cls.evidence.append("long_horizon_terms")
    elif simple_hits and not failure_hits:
        cls.execution_depth = "quick_answer"
        cls.autonomy_level = "proceed_until_blocked"
        cls.duration_expectation = "minutes"
        cls.continuation_policy = "stop_after_answer"
        cls.confidence = 0.75
        cls.evidence.append("simple_answer_terms")
    elif failure_hits:
        cls.execution_depth = "standard_task"
        cls.continuation_policy = "continue_until_verified"
        cls.verification_required = True
        cls.confidence = 0.85

    if cls.hermes_agent_task and (cls.routing_failure_report or cls.deep_work_required):
        cls.completion_contract = "modify_code_and_verify"
        cls.coding_required = True
        cls.test_required = True
        cls.verification_required = True

    return cls


def _available_lookup(available_skill_names: Iterable[str] | None) -> set[str]:
    names = set()
    for name in available_skill_names or []:
        raw = str(name or "").strip()
        if not raw:
            continue
        names.add(raw)
        names.add(raw.lower())
        names.add(raw.lower().replace("_", "-"))
    return names


def _skill_available(name: str, lookup: set[str]) -> bool:
    return not lookup or name in lookup or name.lower() in lookup or name.lower().replace("_", "-") in lookup


def _extract_hermes_metadata(frontmatter: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = frontmatter.get("metadata") if isinstance(frontmatter, Mapping) else None
    if isinstance(metadata, Mapping):
        hermes = metadata.get("hermes")
        if isinstance(hermes, Mapping):
            return hermes
    return {}


def _parse_manifest_from_skill_info(cmd: str, info: Mapping[str, Any]) -> SkillManifest:
    name = str(info.get("name") or cmd.lstrip("/")).strip()
    desc = str(info.get("description") or "")
    skill_dir = str(info.get("skill_dir") or "")
    fm: Mapping[str, Any] = {}
    if skill_dir:
        skill_md = Path(skill_dir) / "SKILL.md"
        if skill_md.exists():
            try:
                from agent.skill_utils import parse_frontmatter
                raw = skill_md.read_text(encoding="utf-8")
                parsed, _body = parse_frontmatter(raw)
                if isinstance(parsed, Mapping):
                    fm = parsed
            except Exception as exc:
                logger.debug("failed to parse skill manifest %s: %s", skill_md, exc)
    hermes = _extract_hermes_metadata(fm)
    routing = hermes.get("skill_routing") if isinstance(hermes.get("skill_routing"), Mapping) else {}
    tags = _as_list(fm.get("tags")) + _as_list(hermes.get("tags")) + _as_list(routing.get("tags"))
    triggers = (
        _as_list(fm.get("triggers"))
        + _as_list(hermes.get("triggers"))
        + _as_list(hermes.get("triggered_by"))
        + _as_list(routing.get("triggers"))
    )
    required_when = _as_list(fm.get("required_when")) + _as_list(hermes.get("required_when")) + _as_list(routing.get("required_when"))
    try:
        priority = int(fm.get("priority") or hermes.get("priority") or routing.get("priority") or 0)
    except Exception:
        priority = 0
    return SkillManifest(
        name=str(fm.get("name") or name),
        description=str(fm.get("description") or desc),
        category=str(fm.get("category") or info.get("category") or "general"),
        tags=tags,
        triggers=triggers,
        negative_triggers=_as_list(fm.get("negative_triggers")) + _as_list(hermes.get("negative_triggers")) + _as_list(routing.get("negative_triggers")),
        task_types=_as_list(fm.get("task_types")) + _as_list(hermes.get("task_types")) + _as_list(routing.get("task_types")),
        required_when=required_when,
        dependencies=_as_list(fm.get("dependencies")) + _as_list(hermes.get("dependencies")) + _as_list(routing.get("dependencies")),
        conflicts=_as_list(fm.get("conflicts")) + _as_list(hermes.get("conflicts")) + _as_list(routing.get("conflicts")),
        priority=priority,
        load_policy=str(fm.get("load_policy") or hermes.get("load_policy") or routing.get("load_policy") or "optional"),
        examples_positive=_as_list(fm.get("examples_positive")) + _as_list(hermes.get("examples_positive")) + _as_list(routing.get("examples_positive")),
        examples_negative=_as_list(fm.get("examples_negative")) + _as_list(hermes.get("examples_negative")) + _as_list(routing.get("examples_negative")),
        verification_hooks=_as_list(fm.get("verification_hooks")) + _as_list(hermes.get("verification_hooks")) + _as_list(routing.get("verification_hooks")),
        command_key=cmd,
        skill_dir=skill_dir or None,
    )


def load_skill_manifests(commands: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, SkillManifest]:
    commands = commands if commands is not None else _skill_command_map()
    manifests: dict[str, SkillManifest] = {}
    for cmd, info in commands.items():
        if not isinstance(info, Mapping):
            continue
        manifest = _parse_manifest_from_skill_info(str(cmd), info)
        manifests[manifest.name] = manifest
        manifests[manifest.name.lower().replace("_", "-")] = manifest
        manifests[str(cmd).lstrip("/").lower().replace("_", "-")] = manifest
    return manifests


def _query_terms(user_message: str) -> set[str]:
    text = (user_message or "").lower()
    terms = {t for t in re.split(r"[^\w\u4e00-\u9fff-]+", text) if t}
    for key, expansions in _QUERY_EXPANSIONS.items():
        if key.lower() in text:
            terms.update(e.lower() for e in expansions)
    return terms


def _manifest_score(manifest: SkillManifest, user_message: str, cls: TaskClassification) -> tuple[int, list[str]]:
    text = (user_message or "").lower()
    terms = _query_terms(user_message)
    haystack = " ".join([
        manifest.name,
        manifest.description,
        " ".join(manifest.tags),
        " ".join(manifest.triggers),
        " ".join(manifest.task_types),
        " ".join(manifest.examples_positive),
    ]).lower()
    score = manifest.priority
    reasons: list[str] = []
    for neg in manifest.negative_triggers:
        if neg and neg.lower() in text:
            return -100, ["negative_trigger"]
    for trig in manifest.triggers:
        if trig and trig.lower() in text:
            score += 20
            reasons.append("trigger")
    overlap = sum(1 for term in terms if len(term) >= 3 and term in haystack)
    if overlap:
        score += overlap
        reasons.append("lexical_semantic_overlap")
    task_types = {t.lower() for t in manifest.task_types}
    if cls.deep_work_required and ({"deep_work", "long_horizon", "long_horizon_execution", "autonomous_iteration"} & task_types):
        score += 15
        reasons.append("task_type")
    if cls.hermes_agent_task and ("hermes" in haystack or "hermes-agent" in haystack):
        score += 10
        reasons.append("domain")
    return score, reasons


def _condition_matches(condition: str, cls: TaskClassification) -> bool:
    c = (condition or "").strip().lower()
    if not c:
        return False
    normalized = c.replace(" ", "")
    mapping = {
        "user_requested_deep_work==true": cls.deep_work_required,
        "user_said_do_not_stop==true": cls.deep_work_required and cls.continuation_policy == "continue_until_verified",
        "autonomy_level==fully_autonomous_until_done": cls.autonomy_level == "fully_autonomous_until_done",
        "task_requires_code_modification==true": cls.coding_required,
        "task_requires_verification==true": cls.verification_required,
        "deep_work_required==true": cls.deep_work_required,
        "hermes_agent_task==true": cls.hermes_agent_task,
    }
    if normalized in mapping:
        return bool(mapping[normalized])
    if normalized.startswith("duration_hours>="):
        return cls.duration_expectation in {"hours", "overnight", "day", "week", "open_ended", "long_horizon"}
    return False


def _manifest_mandatory(manifest: SkillManifest, cls: TaskClassification) -> bool:
    policy = (manifest.load_policy or "").lower()
    if policy == "always":
        return True
    if any(_condition_matches(cond, cls) for cond in manifest.required_when):
        return True
    return policy == "mandatory_if_triggered" and bool(manifest.triggers)


def route_skills(
    user_message: str,
    available_skill_names: Iterable[str] | None = None,
    manifests: Mapping[str, SkillManifest] | None = None,
    *,
    routing_config: SkillRoutingConfig | Mapping[str, Any] | None = None,
    classifier: Callable[[str], Any] | None = None,
) -> SkillRouteDecision:
    cls = classify_task(user_message)
    lookup = _available_lookup(available_skill_names)
    mandatory: list[str] = []
    candidates: list[str] = []
    notes: list[str] = []
    dependency_expansion: dict[str, list[str]] = {}
    bundle_expansion: dict[str, list[str]] = {}
    rejected: dict[str, str] = {}

    def add(name: str, *, must: bool = False, reason: str | None = None) -> None:
        if name not in candidates:
            candidates.append(name)
        if must and name not in mandatory:
            mandatory.append(name)
        if reason:
            notes.append(f"{name}: {reason}")

    def add_bundle(bundle: str, *, must_first: bool = False) -> None:
        skills = _DEFAULT_BUNDLES.get(bundle, [])
        bundle_expansion[bundle] = list(skills)
        for i, skill in enumerate(skills):
            add(skill, must=must_first and i == 0, reason=f"bundle:{bundle}")

    if cls.hermes_agent_task:
        add("hermes-agent", must=True, reason="domain:hermes")
        add_bundle("hermes_maintenance")
    if cls.memory_task:
        add("memory-management", must=True, reason="domain:memory")
    if cls.deep_work_required:
        add_bundle("long_horizon", must_first=True)
        add("deep-work", must=True, reason="long-horizon/autonomous request")
    if cls.coding_task:
        add_bundle("coding_fix")
    if cls.research_task:
        add_bundle("research")
    if cls.patch_or_pr_task:
        add("universal-solutions-for-prs", must=cls.hermes_agent_task, reason="patch/pr")
        add("hermes-memory-os", must=cls.hermes_agent_task, reason="patch-chain")
    if cls.routing_failure_report:
        add("deep-work", must=cls.deep_work_required, reason="user reported prior routing failure")

    if manifests:
        seen_manifest_ids: set[int] = set()
        for manifest in manifests.values():
            mid = id(manifest)
            if mid in seen_manifest_ids:
                continue
            seen_manifest_ids.add(mid)
            score, reasons = _manifest_score(manifest, user_message, cls)
            if score < 0:
                rejected[manifest.name] = ",".join(reasons)
                continue
            must = _manifest_mandatory(manifest, cls)
            if must or score >= 8:
                add(manifest.name, must=must, reason="manifest:" + "+".join(reasons or ["required_when"]))
            if manifest.name in candidates and manifest.dependencies:
                dependency_expansion[manifest.name] = list(manifest.dependencies)
                for dep in manifest.dependencies:
                    add(dep, reason=f"dependency:{manifest.name}")

    if cls.execution_depth == "quick_answer" and "deep-work" in mandatory:
        mandatory.remove("deep-work")
        rejected["deep-work"] = "quick_answer_negative_gate"
        notes.append("quick-answer request: deep-work not mandatory")

    selected = [s for s in candidates if _skill_available(s, lookup)]
    missing = [s for s in mandatory if lookup and not _skill_available(s, lookup)]
    gate_status = {
        "pre_execution_gate": "pass" if not missing else "missing_mandatory",
        "clarification_gate": "enabled" if cls.deep_work_required else "standard",
        "completion_gate": "enabled" if cls.deep_work_required else "standard",
        "mandatory_skills_loaded_or_loadable": not missing,
    }

    decision = SkillRouteDecision(
        classification=cls,
        candidate_skills=candidates,
        mandatory_skills=mandatory,
        selected_skills=selected,
        rejected_skills=rejected,
        missing_skills=missing,
        dependency_expansion=dependency_expansion,
        bundle_expansion=bundle_expansion,
        gate_status=gate_status,
        notes=notes,
        user_message_sha256_16=_message_digest(user_message),
    )

    cfg = routing_config
    if cfg is None:
        cfg = SkillRoutingConfig(semantic_reranker_enabled=False)
    elif isinstance(cfg, Mapping):
        cfg = load_skill_routing_config(cfg)
    if isinstance(cfg, SkillRoutingConfig) and cfg.semantic_reranker_enabled and candidates:
        active_classifier = classifier
        if active_classifier is None and cfg.semantic_allow_network:
            active_classifier = lambda prompt: live_semantic_rerank_classifier(prompt, routing_config=cfg)
        rr = model_rerank_skill_candidates(
            user_message,
            candidates[: max(1, cfg.semantic_max_candidates)],
            manifests,
            classifier=active_classifier,
            classification=cls,
            privacy_mode=cfg.semantic_privacy_mode,
            include_examples=cfg.semantic_include_examples,
        )
        decision.reranker = rr
        if not rr.get("fallback_used") and float(rr.get("confidence") or 0.0) >= cfg.semantic_min_confidence:
            selected_rr = [s for s in _as_list(rr.get("selected_skills")) if s in candidates]
            if selected_rr:
                # Preserve deterministic mandatory skills even if the judge omits them.
                decision.selected_skills = list(dict.fromkeys(list(mandatory) + selected_rr))
            extra_mandatory = [s for s in _as_list(rr.get("mandatory_skills")) if s in candidates]
            for skill in extra_mandatory:
                if skill not in decision.mandatory_skills:
                    decision.mandatory_skills.append(skill)
            decision.source = "deterministic+semantic_reranker"
        else:
            decision.reranker.setdefault("fallback_used", True)
    return decision


def _skill_command_map() -> Mapping[str, Mapping[str, Any]]:
    try:
        from agent.skill_commands import get_skill_commands
        return get_skill_commands()
    except Exception:
        return {}


def available_skill_names_from_commands(commands: Mapping[str, Mapping[str, Any]] | None = None) -> set[str]:
    commands = commands if commands is not None else _skill_command_map()
    out: set[str] = set()
    for cmd, info in commands.items():
        slug = str(cmd).lstrip("/")
        out.add(slug)
        name = str((info or {}).get("name") or "")
        if name:
            out.add(name)
    return out


def _command_for_skill(skill_name: str, commands: Mapping[str, Mapping[str, Any]]) -> str | None:
    target = skill_name.lower().replace("_", "-")
    for cmd, info in commands.items():
        slug = str(cmd).lstrip("/").lower().replace("_", "-")
        name = str((info or {}).get("name") or "").lower().replace("_", "-")
        if target in {slug, name}:
            return str(cmd)
    return None


def build_autoload_skill_messages(
    user_message: str,
    *,
    task_id: str | None = None,
    routing_config: SkillRoutingConfig | Mapping[str, Any] | None = None,
    classifier: Callable[[str], Any] | None = None,
) -> tuple[list[dict[str, str]], SkillRouteDecision]:
    commands = _skill_command_map()
    names = available_skill_names_from_commands(commands)
    manifests = load_skill_manifests(commands)
    cfg = routing_config if routing_config is not None else load_skill_routing_config()
    decision = route_skills(user_message, names, manifests=manifests, routing_config=cfg, classifier=classifier)
    decision.route_id = f"skill-route-{decision.user_message_sha256_16 or _message_digest(user_message)}"

    messages: list[dict[str, str]] = []
    if not decision.mandatory_skills:
        return messages, decision

    try:
        from agent.skill_commands import build_skill_invocation_message
    except Exception:
        decision.notes.append("skill invocation helper unavailable")
        return messages, decision

    for skill_name in decision.mandatory_skills:
        cmd = _command_for_skill(skill_name, commands)
        if not cmd:
            if skill_name not in decision.missing_skills:
                decision.missing_skills.append(skill_name)
            decision.gate_status["pre_execution_gate"] = "missing_mandatory"
            continue
        runtime_note = (
            "Automatically loaded by Hermes Skill Router before the first model token. "
            "This skill is mandatory for the current task classification; follow it unless the user explicitly overrides it."
        )
        payload = build_skill_invocation_message(
            cmd,
            user_instruction="Auto-loaded because the current user request requires this skill.",
            task_id=task_id,
            runtime_note=runtime_note,
        )
        if payload:
            messages.append({"role": "user", "content": payload})
            decision.loaded_skills.append(skill_name)
        else:
            if skill_name not in decision.missing_skills:
                decision.missing_skills.append(skill_name)
            decision.gate_status["pre_execution_gate"] = "missing_mandatory"

    if decision.classification.deep_work_required:
        messages.append({
            "role": "user",
            "content": (
                "[Hermes Skill Router Execution Gate]\n"
                "This turn was classified as long-horizon/autonomous/deep-work. "
                "Before answering, build a todo/state plan and start executing with tools. "
                "Clarification Gate: do not ask non-blocking 'whether to continue' questions; "
                "use reasonable defaults and retrieve missing context with tools. Ask only for "
                "credentials, safety/permission boundaries, or irreversible choices. "
                "Completion Gate: do not final while there is a concrete tool-backed next step; "
                "final is allowed only after the task is verified, a real blocker is proven, "
                "or an explicit resource/permission limit is reached. "
                "If you are about to stop with a plan, continue executing instead.]"
            ),
        })

    return messages, decision


_PREMATURE_FINAL_PATTERNS = [
    r"要不要继续|是否继续|如果你愿意.*继续|需要我.*继续|要我.*继续",
    r"下一步可以|后续可以|建议下一步|我可以帮你",
    r"计划如下|我会先|我将会|可以按照.*步骤",
]

_SUBSTANTIVE_TOOL_NAMES = {
    "terminal", "execute_code", "read_file", "search_files", "patch", "write_file",
    "web_search", "web_extract", "browser_navigate", "browser_click", "browser_snapshot",
    "delegate_task", "cronjob", "process",
}


def looks_like_premature_final(response_text: str, decision: SkillRouteDecision | None) -> bool:
    """Return True when a long-horizon turn appears to stop with planning/clarification.

    This is intentionally lightweight and deterministic.  The router's job is
    not to prove task completion; it blocks the most common failure mode where a
    model answers a deep-work/autonomous request with a plan or asks whether to
    continue before using tools.
    """
    if not decision or not decision.classification.deep_work_required:
        return False
    text = (response_text or "").strip()
    if not text:
        return True
    return bool(_matches_any(text, _PREMATURE_FINAL_PATTERNS))


def count_substantive_tool_turns(messages: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for msg in messages or []:
        if not isinstance(msg, Mapping) or msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            try:
                name = tc.get("function", {}).get("name") if isinstance(tc, Mapping) else getattr(tc.function, "name", "")
            except Exception:
                name = ""
            if name in _SUBSTANTIVE_TOOL_NAMES:
                count += 1
    return count


def completion_gate_should_continue(
    response_text: str,
    decision: SkillRouteDecision | None,
    messages: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    """Code-level CompletionGate used by conversation_loop before finalizing.

    For long-horizon/deep-work requests, a first-turn final response with no
    substantive tool evidence is almost always the exact failure mode the user
    reported: plan-only output, fake clarification, or early stopping.  Block it
    once by injecting a synthetic continuation message so the model must start
    executing.  After substantive tools have run, the normal agent loop can
    finalize or report a true blocker.
    """
    if not decision or not decision.classification.deep_work_required:
        return False, "not_long_horizon"
    tool_turns = count_substantive_tool_turns(messages)
    if tool_turns <= 0:
        return True, "long_horizon_no_substantive_tools"
    if looks_like_premature_final(response_text, decision):
        return True, "long_horizon_premature_final_pattern"
    return False, "pass"


def build_completion_gate_continue_message(reason: str, decision: SkillRouteDecision | None) -> dict[str, str]:
    skills = ", ".join((decision.mandatory_skills if decision else []) or [])
    return {
        "role": "user",
        "content": (
            "[Hermes Skill Router Completion Gate]\n"
            f"Blocked premature final response: {reason}. "
            f"Mandatory skills for this route: {skills or 'none recorded'}. "
            "This is a long-horizon/autonomous task. Do not ask whether to continue "
            "and do not stop with a plan. Take the next concrete tool-backed action now: "
            "inspect files/repo/context, update todo/state, execute the repair/research/test step, "
            "and only final after verified completion or a true blocker."
        ),
    }


def skill_gate_for_tool(tool_name: str, decision: SkillRouteDecision | None) -> tuple[bool, str]:
    """Lightweight tool-call-time gate: returns (allowed, reason)."""
    if not decision:
        return True, "no_route_decision"
    mandatory = set(decision.mandatory_skills)
    loaded = set(decision.loaded_skills)
    missing_loaded = sorted(mandatory - loaded)
    if missing_loaded:
        return False, "mandatory_skills_not_loaded:" + ",".join(missing_loaded)
    if tool_name in {"terminal", "patch", "write_file", "execute_code"} and decision.classification.hermes_agent_task and "hermes-agent" not in loaded:
        return False, "hermes_agent_tool_without_hermes_agent_skill"
    if tool_name in {"cronjob"} and "cron-management" in mandatory and "cron-management" not in loaded:
        return False, "cron_tool_without_cron_skill"
    return True, "pass"


def runtime_reroute_guidance_for_tool_result(
    tool_name: str,
    tool_result: Any,
    decision: SkillRouteDecision | None,
    *,
    failed: bool,
) -> str:
    """Return a runtime rerouting hint after stage/tool failure signals.

    This does not replace the main router. It is the in-loop reroute layer: when
    a long-horizon task hits a failed tool/test/build/edit, the next model call
    receives an explicit instruction to reroute through the mandatory skills,
    repair, and verify instead of summarising or stopping.
    """
    if not failed or not decision or not decision.classification.deep_work_required:
        return ""
    mandatory = ", ".join(decision.mandatory_skills or [])
    return (
        "\n\n[Hermes Skill Router Runtime Re-Route]\n"
        f"Tool `{tool_name}` produced a failure signal during a long-horizon task. "
        f"Active mandatory skills: {mandatory or 'none recorded'}. "
        "Re-evaluate the route before the next action: inspect the failure, load any missing supporting skill if needed, "
        "repair the root cause, rerun the relevant verification gate, and do not final until the failure is fixed or a true blocker is proven."
    )


def model_rerank_skill_candidates(
    user_message: str,
    candidates: Sequence[str],
    manifests: Mapping[str, SkillManifest] | None = None,
    *,
    classifier: Any | None = None,
    classification: TaskClassification | None = None,
    privacy_mode: str = "sanitized",
    include_examples: bool = False,
) -> dict[str, Any]:
    """Optional model-based semantic rerank hook with deterministic fail-closed fallback.

    `classifier` is an injected callable for tests or deployments. It should
    return JSON or a dict with selected_skills/mandatory_skills/rejected_skills.
    When unavailable or invalid, the function returns the original candidates
    and marks fallback_used=True. This keeps the architecture model-ready without
    making core routing depend on a live API call.
    """
    base = list(dict.fromkeys(candidates or []))
    if classifier is None:
        return {
            "selected_skills": base,
            "mandatory_skills": [],
            "rejected_skills": {},
            "confidence": 0.0,
            "fallback_used": True,
            "reason": "classifier_unavailable",
        }
    prompt = build_semantic_rerank_payload(
        user_message,
        base,
        manifests,
        classification=classification,
        privacy_mode=privacy_mode,
        include_examples=include_examples,
    )
    try:
        raw = classifier(json.dumps(prompt, ensure_ascii=False))
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
        selected = [s for s in _as_list(data.get("selected_skills")) if s in base]
        mandatory = [s for s in _as_list(data.get("mandatory_skills")) if s in base]
        rejected_raw_obj = data.get("rejected_skills")
        rejected_raw = rejected_raw_obj if isinstance(rejected_raw_obj, Mapping) else {}
        return {
            "selected_skills": selected or base,
            "mandatory_skills": mandatory,
            "rejected_skills": {str(k): str(v) for k, v in rejected_raw.items()},
            "confidence": float(data.get("confidence") or 0.0),
            "fallback_used": False,
            "reason": str(data.get("reason") or "model_rerank"),
        }
    except Exception as exc:
        return {
            "selected_skills": base,
            "mandatory_skills": [],
            "rejected_skills": {},
            "confidence": 0.0,
            "fallback_used": True,
            "reason": f"classifier_error:{exc.__class__.__name__}",
        }


def routing_failures_to_eval_cases(failure_log: str | Path | None = None, output_path: str | Path | None = None) -> Path:
    """Convert sanitized routing-failure JSONL records into regression eval cases."""
    base = Path(get_hermes_home()) / "logs" / "skill_routing"
    src = Path(failure_log) if failure_log else base / "routing_failures.jsonl"
    dst = Path(output_path) if output_path else base / "routing_eval_cases.jsonl"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        dst.write_text("", encoding="utf-8")
        return dst
    out_lines: list[str] = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        case = {
            "id": "routing-failure-" + str(rec.get("user_message_sha256_16") or "unknown"),
            "source": "routing_failure_log",
            "input_ref": {"user_message_sha256_16": rec.get("user_message_sha256_16", "")},
            "expected_skills": rec.get("expected_skills", []),
            "assertions": [
                "expected_skills_selected_or_loaded",
                "no_raw_user_message_in_fixture",
                "completion_gate_enabled_for_long_horizon",
            ],
            "classification": rec.get("classification", {}),
        }
        out_lines.append(json.dumps(case, ensure_ascii=False, sort_keys=True))
    dst.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    return dst




def persist_skill_route_plan(
    session_db: Any,
    decision: SkillRouteDecision,
    *,
    session_id: str | None,
    task_id: str | None = None,
    status: str = "active",
    ttl_seconds: float | None = 7 * 24 * 3600,
) -> int | None:
    """Persist a privacy-safe route plan if the session DB supports it."""
    if not session_db or not session_id or not decision:
        return None
    save = getattr(session_db, "save_skill_route_plan", None)
    if not callable(save):
        return None
    try:
        plan = decision.sanitize_for_storage()
        plan.pop("user_message", None)
        plan.pop("raw_user_message", None)
        return save(
            session_id,
            plan,
            task_id=task_id,
            user_message_sha256_16=decision.user_message_sha256_16 or "",
            status=status,
            ttl_seconds=ttl_seconds,
        )
    except Exception as exc:
        logger.debug("failed to persist skill route plan: %s", exc)
        return None


def restore_latest_skill_route_plan(
    session_db: Any,
    *,
    session_id: str | None,
    task_id: str | None = None,
) -> SkillRouteDecision | None:
    """Restore the latest active route plan without raw message recovery."""
    if not session_db or not session_id:
        return None
    getter = getattr(session_db, "get_latest_skill_route_plan", None)
    if not callable(getter):
        return None
    try:
        row = getter(session_id, task_id=task_id, active_only=True)
        if not row:
            return None
        plan = row.get("route_plan") or {}
        decision = SkillRouteDecision.from_dict(plan)
        decision.progress.setdefault("restored_from_plan_id", row.get("id"))
        return decision
    except Exception as exc:
        logger.debug("failed to restore skill route plan: %s", exc)
        return None

def log_skill_route_decision(decision: SkillRouteDecision, *, user_message: str, session_id: str | None = None, platform: str | None = None) -> None:
    try:
        log_dir = Path(get_hermes_home()) / "logs" / "skill_routing"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"skill_routing_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
        digest = hashlib.sha256((user_message or "").encode("utf-8", "ignore")).hexdigest()[:16]
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id or "",
            "platform": platform or "",
            "user_message_sha256_16": digest,
            "decision": decision.to_dict(),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as exc:
        logger.debug("failed to write skill route trace: %s", exc)


def maybe_log_routing_failure(decision: SkillRouteDecision, *, user_message: str, session_id: str | None = None) -> None:
    if not decision.classification.routing_failure_report:
        return
    try:
        base = Path(get_hermes_home()) / "logs" / "skill_routing"
        base.mkdir(parents=True, exist_ok=True)
        path = base / "routing_failures.jsonl"
        digest = hashlib.sha256((user_message or "").encode("utf-8", "ignore")).hexdigest()[:16]
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id or "",
            "user_message_sha256_16": digest,
            "failure_type": "user_reported_skill_routing_failure",
            "expected_skills": decision.mandatory_skills or decision.candidate_skills,
            "actual_selected_skills": decision.selected_skills,
            "loaded_skills": decision.loaded_skills,
            "missing_skills": decision.missing_skills,
            "root_cause": "mandatory skill routing/loading was user-reported as missing or ineffective",
            "proposed_fix": "convert this record into a golden skill-router eval case",
            "converted_to_eval_case": False,
            "eval_candidate": True,
            "classification": asdict(decision.classification),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as exc:
        logger.debug("failed to write routing failure record: %s", exc)
