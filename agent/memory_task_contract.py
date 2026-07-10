"""Compile recalled memory into entity bindings and executable task obligations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


_RELATION_PATTERNS = {
    "classmate": (r"同学", r"classmate"),
    "teammate": (r"组员|队友|搭档", r"teammate|partner"),
    "teacher": (r"老师|导师", r"teacher|mentor"),
    "friend": (r"朋友|好友", r"friend"),
}
_PROJECT_REFERENCE_PATTERNS = (
    r"那个项目|这个项目|当前项目|之前的项目",
    r"that project|this project|current project|the project we (?:discussed|worked on)",
)
_COMMON_CJK_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平"
    "黄和穆萧尹姚邵汪祁毛禹狄米贝明臧计伏成戴宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌"
    "霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚"
)
_GENERIC_NAMES = {
    "用户", "助手", "同学", "组员", "队友", "搭档", "老师", "导师", "朋友",
    "项目", "游戏", "关系", "对话", "回复", "记忆", "系统", "用户档案",
    "用户计划", "用户要求", "用户偏好", "当前项目", "游戏项目",
    "我和我", "和我同", "我的同", "用户的", "当前游", "一起做",
}


@dataclass
class EvidenceItem:
    uri: str
    text: str
    score: float = 0.0


@dataclass
class EntityCandidate:
    name: str
    relation: str
    score: float
    evidence_uris: list[str] = field(default_factory=list)


@dataclass
class ResolvedBinding:
    mention: str
    relation: str
    status: str
    confidence: float
    entity: str | None = None
    candidates: list[EntityCandidate] = field(default_factory=list)
    evidence_uris: list[str] = field(default_factory=list)


@dataclass
class Obligation:
    id: str
    description: str
    required_tools_any: list[str] = field(default_factory=list)
    required_tools_all: list[str] = field(default_factory=list)
    required_result_markers: list[str] = field(default_factory=list)
    evidence_uris: list[str] = field(default_factory=list)
    severity: str = "required"


@dataclass
class TaskMemoryContract:
    query: str
    namespace: str
    bindings: list[ResolvedBinding] = field(default_factory=list)
    obligations: list[Obligation] = field(default_factory=list)
    unresolved_ambiguity: list[str] = field(default_factory=list)
    evidence_uris: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_prompt(self) -> str:
        if not (self.bindings or self.obligations or self.unresolved_ambiguity):
            return ""
        lines = ["## Task Memory Contract (behavioral, evidence-backed)"]
        for binding in self.bindings:
            if binding.status == "resolved":
                lines.append(
                    f"- Resolved `{binding.mention}` -> `{binding.entity}` "
                    f"(confidence={binding.confidence:.2f}; evidence={', '.join(binding.evidence_uris[:2])})"
                )
            elif binding.candidates:
                names = ", ".join(f"{c.name}:{c.score:.2f}" for c in binding.candidates[:3])
                lines.append(
                    f"- Ambiguous `{binding.mention}` ({binding.relation}); candidates={names}. "
                    "Do not silently choose. Clarify if the identity materially changes the answer."
                )
            else:
                lines.append(
                    f"- Unresolved `{binding.mention}` ({binding.relation}). "
                    "Do not invent an identity; ask only if identity is material."
                )
        if self.obligations:
            lines.append("Obligations that must affect planning and completion:")
            for item in self.obligations:
                lines.append(f"- [{item.id}] {item.description}")
        lines.append(
            "Before claiming completion, compare actual tool/artifact evidence with every required obligation. "
            "If evidence is missing, continue working or state the concrete blocker."
        )
        return "\n".join(lines)


def _evidence_items(evidence: Iterable[dict[str, Any] | EvidenceItem]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for raw in evidence:
        if isinstance(raw, EvidenceItem):
            items.append(raw)
            continue
        uri = str(raw.get("uri") or "")
        text = str(raw.get("content") or raw.get("text") or raw.get("snippet") or "")
        try:
            score = float(raw.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if uri or text:
            items.append(EvidenceItem(uri=uri, text=text, score=score))
    return items


def detect_relation_mentions(query: str) -> list[tuple[str, str]]:
    mentions: list[tuple[str, str]] = []
    for relation, patterns in _RELATION_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, query, re.IGNORECASE):
                mention = match.group(0)
                pair = (mention, relation)
                if pair not in mentions:
                    mentions.append(pair)
    return mentions


def detect_project_mentions(query: str) -> list[str]:
    mentions: list[str] = []
    for pattern in _PROJECT_REFERENCE_PATTERNS:
        for match in re.finditer(pattern, query, re.IGNORECASE):
            mention = match.group(0)
            if mention not in mentions:
                mentions.append(mention)
    return mentions


def build_contract_recall_queries(query: str) -> list[str]:
    """Add generic evidence queries required to compile a behavioral contract."""
    queries: list[str] = []
    relation_labels = {
        "classmate": ("我的同学", "同学 关系"),
        "teammate": ("我的组员 队友 搭档", "项目成员 关系"),
        "teacher": ("我的老师 导师", "老师 关系"),
        "friend": ("我的朋友", "朋友 关系"),
    }
    for _mention, relation in detect_relation_mentions(query):
        queries.extend(relation_labels[relation])
    if detect_project_mentions(query):
        queries.extend(("当前项目 活跃项目 项目名称 状态", "current active project name status"))
    lower = query.lower()
    if re.search(r"调研|研究|查一下|调查|research|博主|网站|产品对比", lower):
        queries.extend(("用户 调研 偏好 多信息源 交叉验证", "research preference source verification"))
    if re.search(r"修复|实现|代码|bug|部署|build|fix|implement|测试|验证", lower):
        queries.extend(("用户 验证 偏好 真实运行 live path", "coding verification preference"))
    if re.search(r"发我|发送.*文件|deliver.*file|attachment|附件", lower):
        queries.extend(("用户 文件交付 偏好 真实附件 message_id", "file delivery attachment preference"))
    if re.search(r"记忆系统|数字替身|外置大脑|memory os|memory system", lower):
        queries.extend(("记忆系统 可验证闭环 自动写入 自动召回", "memory capability behavioral evidence"))
    if re.search(r"继续|推进|完成|修复|实现|调研|研究|build|fix|implement|finish|complete", lower):
        queries.extend((
            "用户 持续推进 不要问 是否继续 直到完成 验收 偏好",
            "user autonomy preference continue until verified do not ask",
        ))
    deduped: list[str] = []
    for item in queries:
        if item not in deduped:
            deduped.append(item)
    return deduped[:6]


def _extract_names(text: str, relation: str) -> set[str]:
    names: set[str] = set()
    # URI/path terms help rank evidence but must never become person candidates.
    body = text.split("\n", 1)[-1]
    relation_words = {
        "classmate": r"同学|classmate",
        "teammate": r"组员|队友|搭档|teammate|partner",
        "teacher": r"老师|导师|teacher|mentor",
        "friend": r"朋友|好友|friend",
    }[relation]
    # Only accept names in explicit relation grammar. Generic capitalized words
    # elsewhere in a memory are products/projects, not necessarily people.
    patterns = (
        rf"([A-Z][A-Za-z]{{2,24}}|[\u4e00-\u9fff]{{2,4}})(?:是|为|，|,|\s).{{0,8}}(?:{relation_words})",
        rf"(?:{relation_words})(?:是|叫|名为|：|:|\s).{{0,6}}([A-Z][A-Za-z]{{2,24}}|[\u4e00-\u9fff]{{2,4}})",
        rf"([A-Z][A-Za-z]{{2,24}}|[\u4e00-\u9fff]{{2,4}}).{{0,24}}(?:降级为|作为|属于|是).{{0,8}}(?:普通|核心|低频|我的|用户的)?.{{0,4}}(?:{relation_words})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, body, re.IGNORECASE):
            value = (match.group(1) or "").strip("：:，,。.（）() ")
            is_ascii_name = value.isascii() and value[:1].isalpha() and value[:1].upper() == value[:1]
            is_cjk_name = (
                not value.isascii()
                and 2 <= len(value) <= 4
                and value[0] in _COMMON_CJK_SURNAMES
            )
            if (
                value
                and (is_ascii_name or is_cjk_name)
                and value not in _GENERIC_NAMES
                and not value.startswith(("用户", "我的", "我和", "当前"))
            ):
                names.add(value)
    return names


def resolve_relationships(query: str, evidence: Iterable[dict[str, Any] | EvidenceItem]) -> list[ResolvedBinding]:
    items = _evidence_items(evidence)
    bindings: list[ResolvedBinding] = []
    for mention, relation in detect_relation_mentions(query):
        scores: dict[str, float] = {}
        uris: dict[str, list[str]] = {}
        for item in items:
            hay = f"{item.uri}\n{item.text}"
            for name in _extract_names(hay, relation):
                score = 1.0
                if relation == "classmate" and "同学" in hay:
                    score += 1.0
                if relation == "teammate" and re.search(r"组员|队友|搭档|teammate|partner", hay, re.I):
                    score += 1.0
                if name.lower() in query.lower():
                    score += 3.0
                if "用户档案" in item.uri or "关系" in item.uri or "relationship" in item.uri.lower():
                    score += 1.5
                score += min(max(item.score, 0.0), 1.0)
                # Repeated copies of one person's profile must not overwhelm a
                # second valid candidate merely by memory volume.
                scores[name] = max(scores.get(name, 0.0), score)
                if item.uri and item.uri not in uris.setdefault(name, []):
                    uris[name].append(item.uri)
        ranked = sorted(
            (
                EntityCandidate(name=name, relation=relation, score=score, evidence_uris=uris.get(name, []))
                for name, score in scores.items()
            ),
            key=lambda item: (-item.score, item.name.lower()),
        )
        if not ranked:
            bindings.append(ResolvedBinding(mention, relation, "unresolved", 0.0))
            continue
        top = ranked[0]
        second = ranked[1].score if len(ranked) > 1 else 0.0
        margin = top.score - second
        confidence = min(0.99, 0.45 + 0.08 * top.score + 0.08 * max(margin, 0.0))
        if top.score >= 3.0 and (len(ranked) == 1 or margin >= 2.0):
            bindings.append(
                ResolvedBinding(
                    mention, relation, "resolved", confidence, entity=top.name,
                    candidates=ranked[:3], evidence_uris=top.evidence_uris[:3],
                )
            )
        else:
            bindings.append(
                ResolvedBinding(
                    mention, relation, "ambiguous", min(confidence, 0.74),
                    candidates=ranked[:3], evidence_uris=top.evidence_uris[:3],
                )
            )
    return bindings


def _extract_project_names(item: EvidenceItem) -> set[str]:
    """Extract names only from explicit project grammar or a project URI."""
    names: set[str] = set()
    body = item.text.split("\n", 1)[-1]
    patterns = (
        r"(?:项目|工程|project)\s*[`'\"「『]?([A-Z][A-Za-z0-9_-]{2,31}|[\u4e00-\u9fff]{2,12})",
        r"([A-Z][A-Za-z0-9_-]{2,31}|[\u4e00-\u9fff]{2,12})\s*(?:项目|工程|project)\b",
        r"(?:名为|叫做|代号为|named|called)\s*[`'\"「『]?([A-Z][A-Za-z0-9_-]{2,31}|[\u4e00-\u9fff]{2,12})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, body, re.IGNORECASE):
            value = match.group(1).strip("`'\"「『」』：:，,。.（）() ")
            invalid_cjk_phrase = (
                not value.isascii()
                and (
                    value.startswith(("是", "为", "的", "在", "当前", "这个", "那个", "之前"))
                    or value.endswith(("当前", "活跃", "正在", "继续", "完成", "归档"))
                )
            )
            if (
                value
                and not invalid_cjk_phrase
                and value.lower() not in {"current", "active", "this", "that"}
            ):
                names.add(value)
    uri_match = re.search(r"(?:^|://)(?:projects?|项目)/([^/?#]+)", item.uri, re.IGNORECASE)
    if uri_match and not names:
        value = uri_match.group(1).strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{2,31}", value):
            names.add(value)
    return names


def resolve_projects(query: str, evidence: Iterable[dict[str, Any] | EvidenceItem]) -> list[ResolvedBinding]:
    """Resolve implicit project references conservatively from scoped evidence."""
    mentions = detect_project_mentions(query)
    if not mentions:
        return []
    items = _evidence_items(evidence)
    scores: dict[str, float] = {}
    uris: dict[str, list[str]] = {}
    for item in items:
        hay = f"{item.uri}\n{item.text}"
        for name in _extract_project_names(item):
            score = 1.0 + min(max(item.score, 0.0), 1.0)
            if re.search(r"当前|活跃|正在|继续|current|active|ongoing|in progress", hay, re.IGNORECASE):
                score += 2.0
            if re.search(r"已完成|归档|停止|废弃|completed|archived|stopped|abandoned", hay, re.IGNORECASE):
                score -= 1.5
            if "项目" in item.uri or re.search(r"projects?", item.uri, re.IGNORECASE):
                score += 1.0
            scores[name] = max(scores.get(name, float("-inf")), score)
            if item.uri and item.uri not in uris.setdefault(name, []):
                uris[name].append(item.uri)
    ranked = sorted(
        (
            EntityCandidate(name=name, relation="project", score=score, evidence_uris=uris.get(name, []))
            for name, score in scores.items()
        ),
        key=lambda item: (-item.score, item.name.lower()),
    )
    bindings: list[ResolvedBinding] = []
    for mention in mentions:
        if not ranked:
            bindings.append(ResolvedBinding(mention, "project", "unresolved", 0.0))
            continue
        top = ranked[0]
        second = ranked[1].score if len(ranked) > 1 else 0.0
        margin = top.score - second
        confidence = min(0.99, 0.48 + 0.08 * max(top.score, 0.0) + 0.08 * max(margin, 0.0))
        if top.score >= 2.0 and (len(ranked) == 1 or margin >= 1.5):
            bindings.append(ResolvedBinding(
                mention, "project", "resolved", confidence, entity=top.name,
                candidates=ranked[:3], evidence_uris=top.evidence_uris[:3],
            ))
        else:
            bindings.append(ResolvedBinding(
                mention, "project", "ambiguous", min(confidence, 0.74),
                candidates=ranked[:3], evidence_uris=top.evidence_uris[:3],
            ))
    return bindings


def _matching_uris(items: list[EvidenceItem], patterns: Iterable[str]) -> list[str]:
    found: list[str] = []
    for item in items:
        hay = f"{item.uri}\n{item.text}".lower()
        if any(re.search(pattern, hay, re.IGNORECASE) for pattern in patterns):
            if item.uri and item.uri not in found:
                found.append(item.uri)
    return found[:4]


def compile_obligations(query: str, evidence: Iterable[dict[str, Any] | EvidenceItem]) -> list[Obligation]:
    items = _evidence_items(evidence)
    q = query.lower()
    obligations: list[Obligation] = []

    research_task = bool(re.search(r"调研|研究|查一下|调查|research|博主|网站|产品对比", q))
    research_uris = _matching_uris(items, (r"多信息源|交叉验证|深度和广度|primary source|cross[- ]?valid|多源"))
    if research_task and research_uris:
        obligations.append(Obligation(
            id="research.multi_source",
            description="Use multiple independent sources, include primary/official evidence when available, and cross-check material claims before concluding.",
            required_tools_any=["deep_research", "web_search", "web_extract", "browser_navigate", "x_search"],
            required_result_markers=["source_diversity"],
            evidence_uris=research_uris,
        ))

    coding_task = bool(re.search(r"修复|实现|代码|bug|部署|build|fix|implement|测试|验证", q))
    coding_uris = _matching_uris(items, (r"先验证|真实运行|测试|live path|remote readback|公网|browser|dogfood"))
    if coding_task and coding_uris:
        obligations.append(Obligation(
            id="coding.verify",
            description="Exercise the changed behavior with real tests or runtime evidence; do not claim completion from a diff alone.",
            required_tools_any=["terminal", "browser_navigate", "process"],
            required_result_markers=["passing_verification"],
            evidence_uris=coding_uris,
        ))

    delivery_task = bool(re.search(r"发我|发送.*文件|deliver.*file|attachment|附件", q))
    delivery_uris = _matching_uris(items, (r"真实发送|附件|senddocument|message_id|media:/|telegram"))
    if delivery_task and delivery_uris:
        obligations.append(Obligation(
            id="delivery.real_attachment",
            description="Deliver the actual attachment through the platform and retain delivery evidence; plain path/MEDIA text is insufficient.",
            required_tools_any=["telegram_send_file", "send_message", "terminal"],
            required_result_markers=["delivery_confirmation"],
            evidence_uris=delivery_uris,
        ))

    memory_task = bool(re.search(r"记忆系统|数字替身|外置大脑|memory os|memory system", q))
    memory_uris = _matching_uris(items, (r"可验证闭环|自动写入|自动召回|不能.*误说|真实可验证|behavior"))
    if memory_task and memory_uris:
        obligations.append(Obligation(
            id="memory.behavioral_claim",
            description="Evaluate memory capability by real automatic recall/write/compliance behavior, not module presence or shadow candidates.",
            required_result_markers=["behavioral_evidence"],
            evidence_uris=memory_uris,
        ))

    autonomy_task = bool(re.search(r"继续|推进|完成|修复|实现|调研|研究|build|fix|implement|finish|complete", q))
    autonomy_uris = _matching_uris(items, (
        r"不要问.*继续|不问.*继续|不要.*等.*回复|自己.*推进|持续推进|直到.*完成|continue until|do not ask.*continue",
    ))
    # Repeated corrections are stronger than one incidental sentence. Require
    # two independent evidence nodes before promoting this into a hard contract.
    if autonomy_task and len(autonomy_uris) >= 2:
        obligations.append(Obligation(
            id="autonomy.continue_until_verified",
            description="Continue through all inferable next stages without asking whether to continue; stop only when the task is verified complete or a concrete external blocker prevents progress.",
            required_result_markers=["progress_evidence", "no_active_todos"],
            evidence_uris=autonomy_uris,
        ))
    return obligations


def build_task_memory_contract(
    query: str,
    evidence: Iterable[dict[str, Any] | EvidenceItem],
    *,
    namespace: str = "",
) -> TaskMemoryContract:
    items = _evidence_items(evidence)
    bindings = resolve_relationships(query, items) + resolve_projects(query, items)
    obligations = compile_obligations(query, items)
    unresolved = [binding.mention for binding in bindings if binding.status != "resolved"]
    evidence_uris: list[str] = []
    for item in items:
        if item.uri and item.uri not in evidence_uris:
            evidence_uris.append(item.uri)
    return TaskMemoryContract(
        query=query,
        namespace=namespace,
        bindings=bindings,
        obligations=obligations,
        unresolved_ambiguity=unresolved,
        evidence_uris=evidence_uris[:12],
    )


def _result_success(result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("success") is False or result.get("error"):
            return False
        if result.get("exit_code") not in (None, 0):
            return False
    text = str(result or "").lower()
    return not any(marker in text for marker in ("traceback", "fatal:", "permission denied"))


def plan_contract_repair(
    verdict: dict[str, Any],
    *,
    prior_fingerprints: Iterable[str] = (),
    max_attempts_per_failure: int = 2,
) -> dict[str, Any]:
    """Build a bounded, mechanical next-action plan for unmet obligations."""
    prior = list(prior_fingerprints)
    failures = [item for item in verdict.get("obligations", []) if not item.get("passed")]
    normalized = [
        {
            "id": str(item.get("id") or "unknown"),
            "missing": sorted(str(value) for value in item.get("missing", []) if value),
        }
        for item in failures
    ]
    fingerprint = hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    attempts = sum(1 for value in prior if value == fingerprint)
    if attempts >= max_attempts_per_failure:
        return {
            "action": "block",
            "fingerprint": fingerprint,
            "attempt": attempts,
            "message": "Repeated repair attempts did not change the contract failure. Report the concrete blocker and the evidence already collected; do not repeat the same action.",
        }
    actions: list[str] = []
    for item in normalized:
        obligation = item["id"]
        missing = " ".join(item["missing"]).lower()
        if "active todos:" in missing:
            actions.append("Continue the listed active TODO in priority order; mark it complete only after its real acceptance check passes.")
        elif "successful non-housekeeping action" in missing:
            actions.append("Execute one task-producing non-housekeeping tool action now, then inspect its real result.")
        elif obligation == "coding.verify" or "passing test/runtime" in missing:
            actions.append("Run the narrowest relevant test or live runtime probe with terminal/process/browser evidence; fix failures before retrying completion.")
        elif obligation == "delivery.real_attachment" or "delivery confirmation" in missing:
            actions.append("Use the real platform attachment delivery path and verify a returned message/delivery identifier; a local path is not evidence.")
        elif obligation == "research.multi_source" or "multi-source" in missing:
            actions.append("Collect and compare at least two independent sources, including an official/primary source when available.")
        elif obligation == "memory.behavioral_claim" or "behavior-level" in missing:
            actions.append("Run an isolated automatic recall/write/compliance behavior probe and clean up its fixture; module presence is insufficient.")
        else:
            actions.append(f"Address `{obligation}` with a new tool result that directly supplies: {', '.join(item['missing'])}.")
    return {
        "action": "repair",
        "fingerprint": fingerprint,
        "attempt": attempts + 1,
        "actions": list(dict.fromkeys(actions)),
    }


def evaluate_contract(
    contract: TaskMemoryContract,
    tool_events: Iterable[dict[str, Any]],
    *,
    active_todos: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    events = list(tool_events)
    todos = list(active_todos or [])
    tools = {str(event.get("tool_name") or "") for event in events if _result_success(event.get("result"))}
    rendered_results = "\n".join(str(event.get("result") or "") for event in events).lower()
    verdicts = []
    for obligation in contract.obligations:
        missing: list[str] = []
        if obligation.required_tools_all:
            absent = [name for name in obligation.required_tools_all if name not in tools]
            if absent:
                missing.append("required tools: " + ", ".join(absent))
        if obligation.required_tools_any and not tools.intersection(obligation.required_tools_any):
            missing.append("one of tools: " + ", ".join(obligation.required_tools_any))
        for marker in obligation.required_result_markers:
            if marker == "passing_verification":
                if not any(
                    event.get("tool_name") in {"terminal", "process", "browser_navigate"}
                    and _result_success(event.get("result"))
                    for event in events
                ):
                    missing.append("passing test/runtime evidence")
            elif marker == "delivery_confirmation":
                if not any(token in rendered_results for token in ("message_id", '"ok": true', "attachment")):
                    missing.append("platform delivery confirmation")
            elif marker == "source_diversity":
                source_events = [event for event in events if event.get("tool_name") in {
                    "deep_research", "web_search", "web_extract", "browser_navigate", "x_search"
                } and _result_success(event.get("result"))]
                if len(source_events) < 2 and "manifest" not in rendered_results:
                    missing.append("multi-source/cross-check evidence")
            elif marker == "behavioral_evidence":
                if not any(token in rendered_results for token in ("passed", "pass=", "behavior", "semantic recall", "live")):
                    missing.append("behavior-level test evidence")
            elif marker == "no_active_todos":
                active = [
                    item for item in todos
                    if str(item.get("status") or "").lower() in {"pending", "in_progress"}
                ]
                if active:
                    missing.append(
                        "active todos: "
                        + ", ".join(str(item.get("id") or "?") for item in active[:8])
                    )
            elif marker == "progress_evidence":
                housekeeping = {"todo", "memory", "memory_graph_read", "memory_graph_search", "hindsight_recall", "session_search"}
                progressed = any(
                    str(event.get("tool_name") or "") not in housekeeping
                    and _result_success(event.get("result"))
                    for event in events
                )
                if not progressed:
                    missing.append("successful non-housekeeping action evidence")
        verdicts.append({
            "id": obligation.id,
            "passed": not missing,
            "missing": missing,
            "evidence_uris": obligation.evidence_uris,
        })
    return {
        "passed": all(item["passed"] for item in verdicts),
        "obligations": verdicts,
        "tools_seen": sorted(tool for tool in tools if tool),
        "unresolved_ambiguity": list(contract.unresolved_ambiguity),
    }
