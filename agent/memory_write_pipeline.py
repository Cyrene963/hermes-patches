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
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)


# ─── Shadow Write Log Rotation ───────────────────────────────────────

class ShadowWriteLogger:
    """Manages shadow write logs with rotation, daily limits, and retention."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        shadow_cfg = config.get('shadow', {})

        # Get configuration
        log_dir = Path(os.path.expanduser(shadow_cfg.get('log_dir', '~/.hermes/logs/shadow_writes')))
        self.log_dir = log_dir
        self.max_entries_per_day = shadow_cfg.get('max_entries_per_day', 1000)
        self.retention_days = shadow_cfg.get('retention_days', 30)
        self.max_file_size = shadow_cfg.get('max_file_size_mb', 10) * 1024 * 1024  # Convert to bytes

        # Create log directory
        log_dir.mkdir(parents=True, exist_ok=True)

        # Daily entry counter
        self._daily_count = 0
        self._current_date = None

        # Initialize daily log file path
        self._update_log_file()

    def _update_log_file(self) -> None:
        """Update the log file path for the current date."""
        today = datetime.now(timezone.utc).date()

        # Generate log file path first
        date_str = today.strftime('%Y-%m-%d')
        self.current_log_path = self.log_dir / f"shadow_{date_str}.jsonl"

        # Reset counter if date changed
        if self._current_date != today:
            self._current_date = today
            self._daily_count = self._count_today_entries()

    def _count_today_entries(self) -> int:
        """Count existing entries in today's log file."""
        if not self.current_log_path.exists():
            return 0

        try:
            with open(self.current_log_path, 'r', encoding='utf-8') as f:
                return sum(1 for _ in f)
        except Exception as exc:
            logger.warning(f"Failed to count today's entries: {exc}")
            return 0

    def log_shadow_write(self, candidate: 'CandidateFact', classification: Dict[str, Any],
                         result: Dict[str, Any]) -> bool:
        """Log a shadow write entry. Returns True if logged, False if limit reached."""
        self._update_log_file()

        # Check daily limit
        if self._daily_count >= self.max_entries_per_day:
            logger.warning(
                f"Shadow write daily limit reached ({self.max_entries_per_day}). "
                "Entry not logged."
            )
            return False

        # Prepare log entry
        try:
            entry = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'date': self._current_date.isoformat(),
                'subject': candidate.subject,
                'predicate': candidate.predicate,
                'object_value': candidate.object_value[:500],  # Truncate long values
                'memory_type': candidate.memory_type,
                'importance': candidate.importance,
                'confidence': candidate.confidence,
                'source_type': candidate.source_type,
                'target_store': classification.get('target_store'),
                'target_path': classification.get('target_path') or candidate.target_path,
                'action': classification.get('action'),
                'requires_review': candidate.requires_review or classification.get('requires_review', False),
                'namespace': classification.get('namespace') or candidate.namespace,
                'auto_write_allowed': result.get('auto_write_allowed', False),
                'written': result.get('written', False),
                'readback_ok': result.get('readback_ok', False),
                'evidence_quote': candidate.evidence_quote[:200],  # Truncate evidence
            }

            # Write to log file (append mode)
            with open(self.current_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

            self._daily_count += 1
            return True

        except Exception as exc:
            logger.error(f"Failed to log shadow write: {exc}")
            return False

    def cleanup_old_logs(self) -> Dict[str, Any]:
        """Delete log files older than retention_days. Returns cleanup stats."""
        if self.retention_days <= 0:
            return {'deleted': 0, 'reason': 'retention disabled'}

        cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=self.retention_days)
        deleted = []
        errors = []

        try:
            for log_file in self.log_dir.glob('shadow_*.jsonl'):
                # Extract date from filename: shadow_YYYY-MM-DD.jsonl
                try:
                    date_str = log_file.stem.replace('shadow_', '')
                    file_date = datetime.strptime(date_str, '%Y-%m-%d').date()

                    if file_date < cutoff_date:
                        file_size = log_file.stat().st_size
                        log_file.unlink()
                        deleted.append({
                            'file': log_file.name,
                            'date': date_str,
                            'size_bytes': file_size,
                        })
                        logger.info(f"Deleted old shadow log: {log_file.name} (age: {(datetime.now(timezone.utc).date() - file_date).days} days)")

                except ValueError as ve:
                    # Filename doesn't match expected format
                    logger.debug(f"Skipping file with unexpected name format: {log_file.name}")
                except Exception as exc:
                    errors.append({
                        'file': log_file.name,
                        'error': str(exc),
                    })
                    logger.warning(f"Failed to delete {log_file.name}: {exc}")

        except Exception as exc:
            logger.error(f"Shadow log cleanup failed: {exc}")
            return {
                'deleted': len(deleted),
                'errors': len(errors),
                'error': str(exc),
            }

        return {
            'deleted': len(deleted),
            'deleted_files': deleted,
            'errors': errors,
            'cutoff_date': cutoff_date.isoformat(),
            'retention_days': self.retention_days,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about shadow write logs."""
        stats = {
            'log_dir': str(self.log_dir),
            'current_date': self._current_date.isoformat() if self._current_date else None,
            'daily_count': self._daily_count,
            'daily_limit': self.max_entries_per_day,
            'remaining_today': max(0, self.max_entries_per_day - self._daily_count),
            'retention_days': self.retention_days,
            'files': [],
            'total_entries': 0,
            'total_size_bytes': 0,
        }

        try:
            for log_file in sorted(self.log_dir.glob('shadow_*.jsonl')):
                file_stats = log_file.stat()
                entry_count = sum(1 for _ in open(log_file, 'r', encoding='utf-8'))

                stats['files'].append({
                    'name': log_file.name,
                    'size_bytes': file_stats.st_size,
                    'entries': entry_count,
                    'modified': datetime.fromtimestamp(file_stats.st_mtime, tz=timezone.utc).isoformat(),
                })
                stats['total_entries'] += entry_count
                stats['total_size_bytes'] += file_stats.st_size

        except Exception as exc:
            logger.warning(f"Failed to collect shadow log stats: {exc}")
            stats['error'] = str(exc)

        return stats


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
        "shadow": {
            "log_dir": "~/.hermes/logs/shadow_writes",
            "max_entries_per_day": 1000,
            "retention_days": 30,
            "max_file_size_mb": 10,
            "enable_readback_dryrun": True,
        },
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

    Returns types matching allowed_auto_types in memory_write_config.yaml:
    - explicit_correction, explicit_preference, target_function,
      procedural_memory, decision, user_fact
    """
    if candidate.source_type == "user_correction":
        return "explicit_correction"
    if candidate.memory_type == "preference" and candidate.source_type == "user_direct":
        return "explicit_preference"
    if candidate.memory_type in {"target_function", "procedural_memory", "decision", "user_fact"} and candidate.source_type == "user_direct":
        return candidate.memory_type
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

        # Initialize shadow write logger
        try:
            self.shadow_logger = ShadowWriteLogger(self.config)
        except Exception as exc:
            logger.warning(f"Failed to initialize shadow write logger: {exc}")
            self.shadow_logger = None

    def reflect_and_extract(self, user_msg: str, assistant_msg: str) -> Dict[str, Any]:
        """Generate memory reflection from a conversation turn."""
        combined = f"{user_msg} {assistant_msg}"
        mtype, importance = score_importance(combined)

        # System/skill wrapper text can be injected into the user-message channel
        # by the runtime. It is not a user-authored learning event and must never
        # become a ReviewProposal or Memory Graph candidate. Keep this fail-closed:
        # return no candidates rather than trying to extract around wrapper text.
        wrapper_markers = (
            '[IMPORTANT: The user has invoked the',
            'The full skill content is loaded below',
            '<available_skills>',
            'metadata:\n  hermes:',
        )
        if any(marker in user_msg for marker in wrapper_markers):
            return {
                'candidates': [],
                'importance': 0.0,
                'memory_type': 'ignore',
                'evidence': '',
                'ignored_reason': 'system_or_skill_wrapper_not_user_text',
            }

        candidates = []

        # Claude Code-derived auto-store heuristic: use it as a default-on
        # candidate discovery signal, not as a direct write path. The normal
        # MemoryWritePipeline gates below still decide shadow/review/write, so
        # this widens recall of explicit "remember/prefer/correction" messages
        # without bypassing namespace, review, readback, or auto-write policy.
        try:
            from agent.auto_store_heuristic import detect_auto_store
            _should_store, _auto_confidence, _auto_patterns = detect_auto_store(user_msg)
        except Exception:
            _should_store, _auto_confidence, _auto_patterns = False, 0.0, []
        if _should_store:
            _auto_type = 'preference' if any(
                'preference' in p.lower() or 'habit' in p.lower()
                for p in _auto_patterns
            ) else 'procedural_memory'
            _auto_source = 'user_correction' if any(
                'correction' in p.lower()
                for p in _auto_patterns
            ) else 'user_direct'
            _auto_target_path = '用户档案/偏好' if _auto_type == 'preference' else '用户档案/程序性记忆'
            # Upstream LLM classification: decide durable + extract a CLEAN atomic fact
            # ONCE here, so the candidate entering classify_write is high-quality (real
            # subject + full fact → passes the content/quality filter) and the auto-write
            # gate needs no second LLM call. Fail-closed: LLM off/unreachable → not durable
            # → requires_review (no auto-write), falling back to the rule distiller object.
            _llm_durable = None
            _llm_subject = 'self'
            _object_value = None
            _subject = 'auto_store_heuristic'
            try:
                from agent.memory_fact_classifier import classifier_enabled, classify_fact
                if classifier_enabled():
                    _v = classify_fact(user_msg)
                    _llm_durable = bool(_v.durable)
                    _llm_subject = getattr(_v, 'subject', 'self') or 'self'
                    if _v.durable and _v.fact:
                        _object_value = _v.fact
                        _subject = {'preference': '用户偏好', 'correction': '用户纠正',
                                    'decision': '用户决定', 'profile': '用户档案'}.get(_v.kind, '用户事实')
                        if _v.kind == 'correction':
                            _auto_source = 'user_correction'
            except Exception:
                _llm_durable = None
            if _object_value is None:  # LLM unavailable/disabled → rule distiller fallback
                try:
                    from agent.memory_distiller import distill_fact
                    _distilled, _distill_ok = distill_fact(user_msg)
                except Exception:
                    _distilled, _distill_ok = user_msg.strip()[:1000], False
                _object_value = _distilled if (_distill_ok and _distilled) else user_msg.strip()[:1000]
            # Auto-write only when the LLM positively confirmed durability; otherwise review.
            _requires_review = (_llm_durable is not True)
            _cand = CandidateFact(
                subject=_subject,
                predicate='explicit_memory_signal',
                object_value=_object_value,
                importance=max(0.85, min(0.98, _auto_confidence)),
                memory_type=_auto_type,
                target_store='memory_graph',
                target_path=_auto_target_path,
                evidence_quote=user_msg[:1000],
                confidence=max(0.85, min(0.98, _auto_confidence)),
                source_type=_auto_source,
                requires_review=_requires_review,
                reason='; '.join(_auto_patterns[:5]),
            )
            _cand.llm_durable = _llm_durable
            _cand.llm_subject = _llm_subject
            candidates.append(_cand)

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
                sem_candidate = CandidateFact(
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
                )
                if sem_kind == 'correction_learning_event':
                    try:
                        from agent.correction_regression import build_correction_case, record_correction_case

                        correction_case = build_correction_case(
                            evidence_text=sem.evidence_quote,
                            namespace=sem_candidate.namespace or '',
                            memory_kind=sem_kind,
                            target_store=sem.target_store,
                            requires_review=sem_requires_review,
                            reject_gate=sem.reject_gate,
                            future_queries=sem.readback_queries,
                        )
                        correction_record = record_correction_case(
                            correction_case,
                            ledger_path=self.config.get('correction_regression_path'),
                        )
                        sem_candidate.correction_case_id = correction_case.case_id
                        sem_candidate.changeset_id = correction_case.changeset_id
                        sem_candidate.correction_regression_record = correction_record
                    except Exception as exc:
                        logger.debug('Correction regression artifact failed closed: %s', exc)
                candidates.append(sem_candidate)
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

        # Hygiene gate: drop candidates whose object is a raw truncated copy of the
        # user message, a reply-quote, a question, secret-bearing, or too short.
        # A shadow-log audit found 84.2% of candidates were raw_truncated_copy and
        # 2% leaked secrets — these must never reach review/write. Fail-open on any
        # internal error so this never blocks legitimate extraction.
        try:
            from agent.memory_write_earn import hygiene_flags
            _kept = []
            for c in candidates:
                _flags = hygiene_flags(str(getattr(c, 'object_value', '') or ''), user_msg)
                _hard = {'contains_secret', 'raw_truncated_copy', 'is_question', 'too_short'}
                if _flags and (_hard & set(_flags)):
                    logger.debug('Hygiene gate dropped candidate %s: %s',
                                 getattr(c, 'subject', '?'), ','.join(_flags))
                    continue
                _kept.append(c)
            candidates = _kept
        except Exception as exc:
            logger.debug('Hygiene gate skipped (fail-open): %s', exc)

        return {
            'candidates': candidates,
            'importance': importance,
            'memory_type': mtype,
            'evidence': user_msg[:200],
        }

    def classify_write(self, candidate: CandidateFact, existing_facts: List[Dict] = None, namespace: str = "") -> Dict[str, Any]:
        """Apply 5 gates to determine if and where to write."""
        existing = existing_facts or []

        # Gate 1: Candidate quality / pollution guard. This only rejects obvious
        # wrappers, logs, empty fragments, or system events; durable user-authored
        # signals continue into the normal review/auto-write policy below.
        try:
            from agent.memory_write_filters import evaluate_memory_candidate_quality
            quality = evaluate_memory_candidate_quality(
                subject=candidate.subject,
                predicate=candidate.predicate,
                object_value=candidate.object_value,
                memory_type=candidate.memory_type,
                source_type=candidate.source_type,
                evidence_quote=candidate.evidence_quote,
                importance=candidate.importance,
                confidence=candidate.confidence,
            )
        except Exception as exc:
            logger.debug('Memory quality filter failed open to review: %s', exc)
            quality = None
        if quality is not None and not quality.accepted:
            return {'action': 'ignore', 'reason': quality.reason, 'target_store': 'ignore'}
        if quality is not None and quality.requires_review:
            candidate.requires_review = True

        # Gate 2: Importance
        if candidate.importance < 0.40:
            return {'action': 'ignore', 'reason': 'Low importance'}

        # Gate 3: Type (already classified)

        # Gate 4: Conflict
        conflict_uri = detect_conflict(candidate, existing)
        if conflict_uri:
            candidate.conflict_with = conflict_uri
            explicit_correction = candidate.source_type == 'user_correction'
            safe_namespace = bool(namespace or candidate.namespace)
            mode = str(self.config.get('mode', 'shadow')).strip().lower()
            allow_supersede = bool(self.config.get('auto_supersede_user_corrections', True))
            if (
                explicit_correction
                and safe_namespace
                and allow_supersede
                and mode in {'limited_auto', 'full_auto'}
                and candidate.confidence >= float(self.config.get('auto_write_threshold', 0.85))
            ):
                return {
                    'action': 'supersede',
                    'target_store': 'memory_graph',
                    'target_path': candidate.target_path,
                    'conflict_with': conflict_uri,
                    'namespace': namespace or candidate.namespace,
                    'requires_review': False,
                }
            candidate.requires_review = True
            return {
                'action': 'review',
                'target_store': 'review',
                'reason': f'Conflicts with existing fact: {conflict_uri}',
                'conflict_with': conflict_uri
            }

        # Gate 4: Dedup
        candidate.dedup_key = make_dedup_key(candidate)
        # Query existing facts by dedup_key to avoid duplicates
        try:
            from tools import memory_graph_tool
            dedup_search_raw = memory_graph_tool._search({
                'query': f"{candidate.subject} {candidate.predicate} {candidate.object_value[:50]}",
                'limit': 5,
                'namespace': namespace,
            })
            dedup_search = json.loads(dedup_search_raw)
            for item in dedup_search.get('results', []):
                item_content = str(item.get('content', ''))
                item_title = str(item.get('title', ''))
                # Check if the dedup_key components match
                if (candidate.subject.lower() in item_title.lower() or candidate.subject.lower() in item_content.lower()):
                    if (candidate.predicate.lower() in item_content.lower() and
                        candidate.object_value.lower()[:50] in item_content.lower()):
                        return {
                            'action': 'ignore',
                            'reason': f'Duplicate fact already exists: {item.get("uri", "")}',
                            'target_store': 'ignore',
                            'duplicate_uri': item.get('uri', '')
                        }
        except Exception as exc:
            logger.debug('Dedup check failed; continuing to write: %s', exc)

        # Gate 5a: Sensitive review-only routes must remain in the review lane.
        # They should never auto-write, but they must still produce redacted
        # repair/review records for auditability instead of disappearing into
        # low-ROI clarification-on-use queues.
        clarification_queue_enabled = bool(self.config.get('clarification_queue_path'))
        sensitive_review_route = bool(
            not clarification_queue_enabled
            and (
                candidate.target_store == 'review'
                or re.search(
                    r'(credential|credentials|secret|token|api[_ -]?key|密钥|凭据|密码)',
                    f"{candidate.subject}\n{candidate.predicate}\n{candidate.memory_type}\n{candidate.target_path}\n{candidate.object_value}",
                    re.I,
                )
            )
        )
        if candidate.requires_review and sensitive_review_route:
            return {
                'action': 'write',
                'target_store': 'review',
                'target_path': candidate.target_path,
                'requires_review': True,
                'dedup_key': candidate.dedup_key,
                'namespace': namespace or candidate.namespace,
            }

        # Gate 5b: Clarification-on-use instead of low-ROI batch review.
        # Uncertain memories should not pile up for manual WebUI approval. Keep
        # them as pending clarification candidates and surface them only when a
        # future task would rely on them.
        if candidate.source_type == 'agent_inference':
            candidate.requires_review = True
            return {'action': 'clarify_later', 'target_store': 'clarification', 'reason': 'Agent inference should be confirmed when relevant'}
        # Check for sensitive rules
        sensitive_patterns = ['跳过', '绕过', '忽略', '不需要确认', '自动']
        if any(p in candidate.object_value for p in sensitive_patterns):
            candidate.requires_review = True
            return {'action': 'clarify_later', 'target_store': 'clarification', 'reason': 'Sensitive rule should be confirmed when relevant'}

        # Determine target store
        target = route_target(candidate.memory_type, candidate.importance,
                             candidate.memory_type == 'rule')

        # Override if candidate already has a target (from extraction)
        if candidate.target_store and candidate.target_store != 'ignore':
            target = candidate.target_store

        # If requires_review, route to clarification-on-use rather than a batch
        # WebUI approval queue. This preserves safety while avoiding low-ROI
        # manual review work.
        if candidate.requires_review:
            target = 'clarification'

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
        # Subject routing: a fact ABOUT another person must NOT auto-write into the
        # speaker's namespace (that is exactly the mis-filing that polluted a user's
        # private memory with a friend's profile). Default: route such facts to
        # review. If subject_auto_route is enabled AND the subject maps to a known
        # user's namespace, retarget the write to that user's namespace instead.
        _subj = getattr(candidate, 'llm_subject', 'self')
        if _subj and str(_subj).strip().lower() not in {'self', '用户', 'me', 'owner', '本人', 'speaker'}:
            try:
                from agent.memory_fact_classifier import resolve_subject_namespace
                target_ns, is_other = resolve_subject_namespace(_subj, namespace)
            except Exception:
                target_ns, is_other = None, True
            if is_other:
                if self.config.get('subject_auto_route', False) and target_ns and target_ns != namespace:
                    candidate.namespace = target_ns
                    classification['namespace'] = target_ns
                    namespace = target_ns
                else:
                    return False  # about someone else, unmapped or routing off → review, never the speaker's ns
        # Final precision gate: an LLM must confirm this is a durable fact. The
        # classification is normally done ONCE upstream (candidate.llm_durable); only
        # fall back to classifying here if it wasn't. FAIL-CLOSED: disabled/unreachable
        # classifier → not durable → no auto-write (candidate goes to review).
        if self.config.get('require_llm_classifier', True):
            _ld = getattr(candidate, 'llm_durable', None)
            if _ld is True:
                pass  # already confirmed durable upstream (no second LLM call)
            elif _ld is False:
                return False
            else:
                try:
                    from agent.memory_fact_classifier import classifier_enabled, classify_fact
                    if not classifier_enabled():
                        return False
                    verdict = classify_fact(candidate.evidence_quote or candidate.object_value or '')
                    if not verdict.durable:
                        return False
                    if verdict.fact:
                        candidate.object_value = verdict.fact
                except Exception:
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

    def _write_hindsight(self, candidate: CandidateFact, classification: Dict[str, Any]) -> Dict[str, Any]:
        """Write a candidate to Hindsight for semantic/episodic memory storage.

        Hindsight stores lower-importance facts and contextual memories that don't
        require structured graph storage but should be semantically searchable.
        """
        if self.hindsight is None:
            return {
                'written': False,
                'target': 'hindsight',
                'error': 'Hindsight client not available',
            }

        try:
            # Format memory for Hindsight storage
            memory_text = f"{candidate.subject}: {candidate.predicate} = {candidate.object_value}"

            # Add metadata for better retrieval
            metadata = {
                'memory_type': candidate.memory_type,
                'importance': candidate.importance,
                'confidence': candidate.confidence,
                'source_type': candidate.source_type,
                'target_path': candidate.target_path,
                'evidence': candidate.evidence_quote[:200] if candidate.evidence_quote else '',
            }

            # Write to Hindsight using the client
            write_result = self.hindsight.store(
                text=memory_text,
                metadata=metadata,
                namespace=classification.get('namespace') or candidate.namespace or 'core',
            )

            return {
                'written': True,
                'target': 'hindsight',
                'readback_ok': True,  # Hindsight confirms storage on write
                'hindsight_id': write_result.get('id'),
            }

        except Exception as exc:
            logger.warning('Hindsight write failed: %s', exc)
            return {
                'written': False,
                'target': 'hindsight',
                'error': str(exc),
                'failure_reason': f'hindsight write failed: {exc}',
            }

    def _record_repair_queue(self, candidate: CandidateFact, classification: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Append a redacted repair/review item for blocked or failed memory writes."""
        try:
            from datetime import datetime, timezone
            import hashlib

            path = Path(os.path.expanduser(str(self.config.get('repair_queue_path') or '~/.hermes/logs/memory_repair_queue.jsonl')))
            path.parent.mkdir(parents=True, exist_ok=True)

            raw_value = candidate.object_value or ''
            raw_evidence = candidate.evidence_quote or ''
            sensitive_route = bool(re.search(
                r'(credential|credentials|secret|token|api[_ -]?key|密钥|凭据|密码)',
                f"{candidate.subject}\n{candidate.predicate}\n{candidate.target_path}\n{classification.get('target_path', '')}",
                re.I,
            ))
            raw_secret_detected = bool(re.search(
                r'(sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_|xox[baprs]-|AKIA[0-9A-Z]{16}|token\s*[:=]|api[_ -]?key\s*[:=])',
                f"{raw_value}\n{raw_evidence}",
                re.I,
            ))
            preview_redacted = sensitive_route or raw_secret_detected

            def _preview(text: str, limit: int = 500) -> str:
                text = re.sub(r'\s+', ' ', text or '').strip()
                if not text:
                    return ''
                if preview_redacted:
                    return '[redacted: sensitive review content]'
                return text[:limit]

            failure_reason = result.get('failure_reason') or result.get('reason') or 'readback not verified'
            item = {
                'schema_version': 2,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'status': 'pending',
                'namespace': classification.get('namespace') or candidate.namespace or '',
                'subject': candidate.subject,
                'predicate': candidate.predicate,
                'memory_type': candidate.memory_type,
                'source_type': candidate.source_type,
                'importance': candidate.importance,
                'confidence': candidate.confidence,
                'target_store': classification.get('target_store'),
                'target_path': classification.get('target_path') or candidate.target_path,
                'requires_review': bool(candidate.requires_review or classification.get('requires_review')),
                'auto_write_allowed': bool(result.get('auto_write_allowed')),
                'actually_written': bool(result.get('written')),
                'readback_ok': bool(result.get('readback_ok')),
                'readback_queries': result.get('readback_queries') or generate_readback_queries(candidate),
                'top_uri': result.get('top_uri', ''),
                'top_score': result.get('top_score'),
                'failure_reason': failure_reason,
                'suggested_repair': 'manual_review' if preview_redacted or candidate.requires_review or classification.get('target_store') == 'review' else 'alias_or_search_terms',
                'content_preview': _preview(raw_value),
                'evidence_preview': _preview(raw_evidence),
                'raw_secret_redacted': raw_secret_detected,
                'value_sha256': hashlib.sha256(raw_value.encode('utf-8', 'ignore')).hexdigest() if raw_value else '',
                'changeset_id': getattr(candidate, 'changeset_id', ''),
                'correction_case_id': getattr(candidate, 'correction_case_id', ''),
            }
            with path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
        except Exception as exc:
            logger.debug('Failed to record memory repair queue item: %s', exc)

    def _supersede_and_verify(self, candidate: CandidateFact, classification: Dict[str, Any]) -> Dict[str, Any]:
        """Version an explicit correction and prove stale content is no longer active."""
        namespace = str(classification.get('namespace') or candidate.namespace or '')
        uri = str(classification.get('conflict_with') or candidate.conflict_with or '')
        result = {
            'candidate': candidate.subject + '/' + candidate.predicate,
            'action': 'supersede',
            'target': 'memory_graph',
            'written': False,
            'auto_write_allowed': False,
            'readback_ok': False,
            'superseded_uri': uri,
            'failure_reason': '',
        }
        if candidate.source_type != 'user_correction' or not namespace or not uri:
            result['failure_reason'] = 'supersede requires explicit user correction, namespace, and conflict URI'
            return result
        try:
            if self.graph is not None and hasattr(self.graph, 'supersede_candidate'):
                graph_result = self.graph.supersede_candidate(candidate, classification)
            else:
                from tools import memory_graph_tool

                old = json.loads(memory_graph_tool._read({'uri': uri, 'namespace': namespace}))
                if old.get('error'):
                    raise ValueError(old['error'])
                old_content = str(old.get('content') or '')
                updated_content = self._memory_graph_content(candidate)
                graph_result = json.loads(memory_graph_tool._update({
                    'uri': uri,
                    'content': updated_content,
                    'priority': 2 if candidate.importance >= 0.95 else 1,
                    'namespace': namespace,
                }))
                if graph_result.get('error'):
                    raise ValueError(graph_result['error'])
                new_query = f"{candidate.subject} {candidate.predicate} {candidate.object_value}"
                old_query = f"{candidate.subject} {candidate.predicate} {old_content[:120]}"
                new_rows = json.loads(memory_graph_tool._search({
                    'query': new_query, 'limit': 5, 'namespace': namespace,
                })).get('results', [])
                old_rows = json.loads(memory_graph_tool._search({
                    'query': old_query, 'limit': 5, 'namespace': namespace,
                })).get('results', [])
                current = json.loads(memory_graph_tool._read({'uri': uri, 'namespace': namespace}))
                if current.get('error'):
                    raise ValueError(current['error'])
                graph_result.update({
                    'old_content': old_content,
                    'current_content': str(current.get('content') or ''),
                    'new_results': new_rows,
                    'old_results': old_rows,
                })

            new_rows = list(graph_result.get('new_results') or [])
            old_rows = list(graph_result.get('old_results') or [])
            top_new = new_rows[0] if new_rows else {}
            top_old = old_rows[0] if old_rows else {}
            top_new_text = f"{top_new.get('content', '')}\n{top_new.get('snippet', '')}".lower()
            new_ok = bool(
                top_new
                and (
                    top_new.get('uri') == uri
                    or candidate.object_value.lower() in top_new_text
                )
            )
            stale_value = str(graph_result.get('old_content') or '').strip().lower()
            value_match = re.search(r'(?im)^Value:\s*(.+)$', stale_value)
            if value_match:
                stale_value = value_match.group(1).strip()
            old_top_content = f"{top_old.get('content', '')}\n{top_old.get('snippet', '')}".lower()
            current_content = str(graph_result.get('current_content') or '').lower()
            same_entity_top = bool(top_old and top_old.get('uri') == uri)
            current_is_new = bool(candidate.object_value.lower() in current_content)
            stale_top1 = bool(
                same_entity_top
                and not current_is_new
                and candidate.object_value.lower() not in old_top_content
            )
            if (
                stale_value
                and stale_value in old_top_content
                and candidate.object_value.lower() not in old_top_content
                and not current_is_new
            ):
                stale_top1 = True
            result.update({
                'written': bool(graph_result.get('updated', True)),
                'auto_write_allowed': True,
                'readback_ok': bool(new_ok and not stale_top1),
                'uri': graph_result.get('uri') or uri,
                'memory_id': graph_result.get('memory_id'),
                'old_top1_stale': stale_top1,
                'new_top_uri': top_new.get('uri', ''),
                'old_top_uri': top_old.get('uri', ''),
            })
            if not result['readback_ok']:
                result['failure_reason'] = 'supersede committed but temporal top-1 verification failed'
                self._record_repair_queue(candidate, classification, result)
            return result
        except Exception as exc:
            result['failure_reason'] = f'supersede failed: {exc}'
            self._record_repair_queue(candidate, classification, result)
            return result

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

        if classification.get('action') not in {'write', 'clarify_later', 'supersede'}:
            return result

        if classification.get('action') == 'supersede':
            return self._supersede_and_verify(candidate, classification)

        if classification.get('action') == 'clarify_later' or classification.get('target_store') == 'clarification':
            try:
                from agent.memory_clarification_queue import record_clarification_candidate
                item = record_clarification_candidate(
                    candidate,
                    classification,
                    queue_path=self.config.get('clarification_queue_path'),
                )
                result.update({
                    'target': 'clarification',
                    'queued_for_clarification': True,
                    'clarification_id': item.get('id', ''),
                    'failure_reason': classification.get('reason', 'requires clarification when relevant'),
                })
            except Exception as exc:
                result.update({
                    'target': 'clarification',
                    'queued_for_clarification': False,
                    'failure_reason': f'clarification queue write failed: {exc}',
                })
            return result

        result['readback_queries'] = generate_readback_queries(candidate)
        result['auto_write_allowed'] = self._should_auto_write(candidate, classification)
        if not result['auto_write_allowed']:
            result['reason'] = 'auto-write gate rejected candidate'
            if candidate.importance >= 0.85 and classification.get('target_store') in {'memory_graph', 'review'}:
                result['failure_reason'] = result['reason']
                self._record_repair_queue(candidate, classification, result)
            return result

        # Write to appropriate store based on target_store classification
        target_store = classification.get('target_store')

        if target_store == 'hindsight':
            # Write to Hindsight for facts that don't need structured graph storage
            hindsight_result = self._write_hindsight(candidate, classification)
            result.update(hindsight_result)
            return result

        # Rules that would normally fit MEMORY.md are written to Memory Graph here.
        # L1 memory remains a tiny injected rules layer; Graph is the durable store.
        graph_result = self._write_memory_graph(candidate, classification)
        result.update(graph_result)
        result['readback_ok'] = bool(graph_result.get('readback_ok') or graph_result.get('duplicate'))

        # Write to Hindsight as well for semantic searchability if importance warrants it
        # This allows both structured (Memory Graph) and semantic (Hindsight) retrieval
        if result.get('written') and candidate.importance >= 0.40:
            try:
                self._write_hindsight(candidate, classification)
            except Exception as exc:
                logger.debug('Hindsight parallel write failed (non-fatal): %s', exc)

        if not result['readback_ok']:
            self._record_repair_queue(candidate, classification, result)

        # Log to shadow write log
        if self.shadow_logger and self.config.get('mode') == 'shadow':
            try:
                self.shadow_logger.log_shadow_write(candidate, classification, result)
            except Exception as exc:
                logger.debug(f'Shadow write logging failed (non-fatal): {exc}')

        return result

    def cleanup_shadow_logs(self) -> Dict[str, Any]:
        """Clean up old shadow write logs based on retention policy."""
        if not self.shadow_logger:
            return {'error': 'shadow logger not initialized'}
        return self.shadow_logger.cleanup_old_logs()

    def get_shadow_stats(self) -> Dict[str, Any]:
        """Get statistics about shadow write logs."""
        if not self.shadow_logger:
            return {'error': 'shadow logger not initialized'}
        return self.shadow_logger.get_stats()

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
