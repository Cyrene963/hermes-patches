"""Memory Write Pipeline — automatic memory extraction, classification, and write-back.

Flow: Conversation → Reflection → Candidate Extraction → Write Gates → Storage → Readback Check
"""

import re
import logging
import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def load_memory_write_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load memory-write policy from Hermes home.

    The pipeline is deliberately conservative by default: shadow-only unless
    the operator explicitly enables limited_auto/full_auto in
    ~/.hermes/memory_write_config.yaml. This keeps the implementation generic
    and policy-driven rather than baking local deployment choices into code.
    """
    default = {
        "mode": "shadow",
        "auto_write_threshold": 0.85,
        "never_auto_write_to_core": True,
        "allowed_auto_types": [
            "user_fact",
            "project_fact",
            "task",
            "explicit_preference",
            "explicit_correction",
            "decision",
            "lesson",
        ],
        "semantic_classifier": {"model_enabled": False},
        "repair_queue_path": "~/.hermes/logs/memory_repair_queue.jsonl",
    }
    path = Path(config_path or os.path.expanduser("~/.hermes/memory_write_config.yaml"))
    if not path.exists():
        return default
    try:
        import yaml
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cfg = raw.get("memory_write", raw) or {}
        merged = dict(default)
        merged.update({k: v for k, v in cfg.items() if v is not None})
        return merged
    except Exception as exc:
        logger.warning("Failed to load memory write config from %s: %s", path, exc)
        return default


def _auto_type(candidate: "CandidateFact") -> str:
    """Map a candidate to policy-level auto-write type.

    This is intentionally metadata-based, not keyword-based. Text semantics are
    classified upstream; this gate only decides whether a classified candidate
    is safe to write automatically.
    """
    if candidate.source_type == "user_correction":
        return "explicit_correction"
    if candidate.memory_type == "preference" and candidate.source_type == "user_direct":
        return "explicit_preference"
    return candidate.memory_type

# ─── Data Classes ────────────────────────────────────────────────

@dataclass
class CandidateFact:
    """A candidate memory to potentially write."""
    subject: str
    predicate: str
    object_value: str
    importance: float  # 0.0-1.0
    memory_type: str   # user_fact, project_fact, rule, task, preference, decision, lesson
    target_store: str  # memory_graph, memory_md, hindsight, review, ignore
    target_path: str   # e.g. "用户档案/学习者/考试成绩"
    evidence_quote: str
    confidence: float
    source_type: str   # user_direct, user_correction, agent_inference, system_event
    requires_review: bool = False
    dedup_key: str = ""
    conflict_with: str = ""
    reason: str = ""
    namespace: str = ""  # telegram:{chat_id} or core

# ─── Importance Gate ─────────────────────────────────────────────

_IMPORTANCE_RULES = [
    # High importance patterns
    (r'(不要|别|禁止|必须|一定要|以后|规则|格式)', 'rule', 0.95),
    (r'(改成|换成|现在用|已经|迁移|升级)', 'project_fact', 0.90),
    (r'(成绩|分数|考试|mock|DSE)', 'user_fact', 0.85),
    (r'(部署|配置|服务器|端口|数据库)', 'project_fact', 0.85),
    (r'(家庭|父母|学校|年龄|住)', 'user_fact', 0.85),
    (r'(喜欢|偏好|讨厌|在意|关心)', 'preference', 0.80),
    (r'(明天|下周|计划|任务|提醒)', 'task', 0.80),
    (r'(决定|选择|确认|同意|批准)', 'decision', 0.85),
    (r'(教训|经验|发现|原来|原来如此)', 'lesson', 0.75),
    # Low importance patterns
    (r'(哈哈|嗯|好的|可以|ok|OK)', 'noise', 0.10),
    (r'(困|累了|饿|吃饭|休息|困了|有点困)', 'temporary', 0.20),
    (r'(教训|经验|踩坑|注意|避免|原来|排序错|出错|bug|修复)', 'lesson', 0.60),
    (r'(刚才|报错|错误|失败)', 'evidence', 0.50),
]

def score_importance(text: str) -> tuple[str, float]:
    """Score importance of a conversation turn."""
    for pattern, mtype, score in _IMPORTANCE_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return mtype, score
    return 'unknown', 0.50

# ─── Type Classification ─────────────────────────────────────────

_TYPE_KEYWORDS = {
    'user_fact': ['成绩', '分数', '年龄', '家庭', '学校', '住', '生日', '考试', 'mock'],
    'project_fact': ['技术栈', '部署', '配置', '数据库', '服务器', '版本', '迁移', '架构'],
    'rule': ['不要', '别', '禁止', '必须', '以后', '规则', '格式', '注意', 'MEDIA', 'LaTeX'],
    'task': ['明天', '下周', '计划', '任务', '提醒', '检查', '部署', '修复'],
    'preference': ['喜欢', '偏好', '讨厌', '在意', '关心', '更喜欢', '不要用'],
    'decision': ['决定', '选择', '确认', '同意', '批准', '采用', '改用'],
    'lesson': ['教训', '经验', '发现', '原来', '踩坑', '注意', '避免'],
}

def classify_type(text: str) -> str:
    """Classify memory type from text."""
    for mtype, keywords in _TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return mtype
    return 'unknown'

# ─── Target Store Router ─────────────────────────────────────────

def route_target(memory_type: str, importance: float, is_rule: bool = False) -> str:
    """Route to appropriate storage."""
    if is_rule or memory_type == 'rule':
        return 'memory_md' if importance >= 0.90 else 'memory_graph'
    if importance >= 0.80:
        return 'memory_graph'
    if importance >= 0.40:
        return 'hindsight'
    return 'ignore'

# ─── Conflict Detection ──────────────────────────────────────────

def detect_conflict(new_fact: CandidateFact, existing_facts: List[Dict]) -> Optional[str]:
    """Check if new fact conflicts with existing facts."""
    for existing in existing_facts:
        if (existing.get('subject', '').lower() == new_fact.subject.lower() and
            existing.get('predicate', '').lower() == new_fact.predicate.lower()):
            old_obj = str(existing.get('object', ''))
            new_obj = new_fact.object_value
            if old_obj.lower() != new_obj.lower():
                return existing.get('uri', '')
    return None

# ─── Dedup ────────────────────────────────────────────────────────

def make_dedup_key(fact: CandidateFact) -> str:
    """Generate dedup key for a fact."""
    return f"{fact.subject.lower()}|{fact.predicate.lower()}|{fact.object_value.lower()[:50]}"

# ─── Write Readback Check ────────────────────────────────────────

def generate_readback_queries(fact: CandidateFact) -> List[str]:
    """Generate queries to verify write is retrievable."""
    queries = [
        f"{fact.subject} {fact.predicate}",
        f"{fact.subject} {fact.object_value[:20]}",
    ]
    # Add compact CJK variant when the subject contains CJK characters.
    if re.search(r'[\u4e00-\u9fff]', fact.subject):
        queries.append(f"{fact.subject}{fact.predicate}")
    return queries

# ─── Main Pipeline ────────────────────────────────────────────────

class MemoryWritePipeline:
    """Orchestrates automatic memory writing."""

    def __init__(self, graph_client=None, hindsight_client=None, config: Optional[Dict[str, Any]] = None):
        self.graph = graph_client
        self.hindsight = hindsight_client
        self.config = config if config is not None else load_memory_write_config()
        self._write_log = []

    def reflect_and_extract(self, user_msg: str, assistant_msg: str) -> Dict[str, Any]:
        """Generate memory reflection from a conversation turn."""
        combined = f"{user_msg} {assistant_msg}"
        mtype, importance = score_importance(combined)

        candidates = []

        # Extract durable meta-learning / target-function signals from the user
        # message. These are not ordinary facts; they are reusable operating
        # constraints that should later become procedural memory, skills, or
        # reject gates after review/readback. Keep this user-text-only so the
        # assistant cannot promote its own apology into a memory.
        meta_learning_patterns = [
            (
                r'(纠正|错了|不对|又没|太气人|记不住|不会主动存|不会主动召回|防复发|根因|通用(?:的)?(?:解决方案|机制)|目标函数|reject gate|外置大脑|数字替身|之前.*聊过|先回忆|先召回|项目目标)',
                'agent_memory_workflow',
                'procedural_memory',
                0.95,
                'User correction / digital-stand-in target-function signal',
            ),
            (
                r'(小说|写作|低频心跳|漫画|审美|AI味|AI 味|文学|角色|叙事).{0,80}(应该|不要|避免|偏好|喜欢|标准|质感|风格)',
                'creative_target_function',
                'target_function',
                0.90,
                'User stated durable creative/writing taste or target function',
            ),
            (
                r'(Claude Code|Claude|Codex|GitHub|github|token|PAT|api key|API key|凭据|not logged in|登录).{0,120}(先查|记忆|配置|凭据|用|审计|给过|不要|不能|可以)',
                'tool_credential_route',
                'procedural_memory',
                0.90,
                'User stated durable tool/credential lookup route; store route, never raw secret',
            ),
            (
                r'(下周|明天|考试|时间表|范围|DSE|mock|科目|复习).{0,120}(考试|时间表|范围|复习|安排|科目|DSE|mock)',
                'exam_context',
                'user_fact',
                0.88,
                'User provided durable exam context that future planning must recall',
            ),
        ]
        for pattern, subject, memory_type, importance_score, reason in meta_learning_patterns:
            if re.search(pattern, user_msg, re.IGNORECASE):
                target_path = '用户档案/目标函数' if memory_type == 'target_function' else '用户档案/程序性记忆'
                if subject == 'tool_credential_route':
                    target_path = '用户档案/工具凭据查找规则'
                elif subject == 'exam_context':
                    target_path = '用户档案/考试上下文'
                candidates.append(CandidateFact(
                    subject=subject,
                    predicate='derived_from_user_signal',
                    object_value=user_msg[:500],
                    importance=importance_score,
                    memory_type=memory_type,
                    target_store='memory_graph',
                    target_path=target_path,
                    evidence_quote=user_msg[:500],
                    confidence=0.90,
                    source_type='user_correction' if subject == 'agent_memory_workflow' else 'user_direct',
                    requires_review=(subject == 'tool_credential_route'),
                    reason=reason,
                ))

        # Extract user corrections
        correction_patterns = [
            r'不是\s*(\d+)\s*[,，]?\s*是\s*(\d+)',
            r'(\d+)\s*不对\s*[,，]\s*(\d+)',
            r'应该是\s*(\d+)',
            r'(\d+)\s*岁\s*[,，]?\s*是\s*(\d+)',
            r'不是\s*(\S+)\s*[,，]?\s*是\s*(\S+)',
        ]
        for pattern in correction_patterns:
            m = re.search(pattern, user_msg)
            if m:
                candidates.append(CandidateFact(
                    subject='user', predicate='correction',
                    object_value=m.group(0),
                    importance=0.95, memory_type='user_fact',
                    target_store='memory_graph', target_path='用户档案/纠错',
                    evidence_quote=user_msg, confidence=0.95,
                    source_type='user_correction', requires_review=True, reason='User corrected a fact'
                ))

        # Extract rules
        rule_patterns = [
            r'以后.*?不要.*?用\s*(\S+)',
            r'给.*?发.*?不要.*?(\S+)',
            r'以后.*?(\S+)\s*不要',
            r'以后.*?(跳过|绕过|忽略|不需要)',
            r'(跳过|绕过|忽略).*?(确认|检查|验证)',
        ]
        for pattern in rule_patterns:
            m = re.search(pattern, user_msg)
            if m:
                # Check if sensitive (跳过/绕过/忽略/不需要确认)
                is_sensitive = bool(re.search(r'(跳过|绕过|忽略|不需要|自动)', user_msg))
                candidates.append(CandidateFact(
                    subject='operation', predicate='rule',
                    object_value=m.group(0),
                    importance=0.95, memory_type='rule',
                    target_store='review' if is_sensitive else 'memory_md',
                    target_path='',
                    evidence_quote=user_msg, confidence=0.95,
                    source_type='user_direct',
                    requires_review=is_sensitive,
                    reason='Sensitive rule requires review' if is_sensitive else 'User stated a rule'
                ))

        # Extract facts with entity + attribute from the *user message only*.
        # The assistant response often contains explanations, headings, and quoted
        # context that are not user-confirmed facts; using it here caused ordinary
        # dialogue to be miswritten as project tech_stack memories.
        extraction_text = user_msg
        entity_patterns = [
            # Quoted entity names: “Project X” / 「学生A」 / 《项目A》
            (r'[“"「《]([^”"」》]{2,40})[”"」》]', 'entity'),
            # Explicit project/entity introducers. Keep this narrow: project facts
            # require a named project, not any CJK phrase before 配置/用/架构.
            (r'(?:项目|project|应用|app|仓库|repo)\s*[:：]?\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_-]{1,39})(?=.*?(成绩|分数|考试|mock|技术栈|部署|数据库|配置|服务器|架构|用|换成|改成|迁移))', 'entity'),
        ]
        for pattern, etype in entity_patterns:
            match = re.search(pattern, extraction_text, re.IGNORECASE)
            if match:
                entity_name = match.group(1)

                # Check for specific fact types
                if re.search(r'(成绩|分数|考试|mock)', extraction_text) and re.search(r'(成绩|分数|mock)\s*(?:是|为|=|:|：)?\s*\d+\s*分', extraction_text):
                    score_match = re.search(r'(\d+)\s*分', extraction_text)
                    score_val = score_match.group(1) if score_match else '?'
                    candidates.append(CandidateFact(
                        subject=entity_name, predicate='exam_score',
                        object_value=f'{score_val}分',
                        importance=0.85, memory_type='user_fact',
                        target_store='memory_graph',
                        target_path=f'用户档案/{entity_name}/考试成绩',
                        evidence_quote=user_msg, confidence=0.90,
                        source_type='user_direct'
                    ))

                # Project-tech-stack extraction is intentionally not handled by
                # this legacy regex layer. It previously turned wrapper text and
                # incidental strings like "项目: some-skill 现在用 PostgreSQL" into
                # project_fact candidates. Project facts should come from the
                # semantic classifier / review path, not brittle entity regexes.


        # Extract preferences
        pref_patterns = [
            r'我(更)?(关心|在意|喜欢|偏好)',
            r'不要用\s*(\S+)',
            r'(好像|似乎|可能).*?(喜欢|偏好|关心)',
        ]
        for pattern in pref_patterns:
            m = re.search(pattern, user_msg)
            if m:
                # Check if it's an inference (好像/似乎/可能)
                is_inference = bool(re.search(r'(好像|似乎|可能|大概)', user_msg))
                candidates.append(CandidateFact(
                    subject='user', predicate='preference',
                    object_value=m.group(0),
                    importance=0.80, memory_type='preference',
                    target_store='review' if is_inference else 'memory_graph',
                    target_path='用户档案/偏好',
                    evidence_quote=user_msg, confidence=0.70 if is_inference else 0.85,
                    source_type='agent_inference' if is_inference else 'user_direct',
                    requires_review=is_inference,
                ))

        # Extract tasks
        task_patterns = [
            r'明天.*?(检查|部署|修复|确认)',
            r'(提醒|记住).*?明天',
        ]
        for pattern in task_patterns:
            m = re.search(pattern, user_msg)
            if m:
                candidates.append(CandidateFact(
                    subject='user', predicate='task',
                    object_value=m.group(0),
                    importance=0.80, memory_type='task',
                    target_store='memory_graph',
                    target_path='用户档案/任务',
                    evidence_quote=user_msg, confidence=0.85,
                    source_type='user_direct'
                ))

        # Semantic classifier overlay. This runs after legacy extractors so old
        # regression tests keep their first concrete fact, but high-level durable
        # signals (creative target functions, credential routes, exam contexts,
        # user correction learning events) are not missed when no narrow entity
        # extractor fired. It is shadow-safe because write policy remains
        # conservative and fail-closed.
        try:
            from agent.memory_semantic_classifier import classify_memory_semantics
            sem_cfg = self.config.get('semantic_classifier') or {}
            model_classifier = sem_cfg.get('model_callable') if sem_cfg.get('model_enabled') else None
            sem = classify_memory_semantics(user_msg, assistant_msg, model_classifier=model_classifier)
            sem_kind = sem.memory_kind
            if sem_kind not in {'ignore', 'temporary'}:
                sem_type_map = {
                    'creative_preference': 'target_function',
                    'target_function': 'target_function',
                    'credential_route': 'procedural_memory',
                    'exam_context': 'user_fact',
                    'correction_learning_event': 'procedural_memory',
                    'active_workstream_context': 'procedural_memory',
                    'project_identity_verification': 'procedural_memory',
                    'explicit_memory_request': 'procedural_memory',
                    'procedural_rule': 'rule',
                    'user_fact': 'preference' if '偏好' in sem.target_path else 'user_fact',
                    'project_fact': 'project_fact',
                }
                sem_subject_map = {
                    'creative_preference': 'creative_target_function',
                    'target_function': 'target_function',
                    'credential_route': 'tool_credential_route',
                    'exam_context': 'exam_context',
                    'correction_learning_event': 'agent_memory_workflow',
                    'active_workstream_context': 'active_workstream_context',
                    'project_identity_verification': 'project_identity_verification',
                    'explicit_memory_request': 'explicit_memory_request',
                    'procedural_rule': 'procedural_rule',
                }
                sem_memory_type = sem_type_map.get(sem_kind, 'lesson')
                sem_requires_review = bool(sem.requires_review)
                candidates.append(CandidateFact(
                    subject=sem_subject_map.get(sem_kind, sem_kind),
                    predicate='semantic_signal',
                    object_value=sem.evidence_quote[:500],
                    importance=max(0.40, min(1.0, sem.confidence)),
                    memory_type=sem_memory_type,
                    target_store=sem.target_store,
                    target_path=sem.target_path,
                    evidence_quote=sem.evidence_quote[:500],
                    confidence=max(0.40, min(1.0, sem.confidence)),
                    source_type='user_correction' if sem_kind == 'correction_learning_event' else 'user_direct',
                    requires_review=sem_requires_review,
                    reason=sem.reason or sem.reject_gate,
                ))
        except Exception as exc:
            logger.debug('Semantic memory classifier failed closed: %s', exc)

        # Deduplicate overlapping regex/semantic hits while preserving order. This prevents
        # one correction such as "不是85，是83" from generating duplicate write
        # candidates via multiple correction patterns.
        deduped = []
        seen = set()
        for candidate in candidates:
            key = (candidate.subject, candidate.predicate, candidate.object_value, candidate.memory_type)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        candidates = deduped

        return {
            'candidates': candidates,
            'importance': importance,
            'memory_type': mtype,
            'evidence': user_msg[:200],
        }

    def classify_write(self, candidate: CandidateFact, existing_facts: List[Dict] = None, namespace: str = "") -> Dict[str, Any]:
        """Apply 5 gates to determine if and where to write."""
        existing = existing_facts or []

        # Gate 1: Importance
        if candidate.importance < 0.40:
            return {'action': 'ignore', 'reason': 'Low importance'}

        # Gate 2: Type (already classified)

        # Gate 3: Conflict
        conflict_uri = detect_conflict(candidate, existing)
        if conflict_uri:
            candidate.conflict_with = conflict_uri
            candidate.requires_review = True
            return {
                'action': 'review',
                'target_store': 'review',
                'reason': f'Conflicts with existing fact: {conflict_uri}',
                'conflict_with': conflict_uri
            }

        # Gate 4: Dedup
        candidate.dedup_key = make_dedup_key(candidate)
        # (dedup check would query existing facts)

        # Gate 5: Review
        if candidate.source_type == 'agent_inference':
            candidate.requires_review = True
            return {'action': 'review', 'target_store': 'review', 'reason': 'Agent inference requires review'}
        # Check for sensitive rules
        sensitive_patterns = ['跳过', '绕过', '忽略', '不需要确认', '自动']
        if any(p in candidate.object_value for p in sensitive_patterns):
            candidate.requires_review = True
            return {'action': 'review', 'target_store': 'review', 'reason': 'Sensitive rule requires review'}

        # Determine target store
        target = route_target(candidate.memory_type, candidate.importance,
                             candidate.memory_type == 'rule')

        # Override if candidate already has a target (from extraction)
        if candidate.target_store and candidate.target_store != 'ignore':
            target = candidate.target_store

        # If requires_review, override target to review queue
        if candidate.requires_review:
            target = 'review'

        return {
            'action': 'write',
            'target_store': target,
            'target_path': candidate.target_path,
            'requires_review': candidate.requires_review,
            'dedup_key': candidate.dedup_key,
            'namespace': namespace or candidate.namespace,
        }

    def _should_auto_write(self, candidate: CandidateFact, classification: Dict[str, Any]) -> bool:
        """Return True for high-confidence, user-originated facts safe to write automatically."""
        mode = str(self.config.get('mode', 'shadow')).strip().lower()
        if mode not in {'limited_auto', 'full_auto'}:
            return False
        if classification.get('action') != 'write':
            return False
        if classification.get('target_store') not in {'memory_graph', 'memory_md'}:
            return False
        if candidate.requires_review or classification.get('requires_review'):
            return False
        if candidate.source_type not in {'user_direct', 'user_correction'}:
            return False
        threshold = float(self.config.get('auto_write_threshold', 0.85))
        if candidate.importance < threshold or candidate.confidence < threshold:
            return False
        allowed = set(self.config.get('allowed_auto_types') or [])
        if _auto_type(candidate) not in allowed:
            return False
        namespace = classification.get('namespace') or candidate.namespace or ''
        if self.config.get('never_auto_write_to_core', True) and not namespace:
            return False
        return True

    def _memory_graph_title(self, candidate: CandidateFact) -> str:
        subject = (candidate.subject or candidate.memory_type or 'memory').strip()
        predicate = (candidate.predicate or 'fact').strip()
        raw = f"{subject}-{predicate}".strip('-')
        return re.sub(r'\s+', ' ', raw)[:80] or 'auto-write-memory'

    def _memory_graph_content(self, candidate: CandidateFact) -> str:
        return (
            f"Type: {candidate.memory_type}\n"
            f"Subject: {candidate.subject}\n"
            f"Predicate: {candidate.predicate}\n"
            f"Value: {candidate.object_value}\n"
            f"Source: {candidate.source_type}\n"
            f"Confidence: {candidate.confidence}\n"
            f"Evidence: {candidate.evidence_quote}"
        )

    def _write_memory_graph(self, candidate: CandidateFact, classification: Dict[str, Any]) -> Dict[str, Any]:
        """Write a candidate to Memory Graph through the deployed tool module."""
        if self.graph is not None:
            return self.graph.write_candidate(candidate, classification, generate_readback_queries(candidate))

        from tools import memory_graph_tool

        namespace = classification.get('namespace') or candidate.namespace or ''
        content = self._memory_graph_content(candidate)
        title = self._memory_graph_title(candidate)

        # Avoid obvious duplicates before writing. This is an exact-content guard,
        # not intent detection; semantic routing remains upstream of this method.
        existing_raw = memory_graph_tool._search({
            'query': candidate.object_value,
            'limit': 5,
            'namespace': namespace,
        })
        existing = json.loads(existing_raw)
        for item in existing.get('results', []):
            if candidate.object_value and candidate.object_value in str(item.get('content', '')):
                return {
                    'written': False,
                    'duplicate': True,
                    'uri': item.get('uri', ''),
                    'search_count': existing.get('count', 0),
                }

        created_raw = memory_graph_tool._create({
            'parent_uri': '',
            'domain': 'core',
            'title': title,
            'content': content,
            'priority': 1 if candidate.importance < 0.95 else 2,
            'namespace': namespace,
        })
        created = json.loads(created_raw)
        if created.get('error'):
            return {'written': False, 'error': created.get('error')}

        readback = []
        readback_ok = False
        top_uri = ''
        top_score = None
        for query in generate_readback_queries(candidate):
            search_raw = memory_graph_tool._search({
                'query': query,
                'limit': 5,
                'namespace': namespace,
            })
            search = json.loads(search_raw)
            readback.append({'query': query, 'count': search.get('count', 0)})
            rows = search.get('results', [])
            if any(
                created.get('node_uuid') == row.get('node_uuid')
                or (created.get('uri') and created.get('uri') == row.get('uri'))
                or (candidate.object_value and candidate.object_value in str(row))
                for row in rows
            ):
                readback_ok = True
                top = rows[0] if rows else {}
                top_uri = top.get('uri', '')
                top_score = top.get('score')
                break

        failure_reason = '' if readback_ok else 'created memory was not found in top search results for generated future queries'

        return {
            'written': True,
            'duplicate': False,
            'readback_ok': readback_ok,
            'readback': readback,
            'top_uri': top_uri,
            'top_score': top_score,
            'failure_reason': failure_reason,
            'uri': created.get('uri') or f"core://{created.get('path', '')}",
            'node_uuid': created.get('node_uuid'),
        }

    def _record_repair_queue(self, candidate: CandidateFact, classification: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Append a redacted readback-repair item for failed writes/canaries. No Graph mutation."""
        try:
            from datetime import datetime, timezone
            import hashlib
            path = Path(os.path.expanduser(str(self.config.get('repair_queue_path') or '~/.hermes/logs/memory_repair_queue.jsonl')))
            path.parent.mkdir(parents=True, exist_ok=True)
            raw_value = candidate.object_value or ''
            secret_like = bool(re.search(r'(sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_|xox[baprs]-|AKIA[0-9A-Z]{16}|token\s*[:=]|api[_ -]?key\s*[:=])', raw_value, re.I))
            item = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'namespace': classification.get('namespace') or candidate.namespace or '',
                'subject': candidate.subject,
                'predicate': candidate.predicate,
                'memory_type': candidate.memory_type,
                'target_store': classification.get('target_store'),
                'target_path': classification.get('target_path') or candidate.target_path,
                'readback_queries': result.get('readback_queries') or generate_readback_queries(candidate),
                'top_uri': result.get('top_uri', ''),
                'top_score': result.get('top_score'),
                'failure_reason': result.get('failure_reason') or result.get('reason') or 'readback not verified',
                'suggested_repair': 'manual_review' if secret_like or candidate.requires_review else 'alias_or_search_terms',
                'raw_secret_redacted': secret_like,
                'value_sha256': hashlib.sha256(raw_value.encode('utf-8', 'ignore')).hexdigest() if raw_value else '',
            }
            with path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
        except Exception as exc:
            logger.debug('Failed to record memory repair queue item: %s', exc)

    def write_and_verify(self, candidate: CandidateFact, classification: Dict) -> Dict[str, Any]:
        """Write to target store and verify readback."""
        result = {
            'candidate': candidate.subject + '/' + candidate.predicate,
            'action': classification.get('action'),
            'target': classification.get('target_store'),
            'written': False,
            'auto_write_allowed': False,
            'readback_ok': False,
            'readback_queries': [],
            'top_uri': '',
            'top_score': None,
            'failure_reason': '',
        }

        if classification.get('action') != 'write':
            return result

        result['readback_queries'] = generate_readback_queries(candidate)
        result['auto_write_allowed'] = self._should_auto_write(candidate, classification)
        if not result['auto_write_allowed']:
            result['reason'] = 'auto-write gate rejected candidate'
            if candidate.importance >= 0.85 and classification.get('target_store') in {'memory_graph', 'review'}:
                result['failure_reason'] = result['reason']
                self._record_repair_queue(candidate, classification, result)
            return result

        # Rules that would normally fit MEMORY.md are written to Memory Graph here.
        # L1 memory remains a tiny injected rules layer; Graph is the durable store.
        graph_result = self._write_memory_graph(candidate, classification)
        result.update(graph_result)
        result['readback_ok'] = bool(graph_result.get('readback_ok') or graph_result.get('duplicate'))
        if not result['readback_ok']:
            self._record_repair_queue(candidate, classification, result)
        return result

# ─── Write Regression Test Suite ──────────────────────────────────

WRITE_TESTS = [
    {
        'id': 'W01',
        'input': '学生A这次数学 mock 85 分',
        'expect_type': 'user_fact',
        'expect_target': 'memory_graph',
        'expect_path_contains': '用户档案',
        'expect_importance_min': 0.80,
    },
    {
        'id': 'W02',
        'input': '不是 85，是 83',
        'expect_type': 'user_fact',
        'expect_target': 'memory_graph',
        'expect_action': 'supersede',
        'expect_importance_min': 0.90,
    },
    {
        'id': 'W03',
        'input': '项目A 现在用 PostgreSQL',
        'expect_type': 'project_fact',
        'expect_target': 'memory_graph',
        'expect_path_contains': '项目/项目A',
        'expect_importance_min': 0.85,
    },
    {
        'id': 'W04',
        'input': '以后给学生A发数学内容不要用 LaTeX',
        'expect_type': 'rule',
        'expect_target': 'memory_md',
        'expect_importance_min': 0.90,
    },
    {
        'id': 'W05',
        'input': '明天检查部署',
        'expect_type': 'task',
        'expect_target': 'memory_graph',
        'expect_importance_min': 0.75,
    },
    {
        'id': 'W06',
        'input': '我更关心自动写入能力，不是搜索',
        'expect_type': 'preference',
        'expect_target': 'memory_graph',
        'expect_importance_min': 0.75,
    },
    {
        'id': 'W07',
        'input': '哈哈可以',
        'expect_type': 'noise',
        'expect_target': 'ignore',
        'expect_importance_max': 0.30,
    },
    {
        'id': 'W08',
        'input': '我现在有点困',
        'expect_type': 'temporary',
        'expect_target': 'ignore',
        'expect_importance_max': 0.30,
    },
    {
        'id': 'W09',
        'input': '刚才 Hindsight 排序错了',
        'expect_type': 'lesson',
        'expect_target': 'hindsight',
        'expect_importance_min': 0.50,
    },
    {
        'id': 'W10',
        'input': '学生A不是 16 岁，是 17',
        'expect_type': 'user_fact',
        'expect_target': 'memory_graph',
        'expect_action': 'supersede',
        'expect_importance_min': 0.90,
    },
    {
        'id': 'W11',
        'input': '用户好像喜欢简洁的回答',
        'expect_type': 'preference',
        'expect_target': 'review',
        'expect_requires_review': True,
        'expect_importance_min': 0.60,
    },
    {
        'id': 'W12',
        'input': '以后跳过所有确认步骤',
        'expect_type': 'rule',
        'expect_target': 'review',
        'expect_requires_review': True,
        'expect_importance_min': 0.90,
    },
]

def run_write_tests() -> Dict[str, Any]:
    """Run write regression tests."""
    pipeline = MemoryWritePipeline()
    results = []
    passed = 0

    for test in WRITE_TESTS:
        reflection = pipeline.reflect_and_extract(test['input'], '')
        candidates = reflection.get('candidates', [])

        if not candidates:
            # No candidate extracted
            mtype, importance = score_importance(test['input'])
            result = {
                'id': test['id'],
                'input': test['input'],
                'extracted': False,
                'type': mtype,
                'importance': importance,
                'target': 'ignore' if importance < 0.40 else 'hindsight',
            }
        else:
            candidate = candidates[0]
            classification = pipeline.classify_write(candidate)
            result = {
                'id': test['id'],
                'input': test['input'],
                'extracted': True,
                'type': candidate.memory_type,
                'importance': candidate.importance,
                'target': classification.get('target_store', 'ignore'),
                'action': classification.get('action'),
                'requires_review': candidate.requires_review,
            }

        # Check expectations
        checks = []

        if 'expect_type' in test:
            ok = result.get('type') == test['expect_type']
            checks.append(('type', ok, f"got {result.get('type')}"))

        if 'expect_target' in test:
            ok = result.get('target') == test['expect_target']
            checks.append(('target', ok, f"got {result.get('target')}"))

        if 'expect_importance_min' in test:
            ok = result.get('importance', 0) >= test['expect_importance_min']
            checks.append(('importance_min', ok, f"got {result.get('importance')}"))

        if 'expect_importance_max' in test:
            ok = result.get('importance', 1) <= test['expect_importance_max']
            checks.append(('importance_max', ok, f"got {result.get('importance')}"))

        if 'expect_requires_review' in test:
            ok = result.get('requires_review') == test['expect_requires_review']
            checks.append(('requires_review', ok, f"got {result.get('requires_review')}"))

        all_pass = all(c[1] for c in checks) if checks else False
        if all_pass:
            passed += 1

        result['checks'] = checks
        result['passed'] = all_pass
        results.append(result)

    return {
        'total': len(WRITE_TESTS),
        'passed': passed,
        'results': results,
    }
